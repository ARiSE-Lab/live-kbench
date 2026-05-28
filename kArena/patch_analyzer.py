"""Agent Invoker: Docker orchestration for kenv-based agent runs.

This module provides high-level orchestration for running agents in kenv containers:
- Builds and manages Docker images for different agents
- Configures volumes, environment variables, and mounts
- Executes kenv-invoker.py inside containers
- Collects outputs and stores results in kArenaDB

Supported agents: SWE-agent, mini-swe-agent, OpenHands
"""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Literal
from pydantic import BaseModel
from traceback import format_exc
from hashlib import md5
from KBDr.kclient import SyzbotData
from pydantic_core import to_json, from_json
from kArena.models import kArenaConfig, Patch
from kArena.kenv_image_manager import get_docker_base_commit

class PatchAnalysis(BaseModel):
    patchContent: str

    status: Literal['success', 'error']
    systemMessage: str

    modifiedFiles: list[str] | None = None
    modifiedFunctions: list[str] | None = None
    numModifiedLines: int = -1


def patch_from_analysis(analysis: PatchAnalysis) -> Patch:
    """Construct a Patch model from a PatchAnalysis, normalising numModifiedLines to ≥ 0."""
    return Patch(
        patchId=0,
        patchContent=analysis.patchContent,
        status=analysis.status,
        systemMessage=analysis.systemMessage,
        modifiedFiles=analysis.modifiedFiles or [],
        modifiedFunctions=analysis.modifiedFunctions or [],
        numModifiedLines=max(0, analysis.numModifiedLines),
    )


class PatchAnalyzer:

    def __init__(
        self,
        config: kArenaConfig,
        bug: SyzbotData,
        base_commit: Literal['parentCommit', 'crashCommit'],
        patch: str
    ):
        self.config = config
        self.bug_id = bug.bugId
        self.bug = bug
        self.base_commit = base_commit
        self.patch = patch

    @staticmethod
    async def _kill_container(proc, container_name: str) -> None:
        if proc is not None and proc.returncode is None:
            proc.kill()
        await (await asyncio.create_subprocess_exec(
            'docker', 'rm', '-f', container_name,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )).wait()
        if proc is not None:
            await proc.wait()

    async def run_agent(
        self,
        timeout: int = 3600
    ) -> PatchAnalysis | None:
        if self.patch == '':
            return PatchAnalysis(
                patchContent=self.patch,
                status='success',
                systemMessage='Successfully analyzed the patch',
                modifiedFiles=[],
                modifiedFunctions=[],
                numModifiedLines=0
            )
        # Create temporary output directory
        with tempfile.TemporaryDirectory(prefix=f"kenv-{self.bug_id}-") as temp_dir:
            output_dir = Path(temp_dir) / "output"
            output_dir.mkdir(exist_ok=True)

            # stubs are good enough;
            kbench_path = output_dir / 'kBench.json'
            keval_path = output_dir / 'kEval.json'

            kbench_path.write_bytes(to_json({'dataset': [self.bug], 'kCache': {}}))
            keval_path.write_bytes(to_json(dict()))

            patch_path = output_dir / 'patch.txt'
            traj_path = output_dir / 'traj.json'
            log_path = output_dir / 'log.txt'

            patch_path.write_text(self.patch)
            traj_path.touch()
            log_path.touch()

            container_name = f'kenv-analyzer-{self.bug_id}-{md5(temp_dir.encode("utf-8")).hexdigest()[:6]}'
            docker_base_commit = get_docker_base_commit(self.base_commit)

            # Prepare Docker run command
            docker_cmd = [
                'docker', 'run',
                '--rm',
                '--name', container_name,
                # Environment variables
                '-e', f'KENV_KGYM_ENDPOINT={self.config.kGymEndpoint}',
                '-e', f'KENV_COMMIT_FROM={self.base_commit}',
                '-e', f'KENV_SYZBOT_BUG_ID={self.bug_id}',
                '-e', f'KENV_STATEFUL_EDIT=false',
                # Volume mounts
                '-v', f'{kbench_path.absolute()}:/KBDr/kBench.json:ro',
                '-v', f'{output_dir.absolute()}:/KBDr/output',
                '-v', f'{keval_path.absolute()}:/KBDr/kEval.json:ro',
                '-v', f'{(self.config.workspaceRoot / "shared" / "storageCfg.json").absolute()}:/KBDr/storageCfg.json:ro',
                f'kenv-{self.bug_id}-{docker_base_commit}:latest'
            ]

            print(f"Running patch analyzer for bug {self.bug_id}")
            print(f"Command: {' '.join(docker_cmd)}")

            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    *docker_cmd,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )

                async with asyncio.timeout(timeout):
                    exit_code = await proc.wait()
                assert exit_code == 0

                return PatchAnalysis(
                    patchContent=self.patch,
                    status='success',
                    systemMessage='Successfully analyzed the patch',
                    **json.loads(traj_path.read_text())
                )
            except asyncio.TimeoutError:
                await self._kill_container(proc, container_name)
                return PatchAnalysis(
                    patchContent=self.patch,
                    status='error',
                    systemMessage='Timeout Error, killing the analyzer'
                )
            except Exception:
                await self._kill_container(proc, container_name)
                return PatchAnalysis(
                    patchContent=self.patch,
                    status='error',
                    systemMessage=f'Python Exception:\n{format_exc()}'
                )
