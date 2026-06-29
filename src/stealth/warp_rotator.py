from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

import httpx

logger = logging.getLogger(__name__)

_TRACE_URL = 'https://1.1.1.1/cdn-cgi/trace'
_DEFAULT_WARP_CLI = 'warp-cli'  # assumes warp-cli is on PATH; override with absolute path if needed


class WarpRotationError(Exception):
    """Raised when a WARP disconnect/connect cycle fails."""


class WarpRotator:
    """Rotates the outbound IP by cycling Cloudflare WARP via warp-cli.

    Only one rotation runs at a time — a class-level asyncio.Lock serializes
    concurrent calls from multiple collectors running in parallel.

    If warp-cli is not found or `enabled=False`, every call to `rotate()` is
    a silent no-op that returns False.  No exception is raised, so callers can
    unconditionally await rotate() without guarding.
    """

    _global_lock: ClassVar[asyncio.Lock | None] = None

    def __init__(
        self,
        warp_cli_path: str = _DEFAULT_WARP_CLI,
        connect_timeout_s: float = 15.0,
        post_disconnect_wait_s: float = 6.0,
        post_connect_wait_s: float = 3.0,
        enabled: bool = True,
    ) -> None:
        self.warp_cli_path = warp_cli_path
        self.connect_timeout_s = connect_timeout_s
        self.post_disconnect_wait_s = post_disconnect_wait_s  # WARP needs ~6s after disconnect to assign a new IP
        self.post_connect_wait_s = post_connect_wait_s
        self.enabled = enabled
        self._available: bool | None = None  # None = not yet checked

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        # Lock is created lazily inside the running event loop to avoid
        # "no running event loop" errors at import time and in test teardown.
        if cls._global_lock is None:
            cls._global_lock = asyncio.Lock()
        return cls._global_lock

    async def rotate(self) -> bool:
        """Rotate the IP via WARP.  Returns True on success, False otherwise.

        The global lock ensures only one rotation runs at a time even when
        multiple collectors call this concurrently.
        """
        if not self.enabled:
            return False
        if not await self._is_available():
            return False

        async with self._get_lock():
            ip_before = await self._get_current_ip()
            logger.info('[WarpRotator] Rotating IP — current: %s', ip_before or 'unknown')
            try:
                await self._run_warp_cmd('disconnect')
                await asyncio.sleep(self.post_disconnect_wait_s)
                await self._run_warp_cmd('connect')
                await asyncio.sleep(self.post_connect_wait_s)
                ip_after = await self._get_current_ip()
                logger.info('[WarpRotator] Rotation complete — new IP: %s', ip_after or 'unknown')
                return True
            except WarpRotationError as exc:
                logger.warning('[WarpRotator] Rotation failed: %s', exc)
                return False

    async def _is_available(self) -> bool:
        """Return True if warp-cli is reachable.  Result is cached after the first check."""
        if self._available is not None:
            return self._available

        try:
            proc = await asyncio.create_subprocess_exec(
                self.warp_cli_path,
                '--version',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            self._available = proc.returncode == 0
            if not self._available:
                logger.error(
                    '[WarpRotator] warp-cli --version exited %d. stdout=%s stderr=%s',
                    proc.returncode,
                    stdout.decode(errors='replace')[:200],
                    stderr.decode(errors='replace')[:200],
                )
        except FileNotFoundError:
            self._available = False
            logger.error('[WarpRotator] warp-cli not found at path: %r', self.warp_cli_path)
        except asyncio.TimeoutError:
            self._available = False
            logger.error('[WarpRotator] warp-cli --version timed out (5 s) — is warp-cli hanging?')
        except OSError as exc:
            self._available = False
            logger.error('[WarpRotator] OS error probing warp-cli: %s', exc)

        if self._available:
            logger.info('[WarpRotator] warp-cli found and responsive at: %r', self.warp_cli_path)
        return self._available

    async def _run_warp_cmd(self, command: str) -> None:
        """Run `warp-cli <command>`, raising WarpRotationError on failure or timeout."""
        logger.debug('[WarpRotator] Running: warp-cli %s', command)
        try:
            proc = await asyncio.create_subprocess_exec(
                self.warp_cli_path,
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.connect_timeout_s,
                )
            except asyncio.TimeoutError as exc:
                proc.kill()
                err = f'warp-cli {command} timed out after {self.connect_timeout_s}s'
                logger.error('[WarpRotator] %s', err)
                raise WarpRotationError(err) from exc

            stdout_str = stdout.decode(errors='replace').strip()
            stderr_str = stderr.decode(errors='replace').strip()

            if proc.returncode != 0:
                err = (
                    f'warp-cli {command} exited {proc.returncode}'
                    + (f' | stdout: {stdout_str[:200]}' if stdout_str else '')
                    + (f' | stderr: {stderr_str[:200]}' if stderr_str else '')
                )
                logger.error('[WarpRotator] %s', err)
                raise WarpRotationError(err)

            if stdout_str:
                logger.debug('[WarpRotator] warp-cli %s output: %s', command, stdout_str[:200])
        except FileNotFoundError as exc:
            self._available = False
            err = f'warp-cli not found at path: {self.warp_cli_path}'
            logger.error('[WarpRotator] %s', err)
            raise WarpRotationError(err) from exc

    async def _get_current_ip(self) -> str | None:
        """Fetch current public IP from https://1.1.1.1/cdn-cgi/trace."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(_TRACE_URL)
                for line in resp.text.splitlines():
                    if line.startswith('ip='):
                        return line.split('=', 1)[1].strip()
        except Exception:  # noqa: BLE001
            pass
        return None
