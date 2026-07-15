"""Tests for activity logging functionality.

These tests cover:
- Activity logging when enabled/disabled
- Fire-and-forget mode (without session)
- Transactional mode (with session)
- Exception handling (best-effort logging)
- Decorator functionality
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.core.activity_logging import (
    log_activity,
    log_activity_decorator,
)
from redact_api.models.activity_log import ActivityAction, ActivityLog


class TestLogActivityDisabled:
    """Test activity logging when disabled."""

    @pytest.mark.asyncio
    async def test_log_activity_disabled_returns_early(
        self,
        session: AsyncSession,
    ) -> None:
        """log_activity returns early when activity_logging_enabled is False."""
        resource_id = uuid4()

        # Count activities before
        result_before = await session.execute(select(ActivityLog))
        count_before = len(list(result_before.scalars().all()))

        # Mock settings to have activity_logging_enabled=False
        mock_settings = MagicMock()
        mock_settings.activity_logging_enabled = False

        with patch("redact_api.core.activity_logging.settings", mock_settings):
            # This should return early and not log anything
            await log_activity(
                action=ActivityAction.CREATE,
                resource_type="test_disabled",
                resource_id=resource_id,
                session=session,
            )
        await session.commit()

        # Count activities after - should be the same
        result_after = await session.execute(select(ActivityLog))
        count_after = len(list(result_after.scalars().all()))

        # No new activity should be logged when disabled
        assert count_after == count_before


class TestLogActivityTransactional:
    """Test transactional mode (with session)."""

    @pytest.mark.asyncio
    async def test_log_activity_with_session_adds_to_session(
        self,
        session: AsyncSession,
    ) -> None:
        """log_activity with session adds ActivityLog to caller's session."""
        resource_id = uuid4()

        await log_activity(
            action=ActivityAction.CREATE,
            resource_type="test_transactional",
            resource_id=resource_id,
            session=session,
        )
        await session.commit()

        # Verify activity was logged
        result = await session.execute(select(ActivityLog).where(ActivityLog.resource_id == resource_id))
        activity = result.scalar_one_or_none()

        assert activity is not None
        assert activity.action == ActivityAction.CREATE
        assert activity.resource_type == "test_transactional"
        assert activity.resource_id == resource_id

    @pytest.mark.asyncio
    async def test_log_activity_with_details(
        self,
        session: AsyncSession,
    ) -> None:
        """log_activity stores additional details as JSON."""
        resource_id = uuid4()
        details = {"key": "value", "count": 42}

        await log_activity(
            action=ActivityAction.UPDATE,
            resource_type="test_details",
            resource_id=resource_id,
            details=details,
            session=session,
        )
        await session.commit()

        result = await session.execute(select(ActivityLog).where(ActivityLog.resource_id == resource_id))
        activity = result.scalar_one_or_none()

        assert activity is not None
        assert activity.details == details


class TestLogActivityFireAndForget:
    """Test fire-and-forget mode (without session)."""

    @pytest.mark.asyncio
    async def test_log_activity_without_session_uses_internal_session(
        self,
    ) -> None:
        """log_activity without session creates and commits its own session.

        This test verifies the fire-and-forget code path is exercised by mocking
        the async_session_maker to confirm it's called when no session is provided.

        Note: We can't easily verify the database write in tests because the
        fire-and-forget mode uses a global session_maker that may point to a
        different database than the test session.
        """
        resource_id = uuid4()

        # Mock the session to verify fire-and-forget path is taken
        mock_session = AsyncMock()
        mock_session_maker = MagicMock()
        mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "redact_api.db.session.async_session_maker",
            mock_session_maker,
        ):
            # Log without passing session - fire-and-forget mode
            await log_activity(
                action=ActivityAction.DELETE,
                resource_type="test_fire_and_forget",
                resource_id=resource_id,
                # No session parameter
            )

        # Verify session was created and committed
        mock_session_maker.assert_called_once()
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()


class TestLogActivityExceptionHandling:
    """Test exception handling (best-effort logging)."""

    @pytest.mark.asyncio
    async def test_log_activity_suppresses_database_errors(
        self,
        session: AsyncSession,
    ) -> None:
        """log_activity catches database errors without propagating.

        This ensures logging failures don't interrupt the primary operation.
        """
        resource_id = uuid4()

        # Mock session.add to raise an exception
        with patch.object(session, "add", side_effect=Exception("Simulated DB error")):
            # This should NOT raise - errors are suppressed
            await log_activity(
                action=ActivityAction.CREATE,
                resource_type="test_error",
                resource_id=resource_id,
                session=session,
            )

        # Test passes if no exception was raised

    @pytest.mark.asyncio
    async def test_log_activity_fire_and_forget_suppresses_errors(self) -> None:
        """Fire-and-forget mode catches session errors without propagating."""
        resource_id = uuid4()

        # Mock async_session_maker to raise an exception
        mock_session = AsyncMock()
        mock_session.__aenter__.side_effect = Exception("Session creation failed")

        with patch(
            "redact_api.db.session.async_session_maker",
            return_value=mock_session,
        ):
            # This should NOT raise - errors are suppressed
            await log_activity(
                action=ActivityAction.DELETE,
                resource_type="test_ff_error",
                resource_id=resource_id,
                # No session - fire-and-forget mode
            )

        # Test passes if no exception was raised


class TestLogActivityDecorator:
    """Test the log_activity_decorator."""

    @pytest.mark.asyncio
    async def test_decorator_logs_activity_on_success(
        self,
        session: AsyncSession,
    ) -> None:
        """Decorator logs activity after successful endpoint execution."""
        resource_id = uuid4()

        @log_activity_decorator(ActivityAction.CREATE, "test_decorated")
        async def mock_endpoint(session: AsyncSession) -> dict:  # noqa: ARG001
            return {"id": resource_id}

        result = await mock_endpoint(session=session)
        await session.commit()

        assert result["id"] == resource_id

        # Verify activity was logged
        result_db = await session.execute(select(ActivityLog).where(ActivityLog.resource_id == resource_id))
        activity = result_db.scalar_one_or_none()

        assert activity is not None
        assert activity.action == ActivityAction.CREATE
        assert activity.resource_type == "test_decorated"

    @pytest.mark.asyncio
    async def test_decorator_extracts_id_from_dict_result(
        self,
        session: AsyncSession,
    ) -> None:
        """Decorator extracts resource_id from dict response with 'id' key."""
        resource_id = uuid4()

        @log_activity_decorator(ActivityAction.READ, "test_dict")
        async def mock_endpoint(session: AsyncSession) -> dict:  # noqa: ARG001
            return {"id": resource_id, "name": "test"}

        await mock_endpoint(session=session)
        await session.commit()

        result = await session.execute(select(ActivityLog).where(ActivityLog.resource_id == resource_id))
        activity = result.scalar_one_or_none()

        assert activity is not None
        assert activity.resource_id == resource_id

    @pytest.mark.asyncio
    async def test_decorator_extracts_id_from_path_param(
        self,
        session: AsyncSession,
    ) -> None:
        """Decorator extracts resource_id from path parameter for DELETE endpoints."""
        resource_id = uuid4()

        @log_activity_decorator(ActivityAction.DELETE, "test_path_param", resource_id_param_name="item_id")
        async def delete_endpoint(item_id: UUID, session: AsyncSession) -> None:
            # DELETE returns None, no response body with id
            pass

        await delete_endpoint(item_id=resource_id, session=session)
        await session.commit()

        result = await session.execute(select(ActivityLog).where(ActivityLog.resource_id == resource_id))
        activity = result.scalar_one_or_none()

        assert activity is not None
        assert activity.resource_id == resource_id
        assert activity.action == ActivityAction.DELETE

    @pytest.mark.asyncio
    async def test_decorator_without_session_does_not_log(
        self,
        session: AsyncSession,
    ) -> None:
        """Decorator doesn't log if session is not in kwargs."""
        resource_id = uuid4()

        @log_activity_decorator(ActivityAction.CREATE, "test_no_session")
        async def endpoint_without_session() -> dict:
            return {"id": resource_id}

        await endpoint_without_session()

        # Verify NO activity was logged (session was None in decorator)
        result = await session.execute(select(ActivityLog).where(ActivityLog.resource_id == resource_id))
        activity = result.scalar_one_or_none()

        # No activity logged because session was not passed
        assert activity is None
