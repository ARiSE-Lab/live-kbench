"""Kenv base image builder: docker build/tag/push/rmi for kenv-base layers.

Produces the ``kenv-base-{bugId}-{parent|crash}-commit:latest`` image from
``docker/kenv-base.Dockerfile``. Separated from :class:`DataPipeline` so the
subprocess shell can be stubbed in tests (pass ``subprocess_factory``).

Image name helpers are shared with :class:`kArena.kenv_image_manager.KenvImageManager`;
``DataPipeline`` passes the same local/remote names into the kenv_base_image DB
row so downstream code can find the built image.
"""

import asyncio
import logging
from pathlib import Path

from kArena.models import kArenaConfig, kEnvBaseImage

logger = logging.getLogger(__name__)


class KenvBaseBuildError(RuntimeError):
    """Raised when ``docker build``, ``docker push``, or ``docker rmi`` fails.

    The message contains the failing command's stderr so callers can persist
    it to ``kenv_base_image.systemMessage``.
    """


class KenvBaseBuilder:
    """Owns the docker subprocess invocations for kenv-base images.

    Callers (typically :class:`DataPipeline.populate_kenv_base_builds`) are
    responsible for DB state transitions — this class *only* runs commands.
    """

    def __init__(
        self,
        config: kArenaConfig,
        *,
        subprocess_factory=asyncio.create_subprocess_exec,
        repo_root: Path | None = None,
    ):
        self.config = config
        self._subprocess_factory = subprocess_factory
        # Docker build must run from the repo root so the `docker/` path
        # resolves and the mirror bind-mount lives under the build context.
        self._repo_root = Path(repo_root) if repo_root is not None else Path(config.workspaceRoot).parent

    async def build(self, row: kEnvBaseImage) -> None:
        """Run ``docker build`` for a kenv-base image.

        BuildKit is required for the ``--mount=type=bind`` in the Dockerfile;
        we pass ``DOCKER_BUILDKIT=1`` in the environment.
        """
        logger.info(f'[{row.bugId}] building {row.localImageName} @ {row.commitId[:10]}')
        mirror_rel = self._mirror_rel_to_build_context(row.mirrorPath)
        code, _, stderr = await self._run(
            'docker', 'build',
            '-f', 'docker/kenv-base.Dockerfile',
            '--build-arg', f'GIT_URL={row.gitUrl}',
            '--build-arg', f'MIRROR_PATH={mirror_rel}',
            '--build-arg', f'COMMIT_ID={row.commitId}',
            '--build-arg', f'SYZBOT_BUG_ID={row.bugId}',
            '--build-arg', f'BASE_COMMIT={row.baseCommit}',
            '-t', row.localImageName,
            '.',
            env={'DOCKER_BUILDKIT': '1'},
            cwd=str(self._repo_root),
        )
        if code != 0:
            raise KenvBaseBuildError(f'docker build failed (exit {code}): {stderr[-800:]}')

    async def push(self, row: kEnvBaseImage) -> None:
        """Tag the built image with its remote name and push it."""
        logger.info(f'[{row.bugId}] tagging+pushing {row.remoteImageName}')
        code, _, stderr = await self._run(
            'docker', 'tag', row.localImageName, row.remoteImageName
        )
        if code != 0:
            raise KenvBaseBuildError(f'docker tag failed (exit {code}): {stderr[-400:]}')

        code, _, stderr = await self._run('docker', 'push', row.remoteImageName)
        if code != 0:
            raise KenvBaseBuildError(f'docker push failed (exit {code}): {stderr[-800:]}')

    async def remove_local(self, *image_names: str) -> None:
        """Best-effort ``docker rmi`` — ignores failures (image may be in use)."""
        if not image_names:
            return
        code, _, stderr = await self._run('docker', 'rmi', *image_names)
        if code != 0:
            logger.debug(f'docker rmi returned {code} (ignored): {stderr[-200:]}')

    def _mirror_rel_to_build_context(self, mirror_path: str) -> str:
        """Docker build needs MIRROR_PATH relative to the build context
        (``self._repo_root``). Absolute paths under the repo root get
        rebased; paths that are already relative are returned unchanged.
        """
        p = Path(mirror_path)
        if p.is_absolute():
            try:
                return str(p.relative_to(self._repo_root))
            except ValueError:
                # Caller passed an absolute path outside the build context.
                # Docker will reject this at build time — surface as-is so the
                # failure message points at the real problem.
                return str(p)
        return mirror_path

    async def _run(
        self,
        *cmd: str,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> tuple[int, str, str]:
        """Run a subprocess, capturing stdout+stderr. Returns (code, out, err)."""
        import os

        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        proc = await self._subprocess_factory(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
            cwd=cwd,
        )
        stdout_b, stderr_b = await proc.communicate()
        return (
            proc.returncode if proc.returncode is not None else -1,
            stdout_b.decode(errors='replace') if stdout_b else '',
            stderr_b.decode(errors='replace') if stderr_b else '',
        )
