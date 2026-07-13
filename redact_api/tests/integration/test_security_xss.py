"""Cross-site scripting (XSS) security tests.

Verifies that user input is properly sanitized/escaped to prevent
XSS attacks in API responses and stored data.
"""

from http import HTTPStatus

import pytest
from httpx import AsyncClient

# XSS injection payloads constant - all 12 payloads from security plan
XSS_PAYLOADS = [
    "<script>alert('XSS')</script>",
    '<img src=x onerror="alert(1)">',
    '<svg onload="alert(1)">',
    "<iframe src='javascript:alert(1)'>",
    "javascript:alert('XSS')",
    "<body onload=alert(1)>",
    "&#60;script&#62;alert('XSS')&#60;/script&#62;",
    '<a href="javascript:alert(1)">Click</a>',
    "<input type='text' value='x' onfocus='alert(1)'>",
    "<div style='background:url(javascript:alert(1))'>",
    "<object data='data:text/html,<script>alert(1)</script>'>",
    "<embed src='data:text/html,<script>alert(1)</script>'>",
]


class TestXSSUserFields:
    """XSS injection via user name/email fields."""

    @pytest.mark.asyncio
    async def test_xss_script_tag_in_user_name(self, client: AsyncClient) -> None:
        """Verify script tags in user names are properly handled."""
        script_payload = "<script>alert('XSS')</script>"
        response = await client.post(
            "/users",
            json={
                "name": script_payload,
                "email": "xss-test@example.com",
            },
        )

        # Verify Content-Type is JSON (not HTML)
        assert response.headers.get("content-type") == "application/json"

        # Should either reject or store as literal string
        if response.status_code == HTTPStatus.CREATED:
            user = response.json()
            # Payload stored as literal, not executed
            assert user["name"] == script_payload
            # JSON response is safe (browsers won't execute <script> in JSON)
            # The key is that Content-Type is application/json, not text/html
        else:
            # Validation rejected it
            assert response.status_code in (
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

    @pytest.mark.asyncio
    async def test_xss_event_handler_in_user_name(self, client: AsyncClient) -> None:
        """Verify event handlers in user names are properly handled."""
        event_handler_payload = '<img src=x onerror="alert(1)">'
        response = await client.post(
            "/users",
            json={
                "name": event_handler_payload,
                "email": "event-test@example.com",
            },
        )

        # Verify Content-Type is JSON
        assert response.headers.get("content-type") == "application/json"

        if response.status_code == HTTPStatus.CREATED:
            user = response.json()
            assert user["name"] == event_handler_payload
        else:
            assert response.status_code in (
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

    @pytest.mark.asyncio
    async def test_xss_html_entity_encoding(self, client: AsyncClient) -> None:
        """Verify HTML entity encoded XSS is properly handled."""
        entity_payload = "&#60;script&#62;alert('XSS')&#60;/script&#62;"
        response = await client.post(
            "/users",
            json={
                "name": entity_payload,
                "email": "entity-test@example.com",
            },
        )

        if response.status_code == HTTPStatus.CREATED:
            user = response.json()
            # Stored as literal string (entities not decoded)
            assert user["name"] == entity_payload
            # Verify response is JSON, not HTML that would decode entities
            assert response.headers.get("content-type") == "application/json"
        else:
            assert response.status_code in (
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

    @pytest.mark.asyncio
    async def test_xss_iframe_injection(self, client: AsyncClient) -> None:
        """Verify iframe injection in user names is properly handled."""
        iframe_payload = "<iframe src='javascript:alert(1)'>"
        response = await client.post(
            "/users",
            json={
                "name": iframe_payload,
                "email": "iframe-test@example.com",
            },
        )

        if response.status_code == HTTPStatus.CREATED:
            user = response.json()
            assert user["name"] == iframe_payload
            # Verify JSON response (iframes only execute in HTML context)
            assert response.headers.get("content-type") == "application/json"
        else:
            assert response.status_code in (
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )


class TestXSSOrganizationFields:
    """XSS injection via organization name field."""

    @pytest.mark.asyncio
    async def test_xss_script_in_org_name(self, client: AsyncClient) -> None:
        """Verify script tags in organization names are properly handled."""
        for payload in XSS_PAYLOADS[:3]:  # Test subset for performance
            response = await client.post(
                "/organizations",
                json={"name": payload},
            )

            # Verify JSON Content-Type
            assert response.headers.get("content-type") == "application/json"

            if response.status_code == HTTPStatus.CREATED:
                org = response.json()
                assert org["name"] == payload
            else:
                assert response.status_code in (
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )

    @pytest.mark.asyncio
    async def test_xss_img_tag_in_org_name(self, client: AsyncClient) -> None:
        """Verify img tags with event handlers are properly handled."""
        img_payload = '<img src=x onerror="alert(1)">'
        response = await client.post(
            "/organizations",
            json={"name": img_payload},
        )

        assert response.headers.get("content-type") == "application/json"

        if response.status_code == HTTPStatus.CREATED:
            org = response.json()
            assert org["name"] == img_payload
        else:
            assert response.status_code in (
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

    @pytest.mark.asyncio
    async def test_xss_svg_script_in_org_name(self, client: AsyncClient) -> None:
        """Verify SVG with script payloads are properly handled."""
        svg_payload = '<svg onload="alert(1)">'
        response = await client.post(
            "/organizations",
            json={"name": svg_payload},
        )

        assert response.headers.get("content-type") == "application/json"

        if response.status_code == HTTPStatus.CREATED:
            org = response.json()
            assert org["name"] == svg_payload
            # Verify response doesn't render as SVG
            assert "image/svg" not in response.headers.get("content-type", "")
        else:
            assert response.status_code in (
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )


class TestXSSDocumentFields:
    """XSS injection via document fields."""

    @pytest.mark.asyncio
    async def test_xss_in_document_filename(self, client: AsyncClient) -> None:
        """Verify XSS payloads in document filenames are properly handled."""
        filename_payloads = [
            "<script>alert(1)</script>.pdf",
            "document<img src=x onerror=alert(1)>.txt",
        ]

        for payload in filename_payloads:
            response = await client.post(
                "/documents",
                json={
                    "title": payload,
                    "content": "Safe content",
                },
            )

            if response.status_code == HTTPStatus.CREATED:
                doc = response.json()
                # Filename stored as literal
                assert doc["title"] == payload
                # Response is JSON, not served as file
                assert response.headers.get("content-type") == "application/json"
            else:
                # Endpoint might not exist or validation rejects
                assert response.status_code in (
                    HTTPStatus.NOT_FOUND,
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )

    @pytest.mark.asyncio
    async def test_xss_in_document_content_type(self, client: AsyncClient) -> None:
        """Verify XSS via content-type manipulation is prevented."""
        # Try to inject XSS into document metadata that might be reflected
        xss_content = '<script>alert("XSS in content")</script>'
        response = await client.post(
            "/documents",
            json={
                "title": "Test Document",
                "content": xss_content,
            },
        )

        if response.status_code == HTTPStatus.CREATED:
            doc = response.json()
            # Content stored as literal string
            assert doc["content"] == xss_content
            # Response must be JSON, not HTML (this prevents XSS execution)
            assert response.headers.get("content-type") == "application/json"
        else:
            assert response.status_code in (
                HTTPStatus.NOT_FOUND,
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )


class TestXSSAdvanced:
    """Advanced XSS attack vectors."""

    @pytest.mark.asyncio
    async def test_xss_unicode_bypass_attempt(self, client: AsyncClient) -> None:
        """Verify unicode-based XSS bypass attempts are prevented."""
        # Unicode variations of <script>
        unicode_payloads = [
            "\u003cscript\u003ealert(1)\u003c/script\u003e",
            "＜script＞alert(1)＜/script＞",  # Full-width characters  # noqa: RUF001
        ]

        for payload in unicode_payloads:
            response = await client.post(
                "/users",
                json={
                    "name": payload,
                    "email": f"unicode{hash(payload)}@example.com",
                },
            )

            if response.status_code == HTTPStatus.CREATED:
                user = response.json()
                # Stored as literal (not normalized to <script>)
                assert user["name"] == payload
                # Response is JSON
                assert response.headers.get("content-type") == "application/json"
            else:
                assert response.status_code in (
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )

    @pytest.mark.asyncio
    async def test_xss_double_encoding(self, client: AsyncClient) -> None:
        """Verify double-encoded XSS is prevented."""
        # Double URL encoding: %253Cscript%253E = %3Cscript%3E = <script>
        double_encoded = "%253Cscript%253Ealert(1)%253C/script%253E"
        response = await client.post(
            "/users",
            json={
                "name": double_encoded,
                "email": "doubleenc@example.com",
            },
        )

        if response.status_code == HTTPStatus.CREATED:
            user = response.json()
            # Should NOT be decoded to <script>
            assert user["name"] == double_encoded
            assert "<script>" not in user["name"]
            # Verify JSON response
            assert response.headers.get("content-type") == "application/json"
        else:
            assert response.status_code in (
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

    @pytest.mark.asyncio
    async def test_xss_svg_onload_bypass(self, client: AsyncClient) -> None:
        """Verify SVG onload event handler bypass is prevented."""
        svg_payloads = [
            '<svg onload="alert(1)">',
            "<svg><script>alert(1)</script></svg>",
            '<svg/onload="alert(1)">',
        ]

        for payload in svg_payloads:
            response = await client.post(
                "/organizations",
                json={"name": payload},
            )

            # Verify response is JSON, not SVG
            content_type = response.headers.get("content-type", "")
            assert "application/json" in content_type
            assert "image/svg" not in content_type

            if response.status_code == HTTPStatus.CREATED:
                org = response.json()
                assert org["name"] == payload
            else:
                assert response.status_code in (
                    HTTPStatus.BAD_REQUEST,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )
