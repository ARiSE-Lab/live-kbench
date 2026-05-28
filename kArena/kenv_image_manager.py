"""Kenv Image Manager: Docker image management for kenv containers.

This module provides shared functionality for managing Docker images used by
kenv-based agent runs and patch analysis.
"""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from kArena.models import kArenaConfig

logger = logging.getLogger(__name__)


async def _run_docker(
    *cmd: str,
    capture: bool = False,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    """Run a docker command. Returns (exit_code, stdout, stderr).

    When capture=False, output is discarded (no deadlock risk, no memory cost).
    When capture=True, uses communicate() to avoid pipe-buffer deadlock.
    """
    if capture:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        out_b, err_b = await proc.communicate()
        return proc.returncode, out_b.decode(errors='replace'), err_b.decode(errors='replace')
    else:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=cwd,
        )
        await proc.wait()
        return proc.returncode, '', ''


def get_docker_base_commit(base_commit: Literal['parentCommit', 'crashCommit']) -> str:
    """Convert baseCommit to Docker image tag format.

    Args:
        base_commit: 'parentCommit' or 'crashCommit'

    Returns:
        Docker tag format: 'parent-commit' or 'crash-commit'
    """
    return f'{base_commit[:-len("Commit")]}-commit'


class KenvImageManager:
    """Manages Docker images for kenv containers.

    Handles pulling, building, and cleaning up Docker images for:
    - kenv-base images (pulled from remote registry)
    - kenv images (built from kenv-base)
    - Agent-specific kenv images (built from kenv)
    """

    def __init__(
        self,
        config: kArenaConfig,
        base_commit: Literal['parentCommit', 'crashCommit']
    ):
        """Initialize KenvImageManager.

        Args:
            config: kArena configuration with workspace root and docker prefix
            base_commit: 'parentCommit' or 'crashCommit'
        """
        self.config = config
        self.base_commit = base_commit
        self.docker_base_commit = get_docker_base_commit(base_commit)
        self.workspace_root = Path(config.workspaceRoot)

    def get_kenv_base_image_name(self, bug_id: str) -> str:
        """Get the local kenv-base image name."""
        return f'kenv-base-{bug_id}-{self.docker_base_commit}:latest'

    def get_remote_kenv_base_image_name(self, bug_id: str) -> str:
        """Get the remote kenv-base image name."""
        return f'{self.config.dockerPrefix}/kenv-base-{bug_id}-{self.docker_base_commit}:latest'

    def get_kenv_image_name(self, bug_id: str) -> str:
        """Get the kenv image name."""
        return f'kenv-{bug_id}-{self.docker_base_commit}:latest'

    def get_agent_image_name(self, bug_id: str, agent: str) -> str:
        """Get the agent-specific kenv image name."""
        return f'kenv-{agent}-{bug_id}-{self.docker_base_commit}:latest'

    async def check_image_exists(self, image_name: str) -> bool:
        """Check if a Docker image exists locally.

        Args:
            image_name: Full image name with tag

        Returns:
            True if image exists locally
        """
        code, _, _ = await _run_docker('docker', 'image', 'inspect', image_name)
        return code == 0

    async def pull_kenv_base_image(self, bug_id: str, max_retries: int = 3) -> None:
        """Pull kenv-base image from remote registry with retry mechanism.

        Args:
            bug_id: Bug ID
            max_retries: Maximum number of retry attempts

        Raises:
            RuntimeError: If pull fails after all retries
        """
        remote_image = self.get_remote_kenv_base_image_name(bug_id)
        local_image = self.get_kenv_base_image_name(bug_id)

        for attempt in range(max_retries):
            logger.info(f'[{bug_id}] Pulling {remote_image} (attempt {attempt + 1}/{max_retries})')

            code, _, _ = await _run_docker('docker', 'pull', remote_image)

            if code == 0:
                code, _, _ = await _run_docker('docker', 'tag', remote_image, local_image)
                if code == 0:
                    logger.info(f'[{bug_id}] Successfully pulled and tagged {local_image}')
                    return
                else:
                    logger.error(f'[{bug_id}] Failed to tag {remote_image} as {local_image}')
                    raise RuntimeError('Docker tag failed')

            logger.warning(f'[{bug_id}] Pull attempt {attempt + 1} failed, retrying...')
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

        raise RuntimeError(f'Failed to pull {remote_image} after {max_retries} attempts')

    async def build_kenv_image(self, bug_id: str) -> None:
        """Build kenv image from kenv-base.

        Args:
            bug_id: Bug ID

        Raises:
            RuntimeError: If build fails
        """
        base_image = self.get_kenv_base_image_name(bug_id)
        kenv_image = self.get_kenv_image_name(bug_id)

        logger.info(f'[{bug_id}] Building {kenv_image} from {base_image}')

        code, _, stderr = await _run_docker(
            'docker', 'build',
            '-f', 'docker/kenv.Dockerfile',
            '--build-arg', f'KENV_BASE_IMAGE={base_image}',
            '-t', kenv_image, '.',
            capture=True, cwd=str(self.workspace_root.parent),
        )
        if code != 0:
            logger.error(f'[{bug_id}] Failed to build {kenv_image}')
            raise RuntimeError(f'Docker build failed for {kenv_image}: {stderr[-800:]}')

        logger.info(f'[{bug_id}] Successfully built {kenv_image}')

    async def build_agent_image(self, bug_id: str, agent: str) -> None:
        """Build agent-specific kenv image.

        Args:
            bug_id: Bug ID
            agent: Agent name ('swe-agent', 'mini-swe-agent', 'openhands')

        Raises:
            RuntimeError: If build fails
        """
        kenv_image = self.get_kenv_image_name(bug_id)
        agent_image = self.get_agent_image_name(bug_id, agent)

        logger.info(f'[{bug_id}] Building {agent_image} from {kenv_image}')

        code, _, stderr = await _run_docker(
            'docker', 'build',
            '-f', f'docker/kenv-{agent}.Dockerfile',
            '--build-arg', f'KENV_IMAGE={kenv_image}',
            '-t', agent_image, '.',
            capture=True, cwd=str(self.workspace_root.parent),
        )
        if code != 0:
            logger.error(f'[{bug_id}] Failed to build {agent_image}')
            raise RuntimeError(f'Docker build failed for {agent_image}: {stderr[-800:]}')

        logger.info(f'[{bug_id}] Successfully built {agent_image}')

    async def ensure_kenv_image(self, bug_id: str) -> None:
        """Ensure kenv Docker image exists, pulling and building if necessary.

        Args:
            bug_id: Bug ID

        Raises:
            RuntimeError: If pull or build fails
        """
        kenv_image = self.get_kenv_image_name(bug_id)

        if await self.check_image_exists(kenv_image):
            logger.info(f'[{bug_id}] kenv image already exists locally: {kenv_image}')
            return

        base_image = self.get_kenv_base_image_name(bug_id)
        if not await self.check_image_exists(base_image):
            await self.pull_kenv_base_image(bug_id)
        else:
            logger.info(f'[{bug_id}] kenv-base exists locally; skipping pull: {base_image}')
        await self.build_kenv_image(bug_id)

    async def ensure_agent_image(self, bug_id: str, agent: str) -> None:
        """Ensure agent-specific kenv Docker image exists.

        Pulls kenv-base, builds kenv, and builds agent image if necessary.

        Args:
            bug_id: Bug ID
            agent: Agent name ('swe-agent', 'mini-swe-agent', 'openhands')

        Raises:
            RuntimeError: If any step fails
        """
        agent_image = self.get_agent_image_name(bug_id, agent)
        if await self.check_image_exists(agent_image):
            logger.info(f'[{bug_id}] Agent image already exists locally: {agent_image}')
            return
        await self.ensure_kenv_image(bug_id)
        await self.build_agent_image(bug_id, agent)

    async def cleanup_images(self, bug_id: str, agents: list[str] | None = None) -> None:
        """Cleanup Docker images for a bug.

        Args:
            bug_id: Bug ID
            agents: List of agent names to clean up (optional)
        """
        images_to_remove = []

        # Add kenv-base tags (both local and remote) if not preserving
        if not self.config.preserveKenvBase:
            images_to_remove.append(self.get_kenv_base_image_name(bug_id))
            images_to_remove.append(self.get_remote_kenv_base_image_name(bug_id))

        # Always remove intermediate kenv image
        images_to_remove.append(self.get_kenv_image_name(bug_id))

        # Add agent-specific images
        if agents:
            for agent in agents:
                images_to_remove.append(self.get_agent_image_name(bug_id, agent))

        if not images_to_remove:
            return

        logger.info(f'[{bug_id}] Cleaning up {len(images_to_remove)} Docker images')

        # Ignore errors — images might not exist or be in use
        await _run_docker('docker', 'rmi', *images_to_remove)
        await _run_docker('docker', 'image', 'prune', '-f')

        logger.info(f'[{bug_id}] Docker cleanup complete')
