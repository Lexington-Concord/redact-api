"""Mock fixtures and utilities for external service testing.

This package provides fixtures and mocks for testing against external services
without requiring live credentials or active deployments. Useful for:

- CI/CD pipelines without external service access
- Development without full infrastructure
- Testing error scenarios difficult with live services
- Isolated unit testing of service integration code

Available mocks:
- Auth providers: Ory, Auth0, Keycloak, Cognito
- Cloud storage: Azure, AWS S3, Google Cloud Storage
- Email services, SMS services, etc.

Usage:
    from redact_api.tests.mocks import mock_ory_provider, mock_s3_storage

    def test_user_with_auth(mock_ory_provider):
        # Test code here
        pass
"""

__all__ = [
    "mock_auth0_provider",
    "mock_azure_storage",
    "mock_cognito_provider",
    "mock_gcs_storage",
    "mock_keycloak_provider",
    "mock_ory_provider",
    "mock_s3_storage",
]
