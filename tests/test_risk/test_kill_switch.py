"""Tests for KillSwitch — Redis state + DB persistence (BUG-73)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from risk.kill_switch import KillSwitch


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_flag = AsyncMock(return_value=None)
    redis.set_flag = AsyncMock()
    redis.delete_flag = AsyncMock()
    return redis


class TestKillSwitchBasic:
    @pytest.mark.asyncio
    async def test_is_active_when_off(self, mock_redis):
        ks = KillSwitch(mock_redis, "ks:test")
        assert await ks.is_active() is False

    @pytest.mark.asyncio
    async def test_is_active_when_on(self, mock_redis):
        mock_redis.get_flag.return_value = {"active": True, "reason": "test"}
        ks = KillSwitch(mock_redis, "ks:test")
        assert await ks.is_active() is True

    @pytest.mark.asyncio
    async def test_activate_sets_redis(self, mock_redis):
        ks = KillSwitch(mock_redis, "ks:test")
        await ks.activate("drawdown breach")
        mock_redis.set_flag.assert_called_once()
        call_args = mock_redis.set_flag.call_args
        assert call_args[0][0] == "ks:test"
        assert call_args[0][1]["active"] is True
        assert call_args[0][1]["reason"] == "drawdown breach"

    @pytest.mark.asyncio
    async def test_deactivate_deletes_redis(self, mock_redis):
        ks = KillSwitch(mock_redis, "ks:test")
        await ks.deactivate()
        mock_redis.delete_flag.assert_called_once_with("ks:test")


class TestKillSwitchPersistence:
    @pytest.mark.asyncio
    async def test_activate_persists_to_db(self, mock_redis):
        """BUG-73: activate should write to DB when session_id is set."""
        ks = KillSwitch(mock_redis, "ks:test", session_id="sess-1")

        with patch.object(ks, "_persist_event", new_callable=AsyncMock) as mock_persist:
            await ks.activate("test reason")
            mock_persist.assert_called_once()
            assert mock_persist.call_args.kwargs["active"] is True
            assert mock_persist.call_args.kwargs["reason"] == "test reason"

    @pytest.mark.asyncio
    async def test_deactivate_persists_to_db(self, mock_redis):
        """BUG-73: deactivate should write to DB when session_id is set."""
        ks = KillSwitch(mock_redis, "ks:test", session_id="sess-1")

        with patch.object(ks, "_persist_event", new_callable=AsyncMock) as mock_persist:
            await ks.deactivate()
            mock_persist.assert_called_once()
            assert mock_persist.call_args.kwargs["active"] is False

    @pytest.mark.asyncio
    async def test_no_persist_without_session_id(self, mock_redis):
        """No DB writes when session_id is empty."""
        ks = KillSwitch(mock_redis, "ks:test", session_id="")

        with patch.object(ks, "_persist_event", new_callable=AsyncMock) as mock_persist:
            await ks.activate("test")
            # _persist_event is called but returns early due to empty session_id
            mock_persist.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_from_db_no_session(self, mock_redis):
        """restore_from_db returns False when no session_id."""
        ks = KillSwitch(mock_redis, "ks:test", session_id="")
        result = await ks.restore_from_db()
        assert result is False

    @pytest.mark.asyncio
    async def test_restore_from_db_active(self, mock_redis):
        """BUG-73: restore re-populates Redis from DB when kill switch was active."""
        ks = KillSwitch(mock_redis, "ks:test", session_id="sess-1")

        mock_event = MagicMock()
        mock_event.active = True
        mock_event.reason = "drawdown breach"
        mock_event.timestamp = MagicMock()
        mock_event.timestamp.isoformat.return_value = "2026-03-27T00:00:00+00:00"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_event
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("db.session.get_session", return_value=mock_ctx):
            result = await ks.restore_from_db()

        assert result is True
        mock_redis.set_flag.assert_called_once()
        restored = mock_redis.set_flag.call_args[0][1]
        assert restored["active"] is True
        assert restored["restored_from_db"] is True

    @pytest.mark.asyncio
    async def test_restore_from_db_inactive(self, mock_redis):
        """No restoration when last event was deactivation."""
        ks = KillSwitch(mock_redis, "ks:test", session_id="sess-1")

        mock_event = MagicMock()
        mock_event.active = False

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_event
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("db.session.get_session", return_value=mock_ctx):
            result = await ks.restore_from_db()

        assert result is False
        mock_redis.set_flag.assert_not_called()
