"""Tests for db/session.py - session lifecycle and init_db."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from redact_api.db.session import get_session, init_db


class TestGetSession:
    """Tests for get_session dependency."""

    @pytest.mark.asyncio
    async def test_session_rollback_on_exception(self) -> None:
        """Should rollback session when exception occurs during request."""
        mock_session = AsyncMock()
        mock_session.rollback = AsyncMock()

        mock_session_maker = MagicMock()
        mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("redact_api.db.session.async_session_maker", mock_session_maker):
            gen = get_session()
            session = await gen.__anext__()
            assert session is mock_session

            # Simulate exception during request handling
            with pytest.raises(ValueError, match="test error"):
                await gen.athrow(ValueError("test error"))

            # Session should have been rolled back
            mock_session.rollback.assert_called_once()


class TestInitDb:
    """Tests for init_db function."""

    @pytest.mark.asyncio
    async def test_init_db_with_provided_engine(self) -> None:
        """Should use provided engine when passed."""
        mock_connection = AsyncMock()
        mock_connection.run_sync = AsyncMock()

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        await init_db(db_engine=mock_engine)

        mock_engine.begin.assert_called_once()
        mock_connection.run_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_init_db_uses_global_engine_when_none_provided(self) -> None:
        """Should use global engine when no engine provided."""
        mock_connection = AsyncMock()
        mock_connection.run_sync = AsyncMock()

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        with patch("redact_api.db.session.engine", mock_engine):
            await init_db()

        mock_engine.begin.assert_called_once()
        mock_connection.run_sync.assert_called_once()
