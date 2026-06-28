from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.stealth.warp_rotator import WarpRotationError, WarpRotator


@pytest.fixture(autouse=True)
def reset_global_lock():
    """Reset the class-level Lock between tests to avoid event-loop conflicts."""
    WarpRotator._global_lock = None
    yield
    WarpRotator._global_lock = None


# ---------------------------------------------------------------------------
# disabled / unavailable
# ---------------------------------------------------------------------------

async def test_rotate_disabled_returns_false():
    rotator = WarpRotator(enabled=False)
    result = await rotator.rotate()
    assert result is False


async def test_rotate_warp_not_found_returns_false(tmp_path):
    rotator = WarpRotator(warp_cli_path=str(tmp_path / 'nonexistent.exe'), enabled=True)
    result = await rotator.rotate()
    assert result is False
    assert rotator._available is False


# ---------------------------------------------------------------------------
# successful rotation
# ---------------------------------------------------------------------------

async def test_rotate_calls_disconnect_then_connect():
    rotator = WarpRotator(warp_cli_path='warp-cli', enabled=True)
    rotator._available = True  # skip file-existence check

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))

    with patch('asyncio.create_subprocess_exec', return_value=mock_proc) as mock_exec:
        with patch.object(rotator, '_get_current_ip', new=AsyncMock(return_value='1.2.3.4')):
            result = await rotator.rotate()

    assert result is True
    commands_called = [call.args[1] for call in mock_exec.call_args_list]
    assert commands_called == ['disconnect', 'connect']


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------

async def test_rotate_returns_false_on_nonzero_exit():
    rotator = WarpRotator(warp_cli_path='warp-cli', enabled=True)
    rotator._available = True

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b'', b'error msg'))

    with patch('asyncio.create_subprocess_exec', return_value=mock_proc):
        result = await rotator.rotate()

    assert result is False


async def test_run_warp_cmd_raises_on_timeout():
    rotator = WarpRotator(warp_cli_path='warp-cli', connect_timeout_s=0.01)
    rotator._available = True

    async def slow_communicate():
        await asyncio.sleep(10)
        return b'', b''

    mock_proc = MagicMock()
    mock_proc.communicate = slow_communicate
    mock_proc.kill = MagicMock()

    with patch('asyncio.create_subprocess_exec', return_value=mock_proc):
        with pytest.raises(WarpRotationError, match='timed out'):
            await rotator._run_warp_cmd('connect')


async def test_run_warp_cmd_raises_on_file_not_found():
    rotator = WarpRotator(warp_cli_path='/no/such/path/warp-cli')
    rotator._available = True

    with patch('asyncio.create_subprocess_exec', side_effect=FileNotFoundError):
        with pytest.raises(WarpRotationError, match='not found'):
            await rotator._run_warp_cmd('connect')

    assert rotator._available is False


# ---------------------------------------------------------------------------
# concurrency — global lock serialises rotations
# ---------------------------------------------------------------------------

async def test_concurrent_rotations_are_serialized():
    rotator = WarpRotator(warp_cli_path='warp-cli', enabled=True)
    rotator._available = True
    call_log: list[str] = []

    async def fake_run_cmd(cmd: str) -> None:
        call_log.append(f'start_{cmd}')
        await asyncio.sleep(0.05)
        call_log.append(f'end_{cmd}')

    with patch.object(rotator, '_run_warp_cmd', side_effect=fake_run_cmd):
        with patch.object(rotator, '_get_current_ip', new=AsyncMock(return_value=None)):
            await asyncio.gather(rotator.rotate(), rotator.rotate())

    # Verify no interleaving: find where the first rotation's last 'end_connect'
    # appears and confirm the second 'start_disconnect' comes after it.
    end_connect_positions = [i for i, e in enumerate(call_log) if e == 'end_connect']
    start_disconnect_positions = [i for i, e in enumerate(call_log) if e == 'start_disconnect']
    assert len(end_connect_positions) == 2
    assert len(start_disconnect_positions) == 2
    # First full cycle must complete before second starts
    assert end_connect_positions[0] < start_disconnect_positions[1]


# ---------------------------------------------------------------------------
# _is_available — caches result
# ---------------------------------------------------------------------------

async def test_is_available_caches_false():
    rotator = WarpRotator(warp_cli_path='/no/such/warp-cli', enabled=True)
    result1 = await rotator._is_available()
    result2 = await rotator._is_available()
    assert result1 is False
    assert result2 is False  # second call uses cached value


async def test_is_available_returns_true_when_probe_succeeds():
    rotator = WarpRotator(warp_cli_path='warp-cli', enabled=True)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'warp-cli 2.0.0', b''))

    with patch('asyncio.create_subprocess_exec', return_value=mock_proc):
        result = await rotator._is_available()

    assert result is True
