"""Unit tests for the TaskIQ broker/result-backend settings (redact-api#8)."""

from __future__ import annotations

from redact_api.core.config import Settings


class TestTaskiqSettings:
    def test_defaults_present(self) -> None:
        settings = Settings()
        assert settings.rabbitmq_url == "amqp://guest:guest@localhost:5672/"
        assert settings.redis_url == "redis://localhost:6379/0"

    def test_env_override(self) -> None:
        settings = Settings(
            RABBITMQ_URL="amqp://user:pass@broker:5672/vhost",
            REDIS_URL="redis://cache:6379/2",
        )
        assert settings.rabbitmq_url == "amqp://user:pass@broker:5672/vhost"
        assert settings.redis_url == "redis://cache:6379/2"
