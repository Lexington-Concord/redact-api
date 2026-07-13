# Implementing Email Service Integration

## Overview

The `send_welcome_email_task()` in `redact_api/core/background_tasks.py` is currently a **placeholder** that logs success but doesn't send emails. This guide shows how to implement a real email service integration.

**Current Placeholder Behavior**:
```python
await asyncio.sleep(0.1)  # Placeholder - no email sent
logger.info("welcome_email_sent", extra={...})  # Misleading log
```

**Result**: New users are created but never notified, leading to a poor onboarding experience.

---

## What You Need to Implement

Replace the placeholder `send_welcome_email_task()` function with actual email service calls:

```python
async def send_welcome_email_task(user_id: UUID, email: str) -> None:
    """Send welcome email to new user (background task - no blocking)."""
    try:
        logger.info("sending_welcome_email", extra={"user_id": str(user_id), "email": email})

        # TODO: Replace asyncio.sleep with actual email service call
        # Your implementation here

        logger.info("welcome_email_sent", extra={"user_id": str(user_id), "email": email})
    except Exception:
        logger.exception("Failed to send welcome email", extra={"user_id": str(user_id)})
```

---

## Environment Configuration Template

Create a `.env` file with the following variables based on your chosen provider:

```bash
# .env.example for Email Service

# Provider Selection (choose one: sendgrid, ses, mailgun, smtp)
EMAIL_PROVIDER=sendgrid

# SendGrid Configuration
SENDGRID_API_KEY=your_sendgrid_api_key_here
SENDGRID_FROM_EMAIL=noreply@yourdomain.com
SENDGRID_FROM_NAME=Your App Name

# AWS SES Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
SES_FROM_EMAIL=noreply@yourdomain.com

# Mailgun Configuration
MAILGUN_API_KEY=your_mailgun_api_key
MAILGUN_DOMAIN=mg.yourdomain.com
MAILGUN_FROM_EMAIL=noreply@yourdomain.com

# SMTP Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM_EMAIL=noreply@yourdomain.com
SMTP_USE_TLS=true

# Retry Configuration
EMAIL_RETRY_ATTEMPTS=3
EMAIL_RETRY_MIN_WAIT=1
EMAIL_RETRY_MAX_WAIT=10
```

**Naming Convention:** We use provider-specific prefixes (SENDGRID_, AWS_, MAILGUN_, SMTP_) to allow multi-provider configuration in the same environment.

---

## Email Provider Comparison

Choose the right provider for your use case:

| Provider | Cost/Email | Delivery Speed | Setup Complexity | Best For | Free Tier |
|----------|------------|----------------|------------------|----------|-----------|
| **SendGrid** | $0.08-0.30 | Fast (1-5 sec) | Medium | Marketing emails, high volume | 100/day |
| **AWS SES** | $0.10/1000 | Very fast (<1 sec) | High (AWS setup) | Transactional emails, AWS users | 62K/month (EC2) |
| **Mailgun** | $0.80/1000 | Medium (2-10 sec) | Low | API-first teams, webhooks | 5K/month |
| **SMTP** | Depends on provider | Varies | Low | Simple setup, any provider | Varies |

### Detailed Provider Comparison

**SendGrid**
- ✅ Excellent deliverability (95%+)
- ✅ Comprehensive analytics dashboard
- ✅ Template management UI
- ❌ More expensive for high volume
- ❌ Requires API key management

**AWS SES**
- ✅ Cheapest for high volume ($1 per 10K emails)
- ✅ Integrates with AWS ecosystem
- ✅ Very reliable infrastructure
- ❌ Complex IAM setup required
- ❌ Need to request production access (starts in sandbox)

**Mailgun**
- ✅ Simple API, great for developers
- ✅ Excellent webhook support
- ✅ EU data residency options
- ❌ Slower delivery than SendGrid/SES
- ❌ Limited free tier

**SMTP**
- ✅ Works with any email provider
- ✅ Simple configuration
- ✅ No vendor lock-in
- ❌ Slower than APIs
- ❌ Rate limits vary by provider
- ❌ No built-in analytics

### Recommendation

- **Small projects (<5K emails/month)**: SMTP or Mailgun free tier
- **Transactional emails (password resets, etc.)**: AWS SES or SendGrid
- **Marketing emails**: SendGrid
- **Already on AWS**: AWS SES
- **EU data residency required**: Mailgun EU region

---

## Integration Options

Choose one of these email service providers based on your needs:

### Option 1: SendGrid (Recommended for Most)

**Best for**: High delivery reliability, great documentation, good free tier.

**Setup**:
1. Create account at https://sendgrid.com
2. Generate API key: Settings → API Keys → Create API Key
3. Add to `.env`:
   ```bash
   SENDGRID_API_KEY=SG.your-api-key-here
   ```

**Installation**:
```bash
uv pip install sendgrid>=6.11.0,<7.0
```

**Implementation**:

```python
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

async def send_welcome_email_task(user_id: UUID, email: str) -> None:
    """Send welcome email using SendGrid."""
    try:
        logger.info(
            "sending_welcome_email",
            extra={"user_id": str(user_id), "email": email},
        )

        # Create email message
        message = Mail(
            from_email="noreply@redact_api.example.com",
            to_emails=email,
            subject="Welcome to redact_api!",
            html_content="<strong>Welcome!</strong><p>Your account has been created.</p>"
        )

        # Send email (non-blocking via event loop)
        sg = SendGridAPIClient(os.environ.get("SENDGRID_API_KEY"))
        # Note: SendGrid client is sync, so run in executor to avoid blocking
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: sg.send(message)
        )

        logger.info(
            "welcome_email_sent",
            extra={"user_id": str(user_id), "email": email},
        )
    except Exception:
        logger.exception(
            "Failed to send welcome email",
            extra={"user_id": str(user_id), "email": email},
        )
```

**Configuration with Templates**:
```python
from sendgrid.helpers.mail import Mail

# Use SendGrid dynamic templates
message = Mail(
    from_email="noreply@redact_api.example.com",
    to_emails=email,
)
message.template_id = "d-your-template-id"  # Create in SendGrid dashboard
message.dynamic_template_data = {
    "user_id": str(user_id),
    "first_name": "User"  # Pass from database
}
```

---

### Option 2: AWS SES (Best for AWS Ecosystem)

**Best for**: Already using AWS, need tight integration with infrastructure.

**Setup**:
1. Enable SES in AWS Console
2. Request production access (verify domain)
3. Create IAM user with SES permissions
4. Add to `.env`:
   ```bash
   AWS_REGION=us-east-1
   AWS_ACCESS_KEY_ID=AKIA...
   AWS_SECRET_ACCESS_KEY=...
   ```

**Installation**:
```bash
uv pip install boto3
```

**Implementation**:

```python
import aioboto3
from botocore.exceptions import ClientError

async def send_welcome_email_task(user_id: UUID, email: str) -> None:
    """Send welcome email using AWS SES."""
    try:
        logger.info(
            "sending_welcome_email",
            extra={"user_id": str(user_id), "email": email},
        )

        # Create SES client
        session = aioboto3.Session()
        async with session.client("ses", region_name="us-east-1") as client:
            await client.send_email(
                Source="noreply@redact_api.example.com",
                Destination={"ToAddresses": [email]},
                Message={
                    "Subject": {"Data": "Welcome to redact_api!"},
                    "Body": {
                        "Html": {
                            "Data": "<strong>Welcome!</strong><p>Your account has been created.</p>"
                        }
                    }
                }
            )

        logger.info(
            "welcome_email_sent",
            extra={"user_id": str(user_id), "email": email},
        )
    except ClientError as e:
        logger.exception(
            "Failed to send welcome email via SES",
            extra={"user_id": str(user_id), "email": email, "error_code": e.response["Error"]["Code"]},
        )
    except Exception:
        logger.exception(
            "Failed to send welcome email",
            extra={"user_id": str(user_id), "email": email},
        )
```

---

### Option 3: Mailgun (Great API, Developer-Friendly)

**Best for**: Developers who like API-driven workflows, good logging/tracking.

**Setup**:
1. Create account at https://mailgun.com
2. Add domain and verify it
3. Get API key from dashboard
4. Add to `.env`:
   ```bash
   MAILGUN_API_KEY=key-your-api-key
   MAILGUN_DOMAIN=mg.redact_api.example.com
   ```

**Installation**:
```bash
uv pip install httpx>=0.27.0
```

**Implementation**:

```python
import httpx
from redact_api.core.http_client import http_client

async def send_welcome_email_task(user_id: UUID, email: str) -> None:
    """Send welcome email using Mailgun."""
    try:
        logger.info(
            "sending_welcome_email",
            extra={"user_id": str(user_id), "email": email},
        )

        mailgun_api_key = os.environ.get("MAILGUN_API_KEY")
        mailgun_domain = os.environ.get("MAILGUN_DOMAIN")

        async with http_client() as client:
            response = await client.post(
                f"https://api.mailgun.net/v3/{mailgun_domain}/messages",
                auth=("api", mailgun_api_key),
                data={
                    "from": f"noreply@redact_api.example.com",
                    "to": email,
                    "subject": "Welcome to redact_api!",
                    "html": "<strong>Welcome!</strong><p>Your account has been created.</p>"
                }
            )
            response.raise_for_status()

        logger.info(
            "welcome_email_sent",
            extra={"user_id": str(user_id), "email": email},
        )
    except httpx.HTTPStatusError as e:
        logger.exception(
            "Failed to send welcome email via Mailgun",
            extra={"user_id": str(user_id), "email": email, "status": e.response.status_code},
        )
    except Exception:
        logger.exception(
            "Failed to send welcome email",
            extra={"user_id": str(user_id), "email": email},
        )
```

---

### Option 4: SMTP (Self-Hosted)

**Best for**: Full control, on-premises email server, or development with Mailhog.

**Setup**:
Add to `.env`:
```bash
SMTP_HOST=smtp.gmail.com  # or your mail server
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-specific-password
SMTP_FROM_EMAIL=noreply@redact_api.example.com
```

**Installation**:
```bash
uv pip install aiosmtplib
```

**Implementation**:

```python
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

async def send_welcome_email_task(user_id: UUID, email: str) -> None:
    """Send welcome email using SMTP."""
    try:
        logger.info(
            "sending_welcome_email",
            extra={"user_id": str(user_id), "email": email},
        )

        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = "Welcome to redact_api!"
        message["From"] = os.environ.get("SMTP_FROM_EMAIL")
        message["To"] = email

        html = MIMEText("<strong>Welcome!</strong><p>Your account has been created.</p>", "html")
        message.attach(html)

        # Send email
        async with aiosmtplib.SMTP(hostname=os.environ.get("SMTP_HOST"), port=int(os.environ.get("SMTP_PORT", 587))) as smtp:
            await smtp.starttls()
            await smtp.login(os.environ.get("SMTP_USERNAME"), os.environ.get("SMTP_PASSWORD"))
            await smtp.send_message(message)

        logger.info(
            "welcome_email_sent",
            extra={"user_id": str(user_id), "email": email},
        )
    except Exception:
        logger.exception(
            "Failed to send welcome email via SMTP",
            extra={"user_id": str(user_id), "email": email},
        )
```

---

## Retry Logic Dependencies

For implementing retry patterns with exponential backoff:

```bash
uv pip install tenacity>=8.2.0,<9.0
```

---

## Testing Dependencies

For running the test examples in this guide:

```bash
# Unit testing with mocks
uv pip install --group dev pytest-httpx>=0.21.0
uv pip install --group dev pytest-mock>=3.12.0

# Integration testing with Mailhog
# Mailhog doesn't need a Python client - use httpx directly to query API
```

### Mailhog Setup for Integration Testing

Mailhog is an SMTP server for testing. Run it with Docker:

```bash
docker run -d -p 1025:1025 -p 8025:8025 mailhog/mailhog
```

- Port 1025: SMTP server (for sending test emails)
- Port 8025: Web UI and API (for retrieving emails)

**Fixture for Mailhog:**

```python
# conftest.py
import httpx
import pytest

@pytest.fixture
async def mailhog_client():
    """HTTP client for querying Mailhog API."""
    async with httpx.AsyncClient(base_url="http://localhost:8025") as client:
        yield client
```

---

## Error Scenario Testing

### Testing API Failures (4xx/5xx)

Test how your email service handles provider API errors:

```python
import pytest
from unittest.mock import patch, AsyncMock
from uuid import UUID

@pytest.mark.asyncio
async def test_sendgrid_401_unauthorized():
    """Test handling of SendGrid authentication failure."""
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    email = "user@example.com"

    with patch("sendgrid.SendGridAPIClient") as mock_sg:
        mock_instance = mock_sg.return_value
        # Simulate 401 Unauthorized from SendGrid
        from sendgrid.helpers.errors import SendGridException
        mock_instance.send.side_effect = SendGridException("401 Unauthorized")

        # Call should log exception, not raise
        await send_welcome_email_task(user_id, email)

        # Verify exception was logged
        # (check logs contain "401" and "Unauthorized")

@pytest.mark.asyncio
async def test_sendgrid_500_server_error():
    """Test handling of SendGrid server errors."""
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    email = "user@example.com"

    with patch("sendgrid.SendGridAPIClient") as mock_sg:
        mock_instance = mock_sg.return_value
        # Simulate 500 Internal Server Error from SendGrid
        from sendgrid.helpers.errors import SendGridException
        mock_instance.send.side_effect = SendGridException("500 Server Error")

        # Should trigger retry logic
        with patch("tenacity.retry") as mock_retry:
            # After retries exhausted, should log and continue
            await send_welcome_email_task(user_id, email)
```

### Testing Timeout Scenarios

Test network timeout handling:

```python
@pytest.mark.asyncio
async def test_email_timeout():
    """Test handling of SendGrid API timeout."""
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    email = "user@example.com"

    with patch("sendgrid.SendGridAPIClient") as mock_sg:
        mock_instance = mock_sg.return_value
        # Simulate timeout
        import httpx
        mock_instance.send.side_effect = httpx.TimeoutException("Request timeout")

        # Should be retried (transient failure)
        # After max retries, should log and continue
        await send_welcome_email_task(user_id, email)
```

### Testing Rate Limiting (429)

Test handling of rate limit responses:

```python
@pytest.mark.asyncio
async def test_sendgrid_rate_limit_429():
    """Test handling of SendGrid rate limiting."""
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    email = "user@example.com"

    with patch("sendgrid.SendGridAPIClient") as mock_sg:
        mock_instance = mock_sg.return_value
        from sendgrid.helpers.errors import SendGridException

        # Simulate 429 Too Many Requests
        mock_instance.send.side_effect = SendGridException("429 Too Many Requests")

        # Should trigger retry with backoff
        await send_welcome_email_task(user_id, email)

        # Verify exponential backoff was applied
        # (should wait longer between retries)
```

### Testing Network Connection Errors

Test handling of connection failures:

```python
@pytest.mark.asyncio
async def test_network_connection_error():
    """Test handling of network connection failures."""
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    email = "user@example.com"

    with patch("sendgrid.SendGridAPIClient") as mock_sg:
        mock_instance = mock_sg.return_value
        # Simulate network unreachable
        import httpx
        mock_instance.send.side_effect = httpx.ConnectError("Network unreachable")

        # Should be retried (transient failure)
        await send_welcome_email_task(user_id, email)

        # Verify retry was attempted
        assert mock_instance.send.call_count >= 1  # Retried at least once
```

### Testing Invalid Credentials

Test handling of invalid API credentials:

```python
@pytest.mark.asyncio
async def test_invalid_credentials():
    """Test handling of invalid SendGrid API key."""
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    email = "user@example.com"

    with patch("sendgrid.SendGridAPIClient") as mock_sg:
        mock_instance = mock_sg.return_value
        from sendgrid.helpers.errors import SendGridException

        # Simulate 403 Forbidden (invalid API key)
        mock_instance.send.side_effect = SendGridException("403 Forbidden")

        # Should NOT retry (permanent failure)
        await send_welcome_email_task(user_id, email)

        # Verify error was logged
        # (should only call send once, no retries)
        assert mock_instance.send.call_count == 1
```

---

## Test Fixture Definitions

Add these fixtures to your `conftest.py`:

```python
# conftest.py
import pytest
from pytest_httpx import HTTPXMock

@pytest.fixture
def httpx_mock() -> HTTPXMock:
    """Mock for httpx requests (provided by pytest-httpx)."""
    return HTTPXMock()

@pytest.fixture
async def mailhog_client():
    """HTTP client for Mailhog API."""
    import httpx
    async with httpx.AsyncClient(base_url="http://localhost:8025") as client:
        # Clear all messages before each test
        await client.delete("/api/v1/messages")
        yield client
```

---

## Error Handling Patterns

### Retry Logic with Tenacity

For transient failures (network timeouts, temporary service issues), implement retry logic:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sendgrid.helpers.errors import SendGridException
import httpx

@retry(
    retry=retry_if_exception_type((httpx.RequestError, SendGridException)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
async def send_welcome_email_task(user_id: UUID, email: str) -> None:
    """Send welcome email with automatic retries."""
    # Your email sending logic here
    pass
```

### Dead Letter Queue Pattern

Store failed emails for manual review:

```python
async def handle_email_failure(user_id: UUID, email: str, error: str) -> None:
    """Store failed email in dead letter queue for later retry."""
    from datetime import datetime, UTC
    from redact_api.models import FailedEmail
    from redact_api.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        failed_email = FailedEmail(
            user_id=user_id,
            email=email,
            error_message=error,
            created_at=datetime.now(UTC),
            retry_count=0
        )
        session.add(failed_email)
        await session.commit()


async def send_welcome_email_task(user_id: UUID, email: str) -> None:
    """Send welcome email, storing failures for later retry."""
    try:
        # Send email...
        pass
    except Exception as e:
        logger.exception("Failed to send welcome email", extra={"user_id": str(user_id)})

        # Store in dead letter queue
        await handle_email_failure(user_id, email, str(e))
```

---

## Testing Email Service Integration

### Unit Test: Mocking SendGrid

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import UUID

@pytest.mark.asyncio
async def test_send_welcome_email_with_sendgrid():
    """Test welcome email with mocked SendGrid."""
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    email = "user@example.com"

    with patch("sendgrid.SendGridAPIClient") as mock_sg:
        # Mock the send method
        mock_instance = mock_sg.return_value
        mock_instance.send.return_value = None

        # Call function
        await send_welcome_email_task(user_id, email)

        # Verify SendGrid was called
        mock_sg.assert_called_once()
        mock_instance.send.assert_called_once()

        # Verify call arguments
        call_args = mock_instance.send.call_args[0][0]
        assert email in str(call_args.to)
```

### Unit Test: Mocking httpx for Mailgun

```python
@pytest.mark.asyncio
async def test_send_welcome_email_with_mailgun(httpx_mock):
    """Test welcome email with mocked Mailgun API."""
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    email = "user@example.com"

    # Mock Mailgun API response
    httpx_mock.add_response(
        method="POST",
        url="https://api.mailgun.net/v3/mg.example.com/messages",
        status_code=200,
        json={"message": "Queued. Thank you.", "id": "<20230101000000.1234567890@mg.example.com>"}
    )

    # Call function
    await send_welcome_email_task(user_id, email)

    # Verify request was made
    request = httpx_mock.get_request()
    assert request.method == "POST"
    assert "messages" in request.url.path
```

### Unit Test: Mocking SMTP

```python
@pytest.mark.asyncio
async def test_send_welcome_email_with_smtp(mocker):
    """Test welcome email with mocked SMTP."""
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    email = "user@example.com"

    # Mock aiosmtplib
    mock_smtp = AsyncMock()
    mocker.patch("aiosmtplib.SMTP", return_value=mock_smtp)

    # Call function
    await send_welcome_email_task(user_id, email)

    # Verify SMTP methods called
    mock_smtp.__aenter__.return_value.starttls.assert_called_once()
    mock_smtp.__aenter__.return_value.login.assert_called_once()
    mock_smtp.__aenter__.return_value.send_message.assert_called_once()
```

### Integration Test: Mailhog for Development

Use Mailhog to test email locally without real email service:

```bash
# Start Mailhog (catch-all email server for testing)
docker run -d -p 1025:1025 -p 8025:8025 mailhog/mailhog

# Configure .env
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USERNAME=test
SMTP_PASSWORD=test
```

**Integration test**:
```python
@pytest.mark.asyncio
async def test_send_welcome_email_integration_mailhog(mailhog_client):
    """Test email delivery with real Mailhog server."""
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    email = "user@example.com"

    # Send email
    await send_welcome_email_task(user_id, email)

    # Verify email arrived in Mailhog
    messages = mailhog_client.get_messages()
    assert len(messages) == 1
    assert messages[0]["To"][0]["Address"] == email
    assert "Welcome" in messages[0]["Content"]["Headers"]["Subject"][0]

    # Cleanup
    mailhog_client.delete_all_messages()
```

---

## Configuration Checklist

Before going to production:

- [ ] Email service API key added to `.env` (never commit to git)
- [ ] `SMTP_FROM_EMAIL` matches verified domain (for SMTP/SendGrid/SES)
- [ ] Test email sent successfully to test account
- [ ] Email appears in recipient's inbox (check spam folder)
- [ ] Retry logic implemented for transient failures
- [ ] Error logging configured and tested
- [ ] Unit tests passing with mocked service
- [ ] Integration tests passing with test credentials
- [ ] Email template contains unsubscribe link (legal requirement)
- [ ] Rate limiting configured if needed

---

## Common Mistakes to Avoid

### ❌ Mistake 1: Blocking Email Sending in HTTP Response

```python
# BAD - blocks user's request until email sent (30+ second delay)
@router.post("/users")
async def create_user(payload: UserCreate, session: SessionDep):
    user = await create_user_service(session, payload)
    await send_welcome_email_task(user.id, user.email)  # BLOCKS!
    return user
```

**Fix**: Use `asyncio.create_task()` for fire-and-forget:
```python
# GOOD - sends email asynchronously, returns immediately
@router.post("/users")
async def create_user(payload: UserCreate, session: SessionDep):
    user = await create_user_service(session, payload)
    asyncio.create_task(send_welcome_email_task(user.id, user.email))
    return user
```

### ❌ Mistake 2: Missing Exception Handling

```python
# BAD - if email fails, user isn't created but endpoint already returned 200
async def send_welcome_email_task(user_id: UUID, email: str) -> None:
    sg = SendGridAPIClient(api_key)
    sg.send(message)  # No try/except - crashes the task
```

**Fix**: Always wrap in try/except:
```python
# GOOD - logs failure, doesn't crash the task
async def send_welcome_email_task(user_id: UUID, email: str) -> None:
    try:
        sg = SendGridAPIClient(api_key)
        sg.send(message)
    except Exception:
        logger.exception("Failed to send email", extra={...})
```

### ❌ Mistake 3: Invalid Email Addresses

```python
# BAD - sends to invalid address silently
await send_email(email="not-an-email")
```

**Fix**: Validate email before sending:
```python
# GOOD - validates before attempting send
from email_validator import validate_email

try:
    valid = validate_email(email)
    await send_email(valid.email)
except Exception:
    logger.error("Invalid email address", extra={"email": email})
```

### ❌ Mistake 4: Hardcoding API Keys

```python
# BAD - API key visible in code and git history
api_key = "SG.your-api-key-hardcoded"
```

**Fix**: Always use environment variables:
```python
# GOOD - read from .env, never commit to git
api_key = os.environ.get("SENDGRID_API_KEY")
if not api_key:
    raise ValueError("SENDGRID_API_KEY not set in .env")
```

### ❌ Mistake 5: No Retry Logic for Transient Failures

```python
# BAD - temporary network issue causes lost email
try:
    await send_email()
except NetworkError:
    logger.error("Failed to send")  # Give up after first failure
```

**Fix**: Retry on transient errors:
```python
# GOOD - retries on timeout, not on auth errors
@retry(
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def send_email():
    await send_email_service()
```

### ❌ Mistake 6: Synchronous Email Client in Async Function

```python
# BAD - blocks event loop, breaks concurrency
from sendgrid import SendGridAPIClient

async def send_email():
    sg = SendGridAPIClient(api_key)
    sg.send(message)  # Synchronous call blocks entire event loop!
```

**Fix**: Run sync code in executor:
```python
# GOOD - offloads sync work to thread pool
async def send_email():
    sg = SendGridAPIClient(api_key)
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: sg.send(message)
    )
```

---

## Summary

To implement email service integration:

1. **Choose a provider** based on your infrastructure (SendGrid, SES, Mailgun, SMTP)
2. **Add configuration** to `.env` with API keys
3. **Install dependencies** via pip
4. **Replace placeholder** in `send_welcome_email_task()`
5. **Add retry logic** for transient failures
6. **Write tests** with mocked email service
7. **Verify** emails deliver to real addresses
8. **Deploy** with confidence knowing emails are being sent

Choose **SendGrid** if you're unsure - it has the best documentation and reliability for most use cases.

---

## CAN-SPAM Compliance

The **CAN-SPAM Act** requires all marketing emails to include specific elements:

1. **Unsubscribe Header**: Add `List-Unsubscribe` header (RFC 8058)
2. **Clear Identification**: Email must be identifiable as advertisement
3. **Physical Address**: Your company's physical mailing address required
4. **Unsubscribe Link**: Must be functional and honored within 10 days

### Implementation

```python
async def send_marketing_email_can_spam_compliant(
    recipient_email: str,
    subject: str,
    html_content: str,
    org_id: UUID
) -> None:
    """Send CAN-SPAM compliant marketing email."""
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    # Create email with unsubscribe header
    message = Mail(
        from_email=settings.marketing_from_email,
        to_emails=recipient_email,
        subject=subject,
        html_content=html_content
    )

    # Add List-Unsubscribe header (RFC 8058)
    message.reply_to = "noreply@yourdomain.com"

    # Add custom headers for unsubscribe
    message.custom_headers = {
        "List-Unsubscribe": f"<https://yourdomain.com/unsubscribe?org_id={org_id}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"
    }

    # Include footer with company address and unsubscribe link
    footer_html = f"""
    <hr style="border: none; border-top: 1px solid #ddd; margin: 40px 0;">
    <p style="font-size: 12px; color: #999;">
        <strong>Your Company Inc.</strong><br>
        123 Main Street<br>
        Anytown, ST 12345<br>
        <a href="https://yourdomain.com/unsubscribe?org_id={org_id}">Unsubscribe from marketing emails</a>
    </p>
    """

    message.html_content = f"{html_content}{footer_html}"

    sg = SendGridAPIClient(settings.sendgrid_api_key)
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: sg.send(message)
    )

    logger.info(
        "can_spam_compliant_email_sent",
        extra={"org_id": str(org_id), "recipient": recipient_email}
    )
```

### Unsubscribe Endpoint

```python
@router.get("/unsubscribe")
async def unsubscribe_from_emails(
    org_id: UUID,
    token: str = None,
    session: AsyncSession = Depends(get_session)
):
    """Handle unsubscribe requests (must honor within 10 days)."""
    try:
        # Mark organization as unsubscribed
        org = await session.get(Organization, org_id)
        if org:
            org.marketing_emails_enabled = False
            await session.commit()

            logger.info(
                "user_unsubscribed",
                extra={"org_id": str(org_id)}
            )

        return {"message": "You have been unsubscribed. Changes take effect immediately."}

    except Exception:
        logger.exception("Unsubscribe failed", extra={"org_id": str(org_id)})
        return {"error": "Failed to process unsubscribe"}, 500
```

---

## Email Service Best Practices

### Monitoring & Metrics

Track these metrics for email service health:

```python
from prometheus_client import Counter, Histogram, Gauge

# Metrics
email_sent_total = Counter(
    "email_sent_total",
    "Total emails sent",
    ["provider", "template"]
)

email_failed_total = Counter(
    "email_failed_total",
    "Total email failures",
    ["provider", "error_type"]
)

email_delivery_time = Histogram(
    "email_delivery_time_seconds",
    "Time to send email",
    ["provider"]
)

email_queue_size = Gauge(
    "email_queue_size",
    "Current email queue size"
)

async def send_welcome_email_with_metrics(user_id: UUID, email: str) -> None:
    """Send email and track metrics."""
    import time
    start = time.time()

    try:
        await send_welcome_email_task(user_id, email)
        email_sent_total.labels(provider="sendgrid", template="welcome").inc()
    except Exception as e:
        email_failed_total.labels(
            provider="sendgrid",
            error_type=type(e).__name__
        ).inc()
        raise
    finally:
        duration = time.time() - start
        email_delivery_time.labels(provider="sendgrid").observe(duration)
```

---

## Observability & Logging

Implement structured logging for debugging:

```python
async def send_welcome_email_observable(user_id: UUID, email: str) -> None:
    """Send email with detailed observability."""
    import json
    from datetime import datetime, UTC

    log_context = {
        "user_id": str(user_id),
        "email": email,
        "timestamp": datetime.now(UTC).isoformat(),
        "provider": "sendgrid"
    }

    try:
        logger.info("email_send_started", extra=log_context)

        # Send email...
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        # ... (send logic)

        log_context["status"] = "sent"
        log_context["delivery_time_ms"] = delivery_duration_ms

        logger.info("email_send_completed", extra=log_context)

    except Exception as e:
        log_context["status"] = "failed"
        log_context["error_type"] = type(e).__name__
        log_context["error_message"] = str(e)

        logger.exception("email_send_failed", extra=log_context)
        raise
```
