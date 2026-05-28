"""Agent Invoker: Docker orchestration for kenv-based agent runs.

This module provides high-level orchestration for running agents in kenv containers:
- Builds and manages Docker images for different agents
- Configures volumes, environment variables, and mounts
- Executes kenv-invoker.py inside containers
- Collects outputs and stores results in kArenaDB

Supported agents: SWE-agent, mini-swe-agent, OpenHands
"""

import asyncio, json, os
from dataclasses import dataclass
import logging
import subprocess as _subprocess
import tempfile
import urllib.request as _urllib_request
from pathlib import Path
from typing import Literal
from pydantic import BaseModel
from traceback import format_exc
from pydantic_core import to_json, from_json
from hashlib import md5
from unidiff import PatchSet

from KBDr.kclient import SyzbotData
from kArena.models import AgentConfiguration, kArenaConfig, kCache
from kArena.model_config_manager import ModelConfigManager

logger = logging.getLogger(__name__)

def filter_binary_files_from_patch(patch_content: str) -> str:
    """Filter out binary file diffs from a patch.

    Args:
        patch_content: The original patch content

    Returns:
        Filtered patch content without binary file diffs.
        If filtering fails, returns the original patch content.
    """
    if not patch_content or not patch_content.strip():
        return patch_content

    try:
        # Parse the patch
        patchset = PatchSet(patch_content)

        # Filter out binary files
        filtered_files = [f for f in patchset if not f.is_binary_file]

        # If no binary files were found, return original
        if len(filtered_files) == len(patchset):
            return patch_content

        # Recompose the patch from non-binary files
        filtered_patch_lines = []
        for patch_file in filtered_files:
            filtered_patch_lines.append(str(patch_file))

        filtered_patch = ''.join(filtered_patch_lines)

        num_binary = len(patchset) - len(filtered_files)
        logger.info(f"Filtered out {num_binary} binary file(s) from patch")

        return filtered_patch
    except Exception as e:
        logger.warning(f"Failed to filter binary files from patch, using original: {e}")
        return patch_content

class LiteLLMProxyManager:
    def __init__(
        self,
        config: 'kArenaConfig',
        *,
        subprocess_factory=_subprocess.Popen,
        health_check_fn=_urllib_request.urlopen,
    ):
        self.config = config
        self._subprocess_factory = subprocess_factory
        self._health_check_fn = health_check_fn
        self._proc = None

    async def __aenter__(self) -> 'LiteLLMProxyManager':
        port = self.config.litellmProxyPort
        self._proc = self._subprocess_factory(
            ['litellm', '--config', str(self.config.litellmProxyConfigPath),
             '--port', str(port), '--host', '0.0.0.0'],
            env=os.environ.copy()
        )
        health_url = f'http://127.0.0.1:{port}/health'
        await asyncio.sleep(15)
        for _ in range(10):
            try:
                self._health_check_fn(health_url, timeout=5)
                logger.info(f'LiteLLM singleton proxy started on port {port}')
                return self
            except Exception:
                await asyncio.sleep(2)
        self._proc.terminate()
        self._proc.wait()
        raise RuntimeError(f'LiteLLM singleton proxy failed to start on port {port}')

    async def __aexit__(self, *_) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait()
            logger.info('LiteLLM singleton proxy stopped')


class AgentResult(BaseModel):
    status: Literal['success', 'error']
    systemMessage: str

    dollarCost: float | None = None
    timeCost: int | None = None
    exitReason: Literal['normal', 'costLimitExceeded', 'timeLimitExceeded'] | None = None

    patch: str | None = None
    trajectory: bytes | None = None
    log: bytes | None = None

@dataclass(frozen=True)
class _WorkspacePaths:
    kbench_path: Path
    oracle_path: Path
    patch_path: Path
    traj_path: Path
    log_path: Path
    stdout_path: Path
    stderr_path: Path
    metadata_path: Path


class AgentInvoker:

    def __init__(
        self,
        config: kArenaConfig,
        bug: SyzbotData,
        agent_config: AgentConfiguration,
        base_commit: Literal['parentCommit', 'crashCommit'],
        stateful_edit: bool,
        kcache: kCache
    ):
        self.config = config
        self.workspace_root = Path(config.workspaceRoot)
        self.bug = bug.model_copy()
        self.clean_bug_fields()
        self.bug_id = bug.bugId
        self.agent_config = agent_config
        self.base_commit = base_commit
        self.kcache = kcache

        # Ensure paths are Path objects
        self.agent_config_path = self.workspace_root / 'shared' / 'agent-configs' / agent_config.agentConfigName
        self._model_config_name = agent_config.modelConfigName
        self._agent = agent_config.agent

        self.stateful_edit = stateful_edit

    def clean_bug_fields(self):
        self.bug.fixCommits = []
        self.bug.discussions = []

        self.bug.causeCommit = None
        self.bug.causeCommitDate = None
        self.bug.causeModifiedFunctions = []

        self.bug.patch = None
        self.bug.patchMessage = None
        self.bug.patchModifiedFiles = None
        self.bug.patchModifiedFunctions = None
        self.bug.patchCommitDate = None

    def _prepare_workspace(self, temp_dir: Path) -> '_WorkspacePaths':
        output_dir = temp_dir / 'output'
        output_dir.mkdir(exist_ok=True)

        kbench_path = temp_dir / 'kBench.json'
        oracle_path = temp_dir / 'oracle-files.txt'

        kbench_data = {
            'dataset': [self.bug],
            'kCache': {self.bug_id: self.kcache.kGymJobId}
        }
        kbench_path.write_bytes(to_json(kbench_data))
        oracle_path.write_text('\n'.join(self.bug.patchModifiedFiles or []))

        patch_path = output_dir / 'patch.txt'
        traj_path = output_dir / 'traj.json'
        log_path = output_dir / 'log.txt'
        metadata_path = output_dir / 'metadata.json'

        patch_path.touch()
        traj_path.touch()
        log_path.touch()
        metadata_path.touch()

        return _WorkspacePaths(
            kbench_path=kbench_path,
            oracle_path=oracle_path,
            patch_path=patch_path,
            traj_path=traj_path,
            log_path=log_path,
            stdout_path=output_dir / 'docker_stdout.txt',
            stderr_path=output_dir / 'docker_stderr.txt',
            metadata_path=metadata_path,
        )

    def _build_docker_cmd(
        self,
        paths: '_WorkspacePaths',
        model_config_path: Path,
        container_name: str,
    ) -> 'list[str] | AgentResult':
        docker_base_commit = f'{self.base_commit[:-len("Commit")]}-commit'

        gcs_credentials_mount: list[str] = []
        gcs_credentials_env: list[str] = []
        if self.config.googleApplicationCredentials is not None:
            if not self.config.googleApplicationCredentials.exists():
                return AgentResult(
                    status='error',
                    systemMessage=f'GCS credentials file not found: {self.config.googleApplicationCredentials}'
                )
            container_creds_path = '/KBDr/gcp-credentials.json'
            gcs_credentials_mount = ['-v', f'{self.config.googleApplicationCredentials.absolute()}:{container_creds_path}:ro']
            gcs_credentials_env = ['-e', f'GOOGLE_APPLICATION_CREDENTIALS={container_creds_path}']

        proxy_env: list[str] = []
        if self.config.litellmProxyConfigPath is not None:
            proxy_url = f'http://host-gateway:{self.config.litellmProxyPort}'
            proxy_env = ['-e', f'SINGLE_LITELLM_PROXY={proxy_url}']
        proxy_host_flags = ['--add-host', 'host-gateway:host-gateway']

        oracle_mount: list[str] = []
        if self.agent_config.oracleMode:
            oracle_mount = ['-v', f'{paths.oracle_path.absolute()}:/KBDr/oracle-files.txt:ro']

        return [
            'docker', 'run',
            '--rm',
            # '--network', 'none',
            '--name', container_name,
            *proxy_host_flags,
            '-e', f'KENV_KGYM_ENDPOINT={self.config.kGymEndpoint}',
            '-e', f'KENV_COMMIT_FROM={self.base_commit}',
            '-e', f'KENV_SYZBOT_BUG_ID={self.bug_id}',
            '-e', f'KENV_STATEFUL_EDIT={self.stateful_edit}',
            '-e', f'KENV_ORACLE_MODE={str(self.agent_config.oracleMode).lower()}',
            *proxy_env,
            *gcs_credentials_env,
            '-v', f'{paths.kbench_path.absolute()}:/KBDr/kBench.json',
            '-v', f'{self.agent_config_path.absolute()}:/KBDr/agent-config:ro',
            '-v', f'{model_config_path.absolute()}:/KBDr/model-config:ro',
            '-v', f'{paths.patch_path.absolute()}:/KBDr/output/patch.txt',
            '-v', f'{paths.traj_path.absolute()}:/KBDr/output/traj.json',
            '-v', f'{paths.log_path.absolute()}:/KBDr/output/log.txt',
            '-v', f'{paths.metadata_path.absolute()}:/KBDr/output/metadata.json',
            *oracle_mount,
            '-v', f'{(self.workspace_root / "shared" / "storageCfg.json").absolute()}:/KBDr/storageCfg.json:ro',
            *gcs_credentials_mount,
            f'kenv-{self.agent_config.agent}-{self.bug_id}-{docker_base_commit}:latest',
        ]

    def _parse_metadata(self, paths: '_WorkspacePaths') -> AgentResult:
        try:
            if not paths.metadata_path.exists():
                raise FileNotFoundError('metadata.json not found')

            metadata = json.loads(paths.metadata_path.read_text())

            required = ['dollarCost', 'timeCost', 'exitReason']
            for field in required:
                if field not in metadata:
                    raise ValueError(f'Missing required field: {field}')

            valid_reasons = ['normal', 'costLimitExceeded', 'timeLimitExceeded']
            if metadata['exitReason'] not in valid_reasons:
                raise ValueError(f"Invalid exitReason: {metadata['exitReason']}")

            raw_patch = paths.patch_path.read_text() if paths.patch_path.exists() else ''
            return AgentResult(
                status='success',
                systemMessage=f"Completed: {metadata['exitReason']}",
                dollarCost=float(metadata['dollarCost']),
                timeCost=int(metadata['timeCost']),
                exitReason=metadata['exitReason'],
                patch=filter_binary_files_from_patch(raw_patch),
                trajectory=paths.traj_path.read_bytes() if paths.traj_path.exists() else b'',
                log=paths.log_path.read_bytes() if paths.log_path.exists() else b'',
            )
        except Exception as e:
            logger.error(f'[{self.bug_id}] Metadata parsing failed: {e}')
            return AgentResult(
                status='error',
                systemMessage=f'Failed to parse metadata.json: {str(e)}',
            )

    async def _kill_container(self, proc, container_name: str) -> None:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await (await asyncio.subprocess.create_subprocess_exec(
                'docker', 'rm', '-f', container_name,
                stdin=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
            )).wait()
            await proc.wait()

    async def run_agent(self, timeout: int = 6 * 60 * 60) -> AgentResult:
        with tempfile.TemporaryDirectory(prefix=f'kenv-{self.bug_id}-') as temp_dir:
            paths = self._prepare_workspace(Path(temp_dir))
            container_name = f'kenv-{self.bug_id}-{md5(temp_dir.encode("utf-8")).hexdigest()[:6]}'

            async with ModelConfigManager.get_model_config(
                self._model_config_name, self._agent, self.workspace_root
            ) as model_config_path:
                cmd_or_error = self._build_docker_cmd(paths, model_config_path, container_name)
                if isinstance(cmd_or_error, AgentResult):
                    return cmd_or_error
                docker_cmd = cmd_or_error

                logger.info(f'[{self.bug_id}] Running agent {self.agent_config.agent}')
                logger.debug(f'[{self.bug_id}] Command: {" ".join(docker_cmd)}')

                proc = None
                try:
                    with open(paths.stdout_path, 'wb') as stdout_file, open(paths.stderr_path, 'wb') as stderr_file:
                        proc = await asyncio.create_subprocess_exec(
                            *docker_cmd,
                            stdin=asyncio.subprocess.DEVNULL,
                            stdout=stdout_file,
                            stderr=stderr_file,
                        )
                        async with asyncio.timeout(timeout):
                            exit_code = await proc.wait()

                    stdout_content = paths.stdout_path.read_text(errors='replace')
                    stderr_content = paths.stderr_path.read_text(errors='replace')
                    if stdout_content:
                        logger.info(f'[{self.bug_id}] Docker STDOUT:\n{stdout_content}')
                    if stderr_content:
                        logger.info(f'[{self.bug_id}] Docker STDERR:\n{stderr_content}')

                    if exit_code != 0:
                        error_msg = f'Docker container exited with code {exit_code}'
                        logger.error(f'[{self.bug_id}] {error_msg}')
                        return AgentResult(status='error', systemMessage=error_msg)

                    return self._parse_metadata(paths)

                except asyncio.TimeoutError:
                    await self._kill_container(proc, container_name)
                    return AgentResult(status='error', systemMessage='Timeout Error, killing the agent')
                except Exception:
                    await self._kill_container(proc, container_name)
                    return AgentResult(status='error', systemMessage=f'Python Exception:\n{format_exc()}')
