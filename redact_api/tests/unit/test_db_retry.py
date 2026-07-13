"""Tests for database retry decorators.

Tests cover:
- Retry behavior on OperationalError
- No retry on non-database exceptions
- Custom retry configuration
- Logging of retry attempts
- Both sync and async function support
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError
from tenacity import RetryCallState

from redact_api.db.retry import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_WAIT,
    DEFAULT_MIN_WAIT,
    DEFAULT_WAIT_MULTIPLIER,
    _log_retry_attempt,
    create_db_retry,
    db_retry,
)

# Test error messages as constants
_DB_CONNECTION_ERROR = "connection failed"
_DB_FAIL_ERROR = "fail"
_DB_TEST_ERROR = "test"


def _create_operational_error(msg: str = _DB_FAIL_ERROR) -> OperationalError:
    """Create an OperationalError for testing."""
    return OperationalError(None, None, Exception(msg))


class TestDbRetryDecorator:
    """Tests for the default db_retry decorator."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt_no_retry(self) -> None:
        """Function succeeds on first call - no retry needed."""
        call_count = 0

        @db_retry
        async def succeeds_immediately() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = await succeeds_immediately()

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_operational_error(self) -> None:
        """Function retries when OperationalError raised."""
        call_count = 0

        @db_retry
        async def fails_then_succeeds() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise _create_operational_error(_DB_CONNECTION_ERROR)
            return "success"

        result = await fails_then_succeeds()

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self) -> None:
        """Function raises after max retry attempts exhausted."""

        @db_retry
        async def always_fails() -> str:
            raise _create_operational_error(_DB_CONNECTION_ERROR)

        with pytest.raises(OperationalError):
            await always_fails()

    @pytest.mark.asyncio
    async def test_does_not_retry_on_other_exceptions(self) -> None:
        """Non-OperationalError exceptions are not retried."""
        call_count = 0

        @db_retry
        async def raises_value_error() -> str:
            nonlocal call_count
            call_count += 1
            msg = "not a db error"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="not a db error"):
            await raises_value_error()

        assert call_count == 1  # No retry


class TestCreateDbRetry:
    """Tests for the create_db_retry factory function."""

    @pytest.mark.asyncio
    async def test_custom_max_attempts(self) -> None:
        """Custom max_attempts is respected."""
        call_count = 0
        custom_retry = create_db_retry(max_attempts=5)

        @custom_retry
        async def fails_four_times() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 5:
                raise _create_operational_error()
            return "success"

        result = await fails_four_times()

        assert result == "success"
        assert call_count == 5

    @pytest.mark.asyncio
    async def test_custom_max_attempts_exhausted(self) -> None:
        """Fails after custom max_attempts is exhausted."""
        call_count = 0
        custom_retry = create_db_retry(max_attempts=2)

        @custom_retry
        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise _create_operational_error()

        with pytest.raises(OperationalError):
            await always_fails()

        assert call_count == 2

    def test_default_values(self) -> None:
        """Verify default constants are used."""
        assert DEFAULT_MAX_ATTEMPTS == 3
        assert DEFAULT_WAIT_MULTIPLIER == 1
        assert DEFAULT_MIN_WAIT == 1
        assert DEFAULT_MAX_WAIT == 10


class TestLogRetryAttempt:
    """Tests for the _log_retry_attempt logging function."""

    def test_logs_warning_with_context(self) -> None:
        """_log_retry_attempt logs warning with attempt info."""
        mock_retry_state = MagicMock(spec=RetryCallState)
        mock_retry_state.attempt_number = 2
        mock_retry_state.next_action = MagicMock()
        mock_retry_state.next_action.sleep = 2.0
        mock_retry_state.outcome = MagicMock()
        mock_retry_state.outcome.exception.return_value = _create_operational_error(_DB_TEST_ERROR)

        with (
            patch("redact_api.db.retry.LOGGER") as mock_logger,
            patch("redact_api.db.retry.get_logging_context") as mock_context,
        ):
            mock_context.return_value = {"request_id": "test-123"}

            _log_retry_attempt(mock_retry_state)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "db_operation_retry"
            assert "attempt" in call_args[1]["extra"]
            assert call_args[1]["extra"]["attempt"] == 2

    def test_logs_with_wait_seconds(self) -> None:
        """_log_retry_attempt includes wait_seconds in log."""
        mock_retry_state = MagicMock(spec=RetryCallState)
        mock_retry_state.attempt_number = 1
        mock_retry_state.next_action = MagicMock()
        mock_retry_state.next_action.sleep = 5.0
        mock_retry_state.outcome = MagicMock()
        mock_retry_state.outcome.exception.return_value = _create_operational_error(_DB_TEST_ERROR)

        with (
            patch("redact_api.db.retry.LOGGER") as mock_logger,
            patch("redact_api.db.retry.get_logging_context") as mock_context,
        ):
            mock_context.return_value = {}

            _log_retry_attempt(mock_retry_state)

            call_args = mock_logger.warning.call_args
            assert call_args[1]["extra"]["wait_seconds"] == 5.0

    def test_handles_no_next_action(self) -> None:
        """_log_retry_attempt handles missing next_action."""
        mock_retry_state = MagicMock(spec=RetryCallState)
        mock_retry_state.attempt_number = 1
        mock_retry_state.next_action = None
        mock_retry_state.outcome = MagicMock()
        mock_retry_state.outcome.exception.return_value = _create_operational_error(_DB_TEST_ERROR)

        with (
            patch("redact_api.db.retry.LOGGER") as mock_logger,
            patch("redact_api.db.retry.get_logging_context") as mock_context,
        ):
            mock_context.return_value = {}

            # Should not raise
            _log_retry_attempt(mock_retry_state)

            # Verify wait_seconds is 0 when no next_action
            call_args = mock_logger.warning.call_args
            assert call_args[1]["extra"]["wait_seconds"] == 0

    def test_handles_no_outcome(self) -> None:
        """_log_retry_attempt handles missing outcome."""
        mock_retry_state = MagicMock(spec=RetryCallState)
        mock_retry_state.attempt_number = 1
        mock_retry_state.next_action = MagicMock()
        mock_retry_state.next_action.sleep = 1.0
        mock_retry_state.outcome = None

        with (
            patch("redact_api.db.retry.LOGGER") as mock_logger,
            patch("redact_api.db.retry.get_logging_context") as mock_context,
        ):
            mock_context.return_value = {}

            # Should not raise
            _log_retry_attempt(mock_retry_state)

            # Verify exception_type is "unknown" when no outcome
            call_args = mock_logger.warning.call_args
            assert call_args[1]["extra"]["exception_type"] == "unknown"

    def test_logs_exception_type(self) -> None:
        """_log_retry_attempt includes exception type in log."""
        mock_retry_state = MagicMock(spec=RetryCallState)
        mock_retry_state.attempt_number = 1
        mock_retry_state.next_action = MagicMock()
        mock_retry_state.next_action.sleep = 1.0
        mock_retry_state.outcome = MagicMock()
        mock_retry_state.outcome.exception.return_value = _create_operational_error(_DB_TEST_ERROR)

        with (
            patch("redact_api.db.retry.LOGGER") as mock_logger,
            patch("redact_api.db.retry.get_logging_context") as mock_context,
        ):
            mock_context.return_value = {}

            _log_retry_attempt(mock_retry_state)

            call_args = mock_logger.warning.call_args
            assert call_args[1]["extra"]["exception_type"] == "OperationalError"


class TestSyncFunctionRetry:
    """Tests for db_retry with synchronous functions."""

    def test_sync_function_with_db_retry(self) -> None:
        """db_retry works with sync functions too."""
        call_count = 0

        @db_retry
        def sync_fails_then_succeeds() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise _create_operational_error()
            return "success"

        result = sync_fails_then_succeeds()

        assert result == "success"
        assert call_count == 2

    def test_sync_function_raises_after_max_attempts(self) -> None:
        """Sync function raises after max retry attempts exhausted."""

        @db_retry
        def always_fails() -> str:
            raise _create_operational_error(_DB_CONNECTION_ERROR)

        with pytest.raises(OperationalError):
            always_fails()

    def test_sync_function_no_retry_on_value_error(self) -> None:
        """Sync function does not retry on ValueError."""
        call_count = 0

        @db_retry
        def raises_value_error() -> str:
            nonlocal call_count
            call_count += 1
            msg = "not a db error"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="not a db error"):
            raises_value_error()

        assert call_count == 1
