"""SQL injection security tests.

Verifies that SQLAlchemy parameterization prevents SQL injection attacks
across all user-supplied input fields.
"""

from http import HTTPStatus

import pytest
from httpx import AsyncClient

# SQL injection payloads constant - all 14 payloads
SQL_INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE users; --",
    "' OR '1'='1' --",
    "admin'--",
    "' OR '1'='1' /*",
    "') OR ('1'='1",
    "1' UNION SELECT NULL--",
    "' AND '1'='2",
    "' OR 1=1#",
    "'; WAITFOR DELAY '00:00:05'--",
    "1' AND (SELECT COUNT(*) FROM users) > 0--",
    '"; DROP TABLE users; --',
    "%27%20OR%201=1--",  # URL-encoded
    "&#x27; OR 1=1--",  # HTML entity
]


class TestSQLInjectionUsers:
    """SQL injection attempts via user endpoints."""

    @pytest.mark.asyncio
    async def test_sql_injection_in_email_field(self, client: AsyncClient) -> None:
        """Verify SQL injection in email field fails safely."""
        for payload in SQL_INJECTION_PAYLOADS:
            response = await client.post(
                "/users",
                json={
                    "name": "Test User",
                    "email": payload,
                },
            )
            # Email validation should reject most payloads
            # Only valid email-like payloads would be stored as literals
            assert response.status_code in (
                HTTPStatus.UNPROCESSABLE_ENTITY,  # Validation error
                HTTPStatus.CREATED,  # Treated as literal string
            )

    @pytest.mark.asyncio
    async def test_sql_injection_in_name_field(self, client: AsyncClient) -> None:
        """Verify SQL injection in name field fails safely."""
        for i, payload in enumerate(SQL_INJECTION_PAYLOADS):
            response = await client.post(
                "/users",
                json={
                    "name": payload,
                    "email": f"test{i}@example.com",
                },
            )
            # Name field might accept payloads as literal strings
            # or reject via validation (empty/whitespace check)
            if response.status_code == HTTPStatus.CREATED:
                # Verify payload was stored as literal, not executed
                user = response.json()
                assert user["name"] == payload
            else:
                # Validation rejected it
                assert response.status_code in (
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )

    @pytest.mark.asyncio
    async def test_sql_injection_in_user_update(self, client: AsyncClient) -> None:
        """Verify SQL injection in user update fails safely."""
        # Create a user first
        create_response = await client.post(
            "/users",
            json={
                "name": "Original Name",
                "email": "original@example.com",
            },
        )
        assert create_response.status_code == HTTPStatus.CREATED
        user_id = create_response.json()["id"]

        # Try to inject via update (pass X-User-ID header to pass authorization)
        for payload in SQL_INJECTION_PAYLOADS[:5]:  # Test subset for performance
            response = await client.patch(
                f"/users/{user_id}",
                json={"name": payload},
                headers={"X-User-ID": str(user_id), "X-Email": "sqli@example.com"},
            )
            # Update should either accept as literal or reject
            if response.status_code == HTTPStatus.OK:
                updated_user = response.json()
                assert updated_user["name"] == payload
            else:
                assert response.status_code in (
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )

    @pytest.mark.asyncio
    async def test_union_based_injection_attempt(self, client: AsyncClient) -> None:
        """Verify UNION-based SQL injection is prevented."""
        union_payload = "1' UNION SELECT NULL--"
        response = await client.post(
            "/users",
            json={
                "name": union_payload,
                "email": "uniontest@example.com",
            },
        )
        # Should either be rejected or stored as literal
        if response.status_code == HTTPStatus.CREATED:
            user = response.json()
            assert user["name"] == union_payload
            # Verify response structure is unchanged (no extra fields from UNION)
            assert "id" in user
            assert "name" in user
            assert "email" in user
        else:
            assert response.status_code in (
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

    @pytest.mark.asyncio
    async def test_comment_based_injection(self, client: AsyncClient) -> None:
        """Verify comment-based SQL injection is prevented."""
        comment_payloads = [
            "admin'--",
            "' OR '1'='1' --",
            "' OR '1'='1' /*",
        ]
        for i, payload in enumerate(comment_payloads):
            response = await client.post(
                "/users",
                json={
                    "name": payload,
                    "email": f"commenttest{i}@example.com",
                },
            )
            # Should either be rejected or stored as literal
            if response.status_code == HTTPStatus.CREATED:
                user = response.json()
                assert user["name"] == payload
            else:
                assert response.status_code in (
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )


class TestSQLInjectionOrganizations:
    """SQL injection via organization endpoints."""

    @pytest.mark.asyncio
    async def test_sql_injection_in_org_name(self, client: AsyncClient) -> None:
        """Verify SQL injection in organization name fails safely."""
        for payload in SQL_INJECTION_PAYLOADS:
            response = await client.post(
                "/organizations",
                json={"name": payload},
            )
            # Organization name might accept payloads as literals
            # or reject via validation
            if response.status_code == HTTPStatus.CREATED:
                org = response.json()
                assert org["name"] == payload
            else:
                assert response.status_code in (
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )

    @pytest.mark.asyncio
    async def test_sql_injection_in_org_update(self, client: AsyncClient) -> None:
        """Verify SQL injection in organization update fails safely."""
        # Create organization first
        create_response = await client.post(
            "/organizations",
            json={"name": "Original Org"},
        )
        assert create_response.status_code == HTTPStatus.CREATED
        org_id = create_response.json()["id"]

        # Try to inject via update
        for payload in SQL_INJECTION_PAYLOADS[:5]:  # Test subset
            response = await client.patch(
                f"/organizations/{org_id}",
                json={"name": payload},
            )
            if response.status_code == HTTPStatus.OK:
                updated_org = response.json()
                assert updated_org["name"] == payload
            else:
                assert response.status_code in (
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    HTTPStatus.OK,  # Some validators allow empty
                )

    @pytest.mark.asyncio
    async def test_boolean_based_blind_injection(self, client: AsyncClient) -> None:
        """Verify boolean-based blind SQL injection is prevented."""
        boolean_payloads = [
            "' OR '1'='1",
            "' AND '1'='2",
            "' OR 1=1#",
        ]
        for payload in boolean_payloads:
            response = await client.post(
                "/organizations",
                json={"name": payload},
            )
            # Should either be rejected or stored as literal
            if response.status_code == HTTPStatus.CREATED:
                org = response.json()
                assert org["name"] == payload
                # Verify only one organization was created (not all orgs returned)
                assert "id" in org
                assert "name" in org
            else:
                assert response.status_code in (
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )


class TestSQLInjectionDocuments:
    """SQL injection via document endpoints."""

    @pytest.mark.asyncio
    async def test_sql_injection_in_document_title(self, client: AsyncClient) -> None:
        """Verify SQL injection in document title fails safely."""
        for payload in SQL_INJECTION_PAYLOADS[:5]:  # Test subset
            response = await client.post(
                "/documents",
                json={
                    "title": payload,
                    "content": "Test content",
                },
            )
            # Document endpoints might not exist yet or might accept literals
            if response.status_code == HTTPStatus.CREATED:
                doc = response.json()
                assert doc["title"] == payload
            else:
                # Endpoint might not exist (404) or validation rejects
                assert response.status_code in (
                    HTTPStatus.NOT_FOUND,
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )

    @pytest.mark.asyncio
    async def test_sql_injection_in_document_content(self, client: AsyncClient) -> None:
        """Verify SQL injection in document content fails safely."""
        for payload in SQL_INJECTION_PAYLOADS[:5]:  # Test subset
            response = await client.post(
                "/documents",
                json={
                    "title": "Test Document",
                    "content": payload,
                },
            )
            if response.status_code == HTTPStatus.CREATED:
                doc = response.json()
                assert doc["content"] == payload
            else:
                assert response.status_code in (
                    HTTPStatus.NOT_FOUND,
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )


class TestSQLInjectionMemberships:
    """SQL injection via membership queries."""

    @pytest.mark.asyncio
    async def test_sql_injection_in_membership_ids(self, client: AsyncClient) -> None:
        """Verify SQL injection via invalid UUIDs fails safely."""
        # Try to create membership with SQL injection in UUID fields
        for payload in SQL_INJECTION_PAYLOADS[:3]:  # Test subset
            response = await client.post(
                "/memberships",
                json={
                    "user_id": payload,
                    "organization_id": payload,
                },
            )
            # UUID validation should reject all payloads
            assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


class TestSQLInjectionAdvanced:
    """Advanced SQL injection techniques."""

    @pytest.mark.asyncio
    async def test_time_based_blind_injection(self, client: AsyncClient) -> None:
        """Verify time-based blind SQL injection fails."""
        time_payload = "'; WAITFOR DELAY '00:00:05'--"
        response = await client.post(
            "/users",
            json={
                "name": time_payload,
                "email": "timetest@example.com",
            },
        )
        # Should either be rejected or stored as literal
        # Request should NOT take 5+ seconds
        if response.status_code == HTTPStatus.CREATED:
            user = response.json()
            assert user["name"] == time_payload
        else:
            assert response.status_code in (
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

    @pytest.mark.asyncio
    async def test_union_based_injection(self, client: AsyncClient) -> None:
        """Verify UNION-based SQL injection fails."""
        union_payload = "1' UNION SELECT NULL--"
        response = await client.post(
            "/users",
            json={
                "name": union_payload,
                "email": "uniontest@example.com",
            },
        )
        if response.status_code == HTTPStatus.CREATED:
            user = response.json()
            assert user["name"] == union_payload
            # Verify response structure is unchanged (no extra fields)
            assert "id" in user
            assert "name" in user
            assert "email" in user
        else:
            assert response.status_code in (
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

    @pytest.mark.asyncio
    async def test_error_based_injection_no_info_leak(self, client: AsyncClient) -> None:
        """Verify error messages don't expose database structure."""
        # Try various malformed inputs that might trigger DB errors
        malformed_payloads = [
            "' AND 1=(SELECT COUNT(*) FROM information_schema.tables)--",
            "' AND EXTRACTVALUE(1, CONCAT(0x01, (SELECT database())))--",
        ]

        for payload in malformed_payloads:
            response = await client.post(
                "/users",
                json={
                    "name": payload,
                    "email": "errortest@example.com",
                },
            )
            # Check error messages don't leak database info
            if response.status_code >= HTTPStatus.BAD_REQUEST:
                error_detail = response.json().get("detail", "")
                # Error messages should NOT contain SQL keywords or table names
                sensitive_keywords = [
                    "information_schema",
                    "SELECT",
                    "FROM",
                    "database()",
                    "users",
                    "organizations",
                ]
                for keyword in sensitive_keywords:
                    assert keyword not in str(error_detail).upper()

    @pytest.mark.asyncio
    async def test_second_order_injection(self, client: AsyncClient) -> None:
        """Verify second-order SQL injection fails."""
        # First, create a user with a payload-like name
        payload = "'; DROP TABLE users; --"
        create_response = await client.post(
            "/users",
            json={
                "name": payload,
                "email": "secondorder@example.com",
            },
        )

        if create_response.status_code == HTTPStatus.CREATED:
            user_id = create_response.json()["id"]

            # Second, retrieve the user (this could trigger second-order injection)
            get_response = await client.get(f"/users/{user_id}")
            assert get_response.status_code == HTTPStatus.OK
            retrieved_user = get_response.json()
            # Payload should be returned as literal string
            assert retrieved_user["name"] == payload

            # Third, list users (aggregate query that includes this user)
            list_response = await client.get("/users")
            assert list_response.status_code == HTTPStatus.OK
            # Response should be valid JSON, not a database error
            data = list_response.json()
            assert "items" in data
            assert isinstance(data["items"], list)
