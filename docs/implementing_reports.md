# Implementing Report Generation

## Overview

The `generate_activity_report_task()` in `redact_api/core/background_tasks.py` is currently a **placeholder** that logs success but doesn't generate reports. This guide shows how to implement real report generation and delivery.

**Current Placeholder Behavior**:
```python
await asyncio.sleep(0.1)  # Placeholder - no report generated
logger.info("activity_report_generated", extra={...})  # Misleading log
```

**Problem**: Users request reports but receive nothing, leading to:
- Poor user experience (no analytics)
- Lost business insights
- Regulatory non-compliance (missing audit trails)
- Feature perceived as broken

---

## What You Need to Implement

Replace the placeholder function with actual report generation and delivery:

```python
async def generate_activity_report_task(org_id: UUID, period: str) -> None:
    """Generate activity report for organization."""
    try:
        logger.info(
            "generating_activity_report",
            extra={"org_id": str(org_id), "period": period},
        )

        # TODO: Replace asyncio.sleep with actual report generation
        # 1. Query analytics data
        # 2. Format report (PDF, CSV, or JSON)
        # 3. Deliver via email, storage, or webhook

        logger.info("activity_report_generated", extra={"org_id": str(org_id)})
    except Exception:
        logger.exception("Failed to generate activity report", extra={"org_id": str(org_id)})
```

---

## Step 1: Query Analytics Data

### Aggregate Activity Logs by Period

```python
from datetime import datetime, timedelta, UTC
from sqlalchemy import select, func

async def get_report_data(
    session: AsyncSession,
    org_id: UUID,
    period: str
) -> dict:
    """Query analytics data for report generation."""

    # Determine date range based on period
    end_date = datetime.now(UTC).date()
    if period == "daily":
        start_date = end_date - timedelta(days=1)
    elif period == "weekly":
        start_date = end_date - timedelta(weeks=1)
    elif period == "monthly":
        start_date = end_date - timedelta(days=30)
    elif period == "quarterly":
        start_date = end_date - timedelta(days=90)
    else:
        raise ValueError(f"Unknown period: {period}")

    # Count actions by type
    actions_stmt = select(
        ActivityLog.action,
        func.count(ActivityLog.id).label("count")
    ).where(
        ActivityLog.org_id == org_id,
        ActivityLog.created_at >= start_date,
        ActivityLog.created_at < end_date
    ).group_by(ActivityLog.action)

    actions_result = await session.execute(actions_stmt)
    actions = {row[0]: row[1] for row in actions_result}

    # Count resources created
    resources_stmt = select(
        ActivityLog.resource_type,
        func.count(ActivityLog.id).label("count")
    ).where(
        ActivityLog.org_id == org_id,
        ActivityLog.action == "CREATE",
        ActivityLog.created_at >= start_date,
        ActivityLog.created_at < end_date
    ).group_by(ActivityLog.resource_type)

    resources_result = await session.execute(resources_stmt)
    resources = {row[0]: row[1] for row in resources_result}

    # Get top active users
    users_stmt = select(
        User.id,
        User.email,
        func.count(ActivityLog.id).label("activity_count")
    ).select_from(ActivityLog).join(User).where(
        ActivityLog.org_id == org_id,
        ActivityLog.created_at >= start_date,
        ActivityLog.created_at < end_date
    ).group_by(User.id).order_by(func.count(ActivityLog.id).desc()).limit(10)

    users_result = await session.execute(users_stmt)
    top_users = [
        {"email": row[1], "activity_count": row[2]}
        for row in users_result
    ]

    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_actions": sum(actions.values()),
        "actions_by_type": actions,
        "resources_created": resources,
        "top_active_users": top_users,
    }
```

### Timezone Handling

**Critical**: Always use UTC for all date/time operations in reports. This ensures:
- Consistency across distributed systems
- Correct handling during DST transitions
- No ambiguity in scheduling

#### Why UTC Everywhere?

| Issue | Problem | UTC Solution |
|-------|---------|--------------|
| **Daylight Saving Time (DST)** | 2:00 AM occurs twice in spring; 3:00-4:00 AM doesn't exist | UTC never changes |
| **Distributed teams** | 2:00 AM is different in each timezone | UTC is global standard |
| **Scheduling ambiguity** | "2:00 AM local time" changes meaning after DST shift | 02:00 UTC is always the same absolute time |
| **Database consistency** | Timestamps in different zones are hard to compare | UTC timestamps are unambiguous |

#### Implementation

```python
from datetime import datetime, timedelta, UTC

async def get_report_data(
    session: AsyncSession,
    org_id: UUID,
    period: str
) -> dict:
    """Query analytics data using UTC throughout."""

    # Always use UTC.now(), never datetime.now() (which uses local time)
    end_date = datetime.now(UTC).date()  # CORRECT
    # end_date = datetime.now().date()  # WRONG - uses local timezone

    if period == "daily":
        start_date = end_date - timedelta(days=1)
    elif period == "weekly":
        start_date = end_date - timedelta(weeks=1)
    elif period == "monthly":
        start_date = end_date - timedelta(days=30)
    else:
        raise ValueError(f"Unknown period: {period}")

    # Query using UTC date range
    stmt = select(ActivityLog).where(
        ActivityLog.org_id == org_id,
        # Both created_at and dates should be UTC
        ActivityLog.created_at >= datetime.combine(start_date, time(0, 0, 0), tzinfo=UTC),
        ActivityLog.created_at < datetime.combine(end_date, time(0, 0, 0), tzinfo=UTC),
    )
    # ... rest of query
```

#### Scheduling Recommendations

Use these UTC times for scheduled report generation to avoid DST issues:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

# DAILY REPORTS: 02:00 UTC (recommended)
scheduler.add_job(
    generate_daily_reports,
    trigger="cron",
    hour=2,        # 02:00 UTC (universal, no DST changes)
    minute=0,
    timezone="UTC"  # Explicitly use UTC
)

# WEEKLY REPORTS: Monday 02:00 UTC (recommended)
scheduler.add_job(
    generate_weekly_reports,
    trigger="cron",
    day_of_week=0,  # Monday (0=Monday, 6=Sunday in APScheduler)
    hour=2,         # 02:00 UTC
    minute=0,
    timezone="UTC"
)

# MONTHLY REPORTS: 1st of month 02:00 UTC (recommended)
scheduler.add_job(
    generate_monthly_reports,
    trigger="cron",
    day=1,          # 1st of month
    hour=2,         # 02:00 UTC
    minute=0,
    timezone="UTC"
)
```

**Why 02:00 UTC?**
- Off-peak database load (before most offices open in major timezones)
- Far from DST transitions (typically March-April and October-November)
- Consistent run time (never shifts due to local DST)

#### Database Column Configuration

Ensure your database columns store UTC with timezone:

```python
from sqlalchemy import Column, DateTime
from datetime import datetime, UTC

class ActivityLog(Base):
    __tablename__ = "activity_logs"

    # CORRECT - stores timezone-aware UTC
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    # WRONG - loses timezone info, assumes local time
    # created_at = Column(DateTime(timezone=False), default=datetime.now, nullable=False)
```

Create migration if needed:

```bash
alembic revision --autogenerate -m "ensure_activity_logs_timezone_aware"
```

Migration content:
```python
def upgrade():
    # Ensure created_at column has timezone
    op.alter_column(
        'activity_logs',
        'created_at',
        type_=DateTime(timezone=True),
        existing_type=DateTime(timezone=False),
    )

def downgrade():
    op.alter_column(
        'activity_logs',
        'created_at',
        type_=DateTime(timezone=False),
        existing_type=DateTime(timezone=True),
    )
```

#### Common Mistakes to Avoid

**Mistake 1: Using local time for scheduling**
```python
# WRONG - 02:00 local time changes after DST
scheduler.add_job(generate_reports, trigger="cron", hour=2, minute=0)
```

**Fix: Always specify timezone=UTC**
```python
# CORRECT - 02:00 UTC is stable
scheduler.add_job(
    generate_reports,
    trigger="cron",
    hour=2,
    minute=0,
    timezone="UTC"
)
```

**Mistake 2: Storing reports without UTC clarity**
```python
# WRONG - unclear if this is local or UTC
report_data = {
    "generated_at": "2024-01-15T02:00:00",  # UTC? Local? Unknown
}
```

**Fix: Always include timezone in timestamps**
```python
# CORRECT - explicitly UTC
report_data = {
    "generated_at": datetime.now(UTC).isoformat(),  # 2024-01-15T02:00:00+00:00
    "timezone": "UTC"
}
```

**Mistake 3: Assuming database handles timezone conversion**
```python
# WRONG - relies on implicit timezone handling
end_date = datetime.now().date()  # Uses local time, not UTC
logs = select(ActivityLog).where(ActivityLog.created_at < end_date)
```

**Fix: Explicit UTC conversion**
```python
# CORRECT - explicit UTC
end_date = datetime.now(UTC).date()  # Explicitly UTC
logs = select(ActivityLog).where(ActivityLog.created_at < datetime.combine(
    end_date, time(0, 0, 0), tzinfo=UTC
))
```

#### Verification Checklist

Before deploying reports to production:

- [ ] All datetime operations use `datetime.now(UTC)`, never `datetime.now()`
- [ ] Database columns configured with `DateTime(timezone=True)`
- [ ] Scheduled jobs explicitly use `timezone="UTC"` parameter
- [ ] Report output includes `"timezone": "UTC"` in metadata
- [ ] Date range calculations use UTC consistently
- [ ] Test data covers DST transitions (March/October)
- [ ] Verified reports run correctly after DST change

### Optimize Queries with Indexes

```python
# Ensure indexes exist on Activity Logs table
from sqlalchemy import Index

# Add to model definition
class ActivityLog(Base):
    __table_args__ = (
        Index("ix_activity_log_org_created", "org_id", "created_at"),
        Index("ix_activity_log_action", "action"),
        Index("ix_activity_log_resource", "resource_type"),
    )
```

---

## Step 2: Format Report

### Report Format Comparison

| Format | File Size | Human-Readable | Machine-Readable | Best For |
|--------|-----------|----------------|------------------|----------|
| **PDF** | Large (100KB-5MB) | ✅ Excellent | ❌ Poor | Executive reports, printing |
| **CSV** | Medium (10KB-1MB) | ✅ Good | ✅ Excellent | Data analysis, Excel import |
| **JSON** | Small (5KB-500KB) | ❌ Poor | ✅ Excellent | API consumption, automation |

### When to Use Each Format

**PDF**
- ✅ Professional appearance
- ✅ Preserves formatting
- ✅ Can include charts/images
- ❌ Large file size
- ❌ Not parseable by machines
- **Use for:** Executive summaries, compliance reports, user-facing reports

**CSV**
- ✅ Universal compatibility (Excel, Google Sheets)
- ✅ Easy to analyze with pandas/SQL
- ✅ Moderate file size
- ❌ No formatting or charts
- ❌ Flat structure only (no nesting)
- **Use for:** Data exports, analysis, import to other systems

**JSON**
- ✅ Smallest file size
- ✅ Structured data (nested objects)
- ✅ Perfect for APIs
- ❌ Not human-friendly
- ❌ Requires parsing
- **Use for:** API responses, automation, programmatic access

---

### Format Option 1: CSV Export (Recommended for Simplicity)

**Best for**: Data imports, spreadsheet analysis, simplicity.

```python
import csv
import io
from datetime import date

async def generate_csv_report(
    data: dict,
    org_id: UUID
) -> str:
    """Generate CSV report from analytics data."""

    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)

    # Write header
    writer.writerow(["Activity Report"])
    writer.writerow(["Organization ID", str(org_id)])
    writer.writerow(["Period", data["period"]])
    writer.writerow(["Date Range", f"{data['start_date']} to {data['end_date']}"])
    writer.writerow([])

    # Write summary
    writer.writerow(["Summary Statistics"])
    writer.writerow(["Total Actions", data["total_actions"]])
    writer.writerow([])

    # Write action breakdown
    writer.writerow(["Actions by Type"])
    writer.writerow(["Action", "Count"])
    for action, count in data["actions_by_type"].items():
        writer.writerow([action, count])
    writer.writerow([])

    # Write resources created
    writer.writerow(["Resources Created"])
    writer.writerow(["Resource Type", "Count"])
    for resource, count in data["resources_created"].items():
        writer.writerow([resource, count])
    writer.writerow([])

    # Write top users
    writer.writerow(["Top Active Users"])
    writer.writerow(["Email", "Activity Count"])
    for user in data["top_active_users"]:
        writer.writerow([user["email"], user["activity_count"]])

    return csv_buffer.getvalue()
```

### Format Option 2: PDF Export

**Best for**: Professional reports, client delivery, printing.

**Installation**:
```bash
uv pip install reportlab
```

**Implementation**:

```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import io

async def generate_pdf_report(
    data: dict,
    org_id: UUID
) -> bytes:
    """Generate PDF report from analytics data."""

    # Create PDF buffer
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=30,
    )

    # Add title
    elements.append(Paragraph(f"Activity Report - {data['period'].title()}", title_style))
    elements.append(Spacer(1, 12))

    # Add metadata
    metadata_data = [
        ["Organization ID", str(org_id)],
        ["Period", data["period"]],
        ["Date Range", f"{data['start_date']} to {data['end_date']}"],
        ["Total Actions", str(data["total_actions"])],
    ]
    metadata_table = Table(metadata_data, colWidths=[200, 200])
    metadata_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(metadata_table)
    elements.append(Spacer(1, 20))

    # Add actions table
    elements.append(Paragraph("Actions by Type", styles['Heading2']))
    actions_data = [["Action", "Count"]] + [
        [action, str(count)]
        for action, count in data["actions_by_type"].items()
    ]
    actions_table = Table(actions_data, colWidths=[250, 100])
    actions_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(actions_table)
    elements.append(Spacer(1, 20))

    # Add top users
    elements.append(Paragraph("Top Active Users", styles['Heading2']))
    users_data = [["Email", "Activity Count"]] + [
        [user["email"], str(user["activity_count"])]
        for user in data["top_active_users"]
    ]
    users_table = Table(users_data, colWidths=[300, 100])
    users_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(users_table)

    # Build PDF
    doc.build(elements)
    return pdf_buffer.getvalue()
```

### Format Option 3: JSON (for API or webhooks)

**Best for**: Programmatic consumption, webhooks, dashboards.

```python
import json

async def generate_json_report(
    data: dict,
    org_id: UUID
) -> bytes:
    """Generate JSON report (returns bytes for consistency)."""
    report = {
        "type": "activity_report",
        "org_id": str(org_id),
        **data
    }
    json_str = json.dumps(report, indent=2)
    return json_str.encode("utf-8")  # Returns BYTES like PDF/CSV
```

---

## Step 3: Deliver Report

### Delivery Option 1: Email Attachment

**Best for**: User-requested reports, email delivery.

```python
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment
import base64

async def send_report_email(
    org_id: UUID,
    email: str,
    report_content: bytes,
    report_format: str = "pdf"
) -> None:
    """Send report as email attachment."""

    # Create email message
    message = Mail(
        from_email=settings.reports_from_email,
        to_emails=email,
        subject=f"Your Activity Report",
        html_content="<p>Your monthly activity report is attached.</p>"
    )

    # Add attachment
    from datetime import datetime, UTC
    filename = f"activity-report-{org_id}-{datetime.now(UTC).date()}.{report_format}"
    attachment = Attachment(
        file_content=base64.b64encode(report_content).decode(),
        file_type=f"application/{report_format}" if report_format == "pdf" else "text/csv",
        file_name=filename,
        disposition="attachment"
    )
    message.attachment = attachment

    # Send
    sg = SendGridAPIClient(os.environ.get("SENDGRID_API_KEY"))
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: sg.send(message)
    )
```

### Delivery Option 2: S3 Storage + Signed URL

**Best for**: Large reports, archival, download links.

```python
import aioboto3

async def store_report_s3(
    org_id: UUID,
    report_content: bytes,
    report_format: str = "pdf"
) -> str:
    """Store report in S3 and return signed URL."""
    from redact_api.core.config import settings

    from datetime import datetime, UTC
    key = f"reports/{org_id}/{datetime.now(UTC).date().isoformat()}/activity-report.{report_format}"

    session = aioboto3.Session()
    async with session.client("s3", region_name=settings.aws_region) as s3:
        # Upload report
        await s3.put_object(
            Bucket=settings.archive_bucket,
            Key=key,
            Body=report_content,
            ContentType="application/pdf" if report_format == "pdf" else "text/csv"
        )

        # Generate signed URL (valid for 7 days)
        signed_url = await s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.archive_bucket, "Key": key},
            ExpiresIn=7 * 24 * 3600  # 7 days
        )

    return signed_url
```

### Email Delivery with Retry

For reliable email delivery with automatic retry on transient failures:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sendgrid.helpers.errors import SendGridException
from http.client import HTTPException
import httpx

@retry(
    retry=retry_if_exception_type((SendGridException, HTTPException, httpx.RequestError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60)
)
async def send_report_email(
    org_id: UUID,
    report_data: bytes,
    filename: str
) -> None:
    """Send report via email with retry on transient failures."""
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType
    import base64

    message = Mail(
        from_email=settings.reports_from_email,
        to_emails=await get_org_admin_emails(org_id),
        subject=f"Monthly Activity Report - {datetime.now(UTC).strftime('%B %Y')}",
        html_content="<p>Please find your activity report attached.</p>"
    )

    # Attach report
    encoded_file = base64.b64encode(report_data).decode()
    attachment = Attachment(
        FileContent(encoded_file),
        FileName(filename),
        FileType("application/pdf")
    )
    message.attachment = attachment

    sg = SendGridAPIClient(settings.sendgrid_api_key)

    # Properly await executor
    response = await asyncio.get_event_loop().run_in_executor(
        None, sg.send, message
    )

    # Check for rate limiting
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 60))
        logger.warning(
            "sendgrid_rate_limited",
            extra={"retry_after": retry_after}
        )
        raise SendGridException("Rate limited")  # Will trigger retry

    response.raise_for_status()
```

### Delivery Option 3: Webhook with Signature

**Best for**: Integration with external systems, event-driven workflows.

```python
import hmac
import hashlib
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

def generate_webhook_signature(payload: bytes, secret: str) -> str:
    """Generate HMAC signature for webhook verification."""
    return hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

@retry(
    retry=retry_if_exception_type(httpx.RequestError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
async def send_report_webhook(
    org_id: UUID,
    report_data: bytes,
    filename: str
) -> None:
    """Send report to webhook with retry and signature."""
    from redact_api.core.http_client import http_client

    webhook_url = await get_org_webhook_url(org_id)
    webhook_secret = settings.webhook_secret

    # Generate signature for security
    signature = generate_webhook_signature(report_data, webhook_secret)

    async with http_client(timeout=30.0) as client:
        response = await client.post(
            webhook_url,
            files={"report": (filename, report_data, "application/pdf")},
            headers={
                "X-Webhook-Signature": signature,
                "X-Organization-ID": str(org_id)
            },
            timeout=60.0  # Longer timeout for large files
        )
        response.raise_for_status()
```

---

## Step 4: Email Templates

### Template Storage Options

#### Option 1: File-Based Templates (Jinja2)

**Best for**: Static templates, version control, templating logic.

**Installation**:
```bash
uv pip install jinja2>=3.1.0
```

**Setup**: Create `templates/` directory:
```
templates/
├── report_email.html
└── report_summary.txt
```

**Example Template** (`templates/report_email.html`):
```html
<!DOCTYPE html>
<html>
<head>
    <title>Activity Report - [[ period | title ]]</title>
    <style>
        body { font-family: Arial, sans-serif; }
        .header { background-color: #f5f5f5; padding: 20px; }
        .metric { padding: 10px; border-bottom: 1px solid #ddd; }
        .metric-value { font-weight: bold; color: #0066cc; }
    </style>
</head>
<body>
    <div class="header">
        <h1>[[ org_name ]] - Activity Report</h1>
        <p>Period: <strong>[[ period | title ]]</strong></p>
        <p>Date Range: [[ start_date ]] to [[ end_date ]]</p>
    </div>

    <div class="content">
        <h2>Summary</h2>
        <div class="metric">
            <span>Total Actions:</span>
            <span class="metric-value">[[ total_actions ]]</span>
        </div>

        <h2>Actions by Type</h2>
        For each action and count in actions_by_type:
        <div class="metric">
            <span>[[ action ]]:</span>
            <span class="metric-value">[[ count ]]</span>
        </div>

        <h2>Top Active Users</h2>
        <table style="width:100%; border-collapse: collapse;">
            <thead>
                <tr style="background-color: #f0f0f0;">
                    <th style="padding: 10px; text-align: left;">Email</th>
                    <th style="padding: 10px; text-align: left;">Activity Count</th>
                </tr>
            </thead>
            <tbody>
                For each user in top_active_users:
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #ddd;">[[ user.email ]]</td>
                    <td style="padding: 10px; border-bottom: 1px solid #ddd;">[[ user.activity_count ]]</td>
                </tr>
            </tbody>
        </table>
    </div>

    <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px;">
        <p>This is an automated report. Please do not reply to this email.</p>
    </div>
</body>
</html>
```

**Load and Render Template**:
```python
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

async def send_report_email_with_template(
    org_id: UUID,
    admin_email: str,
    report_data: dict,
    org_name: str
) -> None:
    """Send report email using Jinja2 template."""
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    # Load template
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("report_email.html")

    # Render with data
    html_content = template.render(
        org_name=org_name,
        period=report_data["period"],
        start_date=report_data["start_date"],
        end_date=report_data["end_date"],
        total_actions=report_data["total_actions"],
        actions_by_type=report_data["actions_by_type"],
        top_active_users=report_data["top_active_users"]
    )

    # Send email
    message = Mail(
        from_email=settings.reports_from_email,
        to_emails=admin_email,
        subject=f"Your {report_data['period'].title()} Activity Report",
        html_content=html_content
    )

    sg = SendGridAPIClient(settings.sendgrid_api_key)
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: sg.send(message)
    )

    logger.info(
        "report_email_sent",
        extra={"org_id": str(org_id), "template": "report_email.html"}
    )
```

#### Option 2: Database-Stored Templates

**Best for**: User-editable templates, multi-tenant customization.

**Schema**:
```python
from sqlalchemy import Column, String, DateTime, Text
from redact_api.models import Base

class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id = Column(UUID, primary_key=True)
    org_id = Column(UUID, ForeignKey("organizations.id"))
    name = Column(String(100), nullable=False)  # "report_email", "welcome_email"
    subject = Column(String(255), nullable=False)
    html_content = Column(Text, nullable=False)  # Jinja2 template
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
```

**Load and Render**:
```python
async def send_report_email_from_db(
    session: AsyncSession,
    org_id: UUID,
    admin_email: str,
    report_data: dict,
    org_name: str
) -> None:
    """Send report email using template stored in database."""
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    from jinja2 import Template

    # Load template from database
    stmt = select(EmailTemplate).where(
        EmailTemplate.org_id == org_id,
        EmailTemplate.name == "report_email"
    )
    result = await session.execute(stmt)
    db_template = result.scalar_one_or_none()

    if not db_template:
        # Fall back to default template
        logger.warning("Custom template not found, using default", extra={"org_id": str(org_id)})
        db_template = await get_default_template(session)

    # Render Jinja2 template
    template = Template(db_template.html_content)
    html_content = template.render(
        org_name=org_name,
        period=report_data["period"],
        start_date=report_data["start_date"],
        end_date=report_data["end_date"],
        total_actions=report_data["total_actions"],
        actions_by_type=report_data["actions_by_type"],
        top_active_users=report_data["top_active_users"]
    )

    # Render subject
    subject_template = Template(db_template.subject)
    subject = subject_template.render(period=report_data["period"])

    # Send email
    message = Mail(
        from_email=settings.reports_from_email,
        to_emails=admin_email,
        subject=subject,
        html_content=html_content
    )

    sg = SendGridAPIClient(settings.sendgrid_api_key)
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: sg.send(message)
    )

    logger.info(
        "report_email_sent",
        extra={"org_id": str(org_id), "template_id": str(db_template.id)}
    )
```

---

## Complete Implementation

### Using All Pieces Together

```python
async def generate_activity_report_task(
    session: AsyncSession,
    org_id: UUID,
    period: str
) -> None:
    """Generate activity report (session injected)."""
    try:
        logger.info(
            "generating_activity_report",
            extra={"org_id": str(org_id), "period": period},
        )

        # 1. Get organization and user info
        org_stmt = select(Organization).where(Organization.id == org_id)
        org_result = await session.execute(org_stmt)
        org = org_result.scalar_one_or_none()

        if not org:
            logger.warning("Organization not found", extra={"org_id": str(org_id)})
            return

        # 2. Query analytics data
        report_data = await get_report_data(session, org_id, period)

        # 3. Generate report in PDF format
        pdf_content = await generate_pdf_report(report_data, org_id)

        # 4. Deliver via email to org owner
        admin_stmt = select(User).where(
            User.org_id == org_id,
            User.role == "admin"
        ).limit(1)
        admin_result = await session.execute(admin_stmt)
        admin = admin_result.scalar_one_or_none()

        if admin:
            await send_report_email(org_id, admin.email, pdf_content, "pdf")

        # 5. Store copy in S3 for long-term access
        signed_url = await store_report_s3(org_id, pdf_content, "pdf")
        logger.info(
            "report_stored_s3",
            extra={"org_id": str(org_id), "signed_url": signed_url},
        )

        logger.info(
            "activity_report_generated",
            extra={"org_id": str(org_id), "period": period},
        )

    except Exception:
        logger.exception(
            "Failed to generate activity report",
            extra={"org_id": str(org_id), "period": period},
        )
```

---

## Scheduling Report Generation

### Scheduling Strategy Comparison

| Solution | Setup Complexity | Scalability | Dependencies | Best For |
|----------|------------------|-------------|--------------|----------|
| **APScheduler** | Low | Single machine | None | Small apps, simple schedules |
| **Celery** | High | Distributed | Redis/RabbitMQ | Microservices, high volume |
| **User-Requested** | Low | Scales with API | None | On-demand reports |

### When to Use Each

**APScheduler** (Recommended for <1000 reports/day)
- ✅ Simple setup (no message broker)
- ✅ Good for single-server deployments
- ✅ Built-in cron syntax
- ❌ Not distributed (runs on one machine)
- ❌ Lost jobs if server restarts

**Celery** (Recommended for >1000 reports/day or distributed systems)
- ✅ Distributed (run workers on multiple machines)
- ✅ Job persistence (survives restarts)
- ✅ Priority queues and rate limiting
- ❌ Requires Redis/RabbitMQ setup
- ❌ More complex configuration

**User-Requested** (Recommended for ad-hoc reports)
- ✅ No scheduling needed
- ✅ Scales with API
- ✅ Immediate feedback to user
- ❌ Requires API endpoint
- ❌ Can't run on schedule automatically

### Migration Path

1. **Start with User-Requested** (simplest)
2. **Add APScheduler** for basic automation (1-10 orgs)
3. **Migrate to Celery** when scaling (100+ orgs)

---

### Option 1: APScheduler (Simple, Built-in)

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

# Schedule monthly report generation
scheduler.add_job(
    generate_monthly_reports,
    trigger="cron",
    day=1,  # First day of month
    hour=2,  # 2 AM UTC
    minute=0
)

async def generate_monthly_reports():
    """Generate reports for all organizations."""
    from redact_api.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        orgs_stmt = select(Organization)
        orgs_result = await session.execute(orgs_stmt)
        orgs = orgs_result.scalars().all()

        for org in orgs:
            asyncio.create_task(
                generate_activity_report_task(session, org.id, "monthly")
            )
```

### Option 2: Celery (Distributed, Production-Grade)

```python
from celery import Celery
from celery.schedules import crontab

celery_app = Celery(
    "redact_api",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1"
)

# Configure celery beat schedule
celery_app.conf.beat_schedule = {
    "generate-monthly-reports": {
        "task": "redact_api.tasks.generate_monthly_reports",
        "schedule": crontab(day_of_month=1, hour=2, minute=0),
    },
    "generate-weekly-reports": {
        "task": "redact_api.tasks.generate_weekly_reports",
        "schedule": crontab(day_of_week=0, hour=8, minute=0),  # Sunday 8 AM
    },
}

@celery_app.task(name="generate_activity_report")
def generate_activity_report_celery_task(org_id: str, report_type: str):
    """Sync wrapper for Celery - calls async function."""
    from redact_api.core.database import AsyncSessionLocal
    from uuid import UUID

    async def run():
        async with AsyncSessionLocal() as session:
            await generate_activity_report_task(
                session=session,
                org_id=UUID(org_id),
                period=report_type
            )

    asyncio.run(run())

# Usage:
# generate_activity_report_celery_task.delay(str(org_id), "monthly")
```

### Option 3: User-Requested Reports

```python
from redact_api.api.deps import CurrentUserDep

@router.post("/reports/generate")
async def request_report(
    period: str,
    format: str = "pdf",
    current_user: CurrentUserDep = None
):
    """User-requested report generation."""
    from redact_api.core.database import AsyncSessionLocal

    if format not in ["pdf", "csv", "json"]:
        raise HTTPException(status_code=400, detail="Invalid format")

    if period not in ["daily", "weekly", "monthly", "quarterly"]:
        raise HTTPException(status_code=400, detail="Invalid period")

    # Queue report generation
    async def generate_report():
        async with AsyncSessionLocal() as session:
            await generate_activity_report_task(session, current_user.org_id, period)

    asyncio.create_task(generate_report())

    return {"message": "Report generation queued. You'll receive it via email shortly."}
```

---

## Test Fixture Setup

Add these fixtures to your `conftest.py`:

```python
# conftest.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

@pytest.fixture
async def test_db():
    """Async database session for testing."""
    engine = create_async_engine(
        "postgresql+asyncpg://user:pass@localhost/test_db",
        echo=True
    )

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session
        await session.rollback()  # Rollback after each test
```

---

## Testing Report Generation

### Unit Test: Mock Data and PDF Generation

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import UUID

@pytest.mark.asyncio
async def test_generate_pdf_report():
    """Test PDF report generation."""
    org_id = UUID("12345678-1234-5678-1234-567812345678")

    # Mock report data
    report_data = {
        "period": "monthly",
        "start_date": "2023-01-01",
        "end_date": "2023-01-31",
        "total_actions": 150,
        "actions_by_type": {
            "CREATE": 50,
            "UPDATE": 80,
            "DELETE": 20,
        },
        "resources_created": {
            "User": 10,
            "Document": 25,
        },
        "top_active_users": [
            {"email": "user1@example.com", "activity_count": 45},
        ],
    }

    # Generate PDF
    pdf_content = await generate_pdf_report(report_data, org_id)

    # Verify PDF content
    assert pdf_content.startswith(b"%PDF")  # PDF header
    assert b"Activity Report" in pdf_content
    assert b"monthly" in pdf_content
```

### Integration Test: Full Report Pipeline

```python
@pytest.mark.asyncio
async def test_generate_activity_report_full_pipeline(test_db):
    """Test complete report generation with database."""
    from datetime import datetime, timedelta, UTC

    org_id = UUID("12345678-1234-5678-1234-567812345678")

    # Create test data
    org = Organization(id=org_id, name="Test Org")
    user = User(id=UUID(int=1), org_id=org_id, email="admin@example.com", role="admin")
    logs = [
        ActivityLog(
            id=UUID(int=i),
            org_id=org_id,
            user_id=user.id,
            action="CREATE",
            resource_type="Document",
            resource_id=UUID(int=100+i),
            created_at=datetime.now(UTC) - timedelta(days=5)
        )
        for i in range(10)
    ]

    test_db.add(org)
    test_db.add(user)
    test_db.add_all(logs)
    await test_db.commit()

    # Generate report
    with patch("send_report_email") as mock_send:
        await generate_activity_report_task(org_id, "monthly")
        mock_send.assert_called_once()
```

### Test Email Delivery

```python
@pytest.mark.asyncio
async def test_send_report_email(httpx_mock):
    """Test report email delivery."""
    org_id = UUID("12345678-1234-5678-1234-567812345678")
    email = "admin@example.com"
    report_content = b"%PDF fake pdf content"

    # Mock SendGrid API
    httpx_mock.add_response(
        method="POST",
        url="https://api.sendgrid.com/v3/mail/send",
        status_code=202
    )

    # Send email
    await send_report_email(org_id, email, report_content, "pdf")

    # Verify request
    request = httpx_mock.get_request()
    assert "mail/send" in str(request.url)
```

---

## Configuration Checklist

Before going to production:

- [ ] Report format chosen (PDF recommended for UX)
- [ ] Query performance optimized (indexes created)
- [ ] Delivery method selected (email, S3, webhook)
- [ ] Email/S3/webhook credentials configured
- [ ] Scheduling configured (APScheduler or Celery)
- [ ] Report data verified for accuracy
- [ ] PDF generated successfully with reportlab
- [ ] Email templates created (subject, body, signature)
- [ ] Error handling and retry logic implemented
- [ ] Logging configured for troubleshooting
- [ ] Unit tests passing (mock data)
- [ ] Integration tests passing (real database)
- [ ] Report delivery verified (test email received)
- [ ] Monitoring/alerting configured for failures

---

## Common Mistakes to Avoid

### ❌ Mistake 1: Blocking Report Generation

```python
# BAD - endpoint waits 10+ seconds for PDF generation
@router.post("/reports/generate")
async def request_report(org_id: UUID):
    pdf = await generate_pdf_report(...)  # BLOCKS
    return {"file": pdf}
```

**Fix**: Queue report and return immediately:
```python
# GOOD - returns immediately, generates in background
@router.post("/reports/generate")
async def request_report(org_id: UUID):
    asyncio.create_task(generate_activity_report_task(org_id, "monthly"))
    return {"message": "Report generation queued"}
```

### ❌ Mistake 2: Not Handling Missing Data

```python
# BAD - crashes if organization not found
org = await session.get(Organization, org_id)  # Returns None
await generate_report_for_org(org)  # Crashes with AttributeError
```

**Fix**: Check for None:
```python
# GOOD - handles missing org gracefully
org = await session.get(Organization, org_id)
if not org:
    logger.warning("Org not found", extra={"org_id": org_id})
    return
```

### ❌ Mistake 3: Inefficient Database Queries

```python
# BAD - N+1 query problem: one query per user
for user in users:
    user_activity = select(func.count(ActivityLog.id)).where(...)
    # Executes query for each user
```

**Fix**: Join in single query:
```python
# GOOD - single query with JOIN
stmt = select(
    User.email,
    func.count(ActivityLog.id).label("count")
).select_from(ActivityLog).join(User).group_by(User.id)
```

### ❌ Mistake 4: Hardcoded Email Templates

```python
# BAD - email content hardcoded, hard to change
message = Mail(
    subject="Your monthly report",
    html_content="Here's your report..."
)
```

**Fix**: Use templates:
```python
# GOOD - templates in database or files
from jinja2 import Template

with open("templates/report_email.html") as f:
    template = Template(f.read())
    html_content = template.render(
        org_name=org.name,
        period="monthly"
    )
```

### ❌ Mistake 5: No Error Recovery

```python
# BAD - if email fails, nothing logged or retried
try:
    await send_report_email(...)
except Exception:
    pass  # Silently fails
```

**Fix**: Log and retry:
```python
# GOOD - logs error and retry with backoff
@retry(stop=stop_after_attempt(3), wait=wait_exponential())
async def send_report_with_retry(org_id, email, content):
    try:
        await send_report_email(org_id, email, content)
    except Exception:
        logger.exception("Report send failed", extra={"org_id": org_id})
        raise  # Trigger retry
```

---

## Summary

To implement report generation:

1. **Query analytics** using optimized SQL (add indexes)
2. **Choose format**: PDF (best UX), CSV (spreadsheets), or JSON (APIs)
3. **Choose delivery**: Email (direct), S3 (archival), Webhook (integration)
4. **Schedule generation**: Daily, weekly, or monthly
5. **Add error handling** with logging and retries
6. **Test thoroughly** with real and mock data
7. **Monitor task execution** and alert on failures

Choose **PDF email delivery** if unsure - it's the most professional and user-friendly option.

---

## Timezone Handling

Reports must respect organizational timezones:

### Timezone-Aware Report Generation

```python
from datetime import datetime, timezone, timedelta, UTC
from zoneinfo import ZoneInfo

async def get_report_data_with_timezone(
    session: AsyncSession,
    org_id: UUID,
    period: str,
    org_timezone: str = "UTC"  # e.g., "America/New_York"
) -> dict:
    """Query analytics data respecting organization timezone."""

    # Get organization's timezone
    org = await session.get(Organization, org_id)
    tz = ZoneInfo(org_timezone if org else "UTC")

    # Calculate date range in org timezone
    now_in_tz = datetime.now(tz)
    end_date = now_in_tz.date()

    if period == "daily":
        start_date = end_date - timedelta(days=1)
    elif period == "weekly":
        start_date = end_date - timedelta(weeks=1)
    elif period == "monthly":
        start_date = end_date - timedelta(days=30)
    else:
        raise ValueError(f"Unknown period: {period}")

    # Convert back to UTC for database query (assuming logs stored in UTC)
    start_utc = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=tz).astimezone(UTC)
    end_utc = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=tz).astimezone(UTC)

    # Query with UTC times
    stmt = select(ActivityLog).where(
        ActivityLog.org_id == org_id,
        ActivityLog.created_at >= start_utc,
        ActivityLog.created_at < end_utc
    )

    result = await session.execute(stmt)
    logs = result.scalars().all()

    # Convert log times to org timezone for display
    logs_in_tz = []
    for log in logs:
        log_dict = log.to_dict()
        # Convert created_at from UTC to org timezone
        log_dict["created_at_local"] = log.created_at.astimezone(tz).isoformat()
        logs_in_tz.append(log_dict)

    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "timezone": org_timezone,
        "logs": logs_in_tz
    }
```

### Recommended Report Run Times

Schedule reports to generate at optimal times for your users:

```python
# Configuration for per-timezone report generation
REPORT_GENERATION_SCHEDULE = {
    "America/New_York": {"hour": 6, "minute": 0},      # 6 AM ET
    "Europe/London": {"hour": 7, "minute": 0},         # 7 AM GMT
    "Asia/Tokyo": {"hour": 8, "minute": 0},            # 8 AM JST
    "Australia/Sydney": {"hour": 9, "minute": 0},      # 9 AM AEDT
}

async def generate_reports_by_timezone() -> None:
    """Generate reports at optimal local times per organization."""
    from redact_api.core.database import AsyncSessionLocal
    from zoneinfo import ZoneInfo

    async with AsyncSessionLocal() as session:
        # Get all organizations with their timezones
        stmt = select(Organization).where(Organization.timezone != None)
        result = await session.execute(stmt)
        orgs = result.scalars().all()

        now_utc = datetime.now(UTC)

        for org in orgs:
            # Check if it's time to generate report for this org's timezone
            tz = ZoneInfo(org.timezone)
            now_in_tz = now_utc.astimezone(tz)

            schedule = REPORT_GENERATION_SCHEDULE.get(org.timezone, {})
            target_hour = schedule.get("hour", 6)
            target_minute = schedule.get("minute", 0)

            # If within 1-minute window, generate report
            if now_in_tz.hour == target_hour and now_in_tz.minute == target_minute:
                asyncio.create_task(
                    generate_activity_report_task(org.id, "daily")
                )
```

---

## AWS Credentials Validation

Validate S3 credentials before attempting archival:

```python
async def validate_aws_credentials() -> bool:
    """Verify AWS credentials are valid before operations."""
    import aioboto3
    from botocore.exceptions import ClientError
    from redact_api.core.config import settings

    try:
        session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region
        )

        async with session.client("s3") as s3:
            # Try to list bucket (requires permissions)
            await s3.list_objects_v2(
                Bucket=settings.archive_bucket,
                MaxKeys=1
            )

        logger.info(
            "aws_credentials_valid",
            extra={"bucket": settings.archive_bucket}
        )
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "NoSuchBucket":
            logger.error("S3 bucket does not exist", extra={"bucket": settings.archive_bucket})
        elif error_code == "AccessDenied":
            logger.error("AWS credentials lack S3 permissions", extra={"bucket": settings.archive_bucket})
        else:
            logger.error("AWS credentials invalid", extra={"error": error_code})
        return False

    except Exception:
        logger.exception("Failed to validate AWS credentials")
        return False
```

---

## PDF Generation with Null Checks

Generate PDFs safely with proper null checking:

```python
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

async def generate_pdf_report_safe(
    org_id: UUID,
    report_data: dict
) -> bytes:
    """Generate PDF with null checks for safe rendering."""
    from io import BytesIO

    # Validate required fields
    if not report_data:
        logger.error("Empty report data", extra={"org_id": str(org_id)})
        raise ValueError("Report data cannot be empty")

    if not report_data.get("org_name"):
        logger.error("Missing org_name in report data", extra={"org_id": str(org_id)})
        raise ValueError("Organization name required for PDF generation")

    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    # Add title
    org_name = report_data.get("org_name") or "Unknown Organization"
    title = Paragraph(f"<b>Activity Report - {org_name}</b>", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 12))

    # Add summary section
    period = report_data.get("period", "Unknown").title()
    start_date = report_data.get("start_date") or "N/A"
    end_date = report_data.get("end_date") or "N/A"

    summary_data = [
        ["Period", period],
        ["Start Date", start_date],
        ["End Date", end_date],
        ["Total Actions", str(report_data.get("total_actions", 0))],
    ]

    summary_table = Table(summary_data, colWidths=[200, 200])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))

    elements.append(summary_table)
    elements.append(Spacer(1, 12))

    # Add actions by type (safe iteration)
    actions_by_type = report_data.get("actions_by_type") or {}
    if actions_by_type:
        elements.append(Paragraph("<b>Actions by Type</b>", styles['Heading2']))

        actions_data = [["Action", "Count"]]
        for action, count in actions_by_type.items():
            actions_data.append([str(action), str(count)])

        actions_table = Table(actions_data, colWidths=[200, 200])
        actions_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))

        elements.append(actions_table)

    # Build PDF
    try:
        doc.build(elements)
        pdf_content = pdf_buffer.getvalue()

        if not pdf_content:
            logger.error("PDF generation produced empty content", extra={"org_id": str(org_id)})
            raise ValueError("PDF generation failed - empty output")

        logger.info(
            "pdf_generated",
            extra={"org_id": str(org_id), "size_bytes": len(pdf_content)}
        )

        return pdf_content

    except Exception:
        logger.exception("PDF generation failed", extra={"org_id": str(org_id)})
        raise
```

---

## Monitoring & Observability

Track report generation metrics and observability:

```python
from prometheus_client import Counter, Histogram, Gauge

# Metrics
reports_generated_total = Counter(
    "reports_generated_total",
    "Total reports generated",
    ["org_id", "format"]
)

reports_delivery_duration_seconds = Histogram(
    "reports_delivery_duration_seconds",
    "Time to deliver report",
    ["delivery_method"]  # email, s3, webhook
)

reports_failed_total = Counter(
    "reports_failed_total",
    "Total report generation failures",
    ["org_id", "error_type"]
)

reports_queue_size = Gauge(
    "reports_queue_size",
    "Current report generation queue size"
)

async def generate_activity_report_with_observability(
    session: AsyncSession,
    org_id: UUID,
    period: str,
    format: str = "pdf"
) -> None:
    """Generate report with comprehensive observability."""
    import time

    start_time = time.time()

    try:
        logger.info(
            "report_generation_started",
            extra={"org_id": str(org_id), "period": period, "format": format}
        )

        # Generate report
        report_data = await get_report_data(session, org_id, period)

        if format == "pdf":
            report_content = await generate_pdf_report(report_data, org_id)
        elif format == "csv":
            report_content = await generate_csv_report(report_data)
        else:
            report_content = await generate_json_report(report_data)

        # Record success
        reports_generated_total.labels(org_id=str(org_id), format=format).inc()

        # Deliver report
        delivery_start = time.time()
        await send_report_email(org_id, "admin@example.com", report_content, format)
        delivery_duration = time.time() - delivery_start

        reports_delivery_duration_seconds.labels(delivery_method="email").observe(delivery_duration)

        logger.info(
            "report_generation_completed",
            extra={
                "org_id": str(org_id),
                "period": period,
                "format": format,
                "generation_time_seconds": time.time() - start_time,
                "delivery_time_seconds": delivery_duration,
                "report_size_bytes": len(report_content)
            }
        )

    except Exception as e:
        reports_failed_total.labels(
            org_id=str(org_id),
            error_type=type(e).__name__
        ).inc()

        logger.exception(
            "report_generation_failed",
            extra={
                "org_id": str(org_id),
                "period": period,
                "error": str(e)
            }
        )
        raise
```
