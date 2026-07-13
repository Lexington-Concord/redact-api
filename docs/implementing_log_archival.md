# Implementing Log Archival

## Overview

The `archive_old_activity_logs_task()` in `redact_api/core/background_tasks.py` is currently a **placeholder** that logs success but doesn't archive anything. This guide shows how to implement real log archival to manage database growth.

**Current Placeholder Behavior**:
```python
await asyncio.sleep(0.1)  # Placeholder - no archival happens
logger.info("activity_logs_archived", extra={...})  # Misleading log
```

**Problem**: Activity logs accumulate indefinitely, causing:
- Database bloat (poor query performance)
- High storage costs
- Compliance issues (data retention violations)
- Backup/restore delays

---

## What You Need to Implement

Replace the placeholder function with actual archival logic:

```python
async def archive_old_activity_logs_task(org_id: UUID, days_older_than: int) -> None:
    """Archive activity logs older than specified days."""
    try:
        logger.info(
            "archiving_old_activity_logs",
            extra={"org_id": str(org_id), "days_older_than": days_older_than},
        )

        # TODO: Replace asyncio.sleep with actual archival implementation
        # Your archival logic here

        logger.info("activity_logs_archived", extra={"org_id": str(org_id)})
    except Exception:
        logger.exception("Failed to archive activity logs", extra={"org_id": str(org_id)})
```

---

## Core: Database Query Pattern

All archival strategies start with selecting old logs. Here's the pattern:

```python
from datetime import datetime, timedelta, UTC
from sqlalchemy import select

async def get_old_activity_logs(
    session: AsyncSession,
    org_id: UUID,
    days_older_than: int
) -> list[ActivityLog]:
    """Get activity logs older than specified days."""
    cutoff_date = datetime.now(UTC) - timedelta(days=days_older_than)

    stmt = select(ActivityLog).where(
        ActivityLog.org_id == org_id,
        ActivityLog.created_at < cutoff_date
    )

    result = await session.execute(stmt)
    return result.scalars().all()
```

### Batch Processing (for large datasets)

Don't load all old logs into memory - process in chunks:

```python
from sqlalchemy import select

async def process_old_logs_in_batches(
    session: AsyncSession,
    org_id: UUID,
    days_older_than: int,
    batch_size: int = 1000
):
    """Process old logs in batches to avoid memory issues."""
    from datetime import datetime, timedelta, UTC
    cutoff_date = datetime.now(UTC) - timedelta(days=days_older_than)
    offset = 0

    while True:
        stmt = select(ActivityLog).where(
            ActivityLog.org_id == org_id,
            ActivityLog.created_at < cutoff_date
        ).offset(offset).limit(batch_size)

        result = await session.execute(stmt)
        batch = result.scalars().all()

        if not batch:
            break  # No more logs to process

        # Process this batch
        yield batch
        offset += batch_size
```

### Avoiding Timeouts on Large Datasets

Use date ranges to prevent scanning huge indexes:

```python
async def process_logs_by_date_range(
    session: AsyncSession,
    org_id: UUID,
    from_date: datetime,
    to_date: datetime,
    batch_size: int = 1000
):
    """Process logs by date range to avoid timeout."""
    current_date = from_date

    while current_date < to_date:
        next_date = current_date + timedelta(days=1)  # Process 1 day at a time

        stmt = select(ActivityLog).where(
            ActivityLog.org_id == org_id,
            ActivityLog.created_at >= current_date,
            ActivityLog.created_at < next_date
        ).limit(batch_size)

        result = await session.execute(stmt)
        batch = result.scalars().all()

        if batch:
            yield batch

        current_date = next_date
```

---

## Database Index Requirements

For efficient archival queries, create indexes on frequently queried columns:

### Required Indexes

```python
# alembic/versions/XXXXXX_add_activity_log_indexes.py

from alembic import op

def upgrade():
    # Composite index for archival queries (org_id + created_at)
    op.create_index(
        'ix_activity_logs_org_created',
        'activity_logs',
        ['org_id', 'created_at'],
        unique=False
    )

    # Index for org lookups
    op.create_index(
        'ix_activity_logs_org_id',
        'activity_logs',
        ['org_id'],
        unique=False
    )

def downgrade():
    op.drop_index('ix_activity_logs_org_created')
    op.drop_index('ix_activity_logs_org_id')
```

### Why These Indexes?

- **`(org_id, created_at)`**: Covers the WHERE clause in archival queries (`org_id = ? AND created_at < ?`). Database can use index-only scan.
- **`org_id`**: Supports queries that only filter by organization.

### Query Performance Impact

Without indexes:
- 1M logs: ~5-10 seconds for archival query (full table scan)

With indexes:
- 1M logs: ~100-500ms for archival query (index scan)

**Recommendation:** Create indexes BEFORE archival, especially on tables with >100K rows.

---

## Archival Strategy Comparison

| Strategy | Query Latency | Cost/GB/Month | Compliance | Recovery Time | Best For |
|----------|---------------|---------------|------------|---------------|----------|
| **S3 Storage** | 100-500ms | $0.023 | Excellent | Minutes | Long-term retention, infrequent access |
| **Cold Storage Table** | 1-10ms | $0.10-0.30 (DB) | Good | Immediate | Compliance queries, frequent access |
| **Deletion** | N/A | $0 | Limited | Never | Non-critical logs, cost optimization |

### Detailed Comparison

**S3 Storage**
- ✅ Cheapest for large volumes ($0.023/GB vs $0.30/GB database)
- ✅ Unlimited scalability
- ✅ Built-in versioning and lifecycle policies
- ✅ Excellent for compliance (WORM, audit logs)
- ❌ Slower queries (100ms+ network latency)
- ❌ Requires S3 credentials and setup
- ❌ Data retrieval costs ($0.09/GB)

**Cold Storage Table**
- ✅ Fast queries (1-10ms, same database)
- ✅ No external dependencies
- ✅ Can JOIN with active tables
- ❌ More expensive storage ($0.10-0.30/GB depending on DB)
- ❌ Adds load to database
- ❌ Limited by database capacity

**Deletion Strategy**
- ✅ Free (no storage cost)
- ✅ Simplest implementation
- ❌ Irreversible data loss
- ❌ May violate compliance requirements (GDPR, HIPAA)
- ❌ No forensic capability

### Use Case Recommendations

| Use Case | Recommended Strategy | Reason |
|----------|---------------------|--------|
| Compliance audit logs | S3 Storage | Long retention (7+ years), immutable |
| Activity logs (recent queries needed) | Cold Storage Table | Fast access for user queries |
| Debug logs | Deletion after 30 days | Not needed long-term, cost optimization |
| Financial transactions | S3 + Cold Storage | Compliance + fast access |
| Anonymous analytics | Deletion after aggregation | Privacy, no PII retention needed |

### Cost Example (100GB of logs)

- **S3 Storage**: $2.30/month storage + $9 retrieval (one-time)
- **Cold Storage (PostgreSQL)**: $10-30/month storage
- **Deletion**: $0

**Recommendation**: Use S3 for logs older than 90 days, cold storage for 30-90 days, active table for <30 days.

---

## Failure Recovery Patterns

When archival tasks are interrupted (network failures, server restarts, timeouts), you need a way to resume from where you left off. This section covers checkpointing strategies for resilient archival.

### Checkpointing Pattern: Resume Interrupted Archival

**Problem**: If archival fails after processing 50,000 logs out of 100,000, restarting from log 1 wastes time and may cause rate limiting.

**Solution**: Track progress with checkpoints, resume from the last processed record.

#### Step 1: Create Checkpoint Model

```python
from sqlalchemy import Column, DateTime, String, UUID as SQLAlchemy_UUID, Integer, Index
from sqlalchemy.orm import declarative_base
from datetime import datetime, UTC
from uuid import uuid4

Base = declarative_base()

class ArchivalCheckpoint(Base):
    """Track progress of archival operations for resumption after interruption."""
    __tablename__ = "archival_checkpoints"

    id = Column(SQLAlchemy_UUID, primary_key=True, default=uuid4)
    org_id = Column(SQLAlchemy_UUID, nullable=False)
    archival_type = Column(String(50), nullable=False)  # "s3", "cold_storage", "deletion"
    last_processed_id = Column(SQLAlchemy_UUID, nullable=True)  # Last log ID processed
    logs_processed = Column(Integer, default=0)
    logs_failed = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    last_checkpoint_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, default="in_progress")  # "in_progress", "completed", "failed"
    error_message = Column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_checkpoints_org_status", "org_id", "status"),
    )
```

Create migration:
```bash
alembic revision --autogenerate -m "add_archival_checkpoints_table"
alembic upgrade head
```

#### Step 2: Checkpoint Creation and Resumption Logic

```python
from sqlalchemy import select, update, and_
from datetime import datetime, timedelta, UTC

async def get_or_create_checkpoint(
    session: AsyncSession,
    org_id: UUID,
    archival_type: str = "s3"
) -> ArchivalCheckpoint:
    """Get existing checkpoint or create new one."""
    # Check for in-progress checkpoint
    stmt = select(ArchivalCheckpoint).where(
        ArchivalCheckpoint.org_id == org_id,
        ArchivalCheckpoint.archival_type == archival_type,
        ArchivalCheckpoint.status == "in_progress"
    )
    result = await session.execute(stmt)
    checkpoint = result.scalar_one_or_none()

    if checkpoint:
        logger.info(
            "resuming_archival_from_checkpoint",
            extra={
                "org_id": str(org_id),
                "logs_processed": checkpoint.logs_processed,
                "last_processed_id": str(checkpoint.last_processed_id),
                "last_checkpoint_at": checkpoint.last_checkpoint_at.isoformat()
            }
        )
        return checkpoint

    # Create new checkpoint
    new_checkpoint = ArchivalCheckpoint(
        org_id=org_id,
        archival_type=archival_type,
        started_at=datetime.now(UTC),
        last_checkpoint_at=datetime.now(UTC)
    )
    session.add(new_checkpoint)
    await session.flush()  # Get ID without commit
    return new_checkpoint

async def update_checkpoint(
    session: AsyncSession,
    checkpoint: ArchivalCheckpoint,
    last_processed_id: UUID,
    logs_processed: int,
    logs_failed: int = 0
):
    """Update checkpoint after processing a batch."""
    checkpoint.last_processed_id = last_processed_id
    checkpoint.logs_processed = logs_processed
    checkpoint.logs_failed = logs_failed
    checkpoint.last_checkpoint_at = datetime.now(UTC)
    # Do NOT commit - caller will commit after successful S3 upload
    await session.flush()

async def complete_checkpoint(
    session: AsyncSession,
    checkpoint: ArchivalCheckpoint
):
    """Mark checkpoint as completed."""
    checkpoint.status = "completed"
    checkpoint.completed_at = datetime.now(UTC)
    await session.flush()

async def fail_checkpoint(
    session: AsyncSession,
    checkpoint: ArchivalCheckpoint,
    error: str
):
    """Mark checkpoint as failed."""
    checkpoint.status = "failed"
    checkpoint.error_message = error
    await session.flush()
```

#### Step 3: Resumable Archival Loop

```python
async def archive_logs_to_s3_with_checkpoint(
    org_id: UUID,
    days_older_than: int = 90,
    batch_size: int = 1000
) -> None:
    """Archive logs to S3 with checkpoint-based resumption."""
    from redact_api.core.database import AsyncSessionLocal
    from redact_api.core.config import settings
    import json
    import gzip

    async with AsyncSessionLocal() as session:
        try:
            # Get or resume checkpoint
            checkpoint = await get_or_create_checkpoint(session, org_id, "s3")

            cutoff_date = datetime.now(UTC) - timedelta(days=days_older_than)
            offset = 0
            total_processed = checkpoint.logs_processed  # Resume from checkpoint count

            while True:
                # Query logs: if resuming, fetch after last_processed_id
                if checkpoint.last_processed_id:
                    logs_query = select(ActivityLog).where(
                        ActivityLog.org_id == org_id,
                        ActivityLog.created_at < cutoff_date,
                        ActivityLog.id > checkpoint.last_processed_id  # Resume after last ID
                    ).order_by(ActivityLog.id).limit(batch_size)
                else:
                    logs_query = select(ActivityLog).where(
                        ActivityLog.org_id == org_id,
                        ActivityLog.created_at < cutoff_date
                    ).order_by(ActivityLog.id).limit(batch_size)

                result = await session.execute(logs_query)
                batch = result.scalars().all()

                if not batch:
                    break  # All logs processed

                # Serialize and upload batch to S3
                logs_json = json.dumps([log.to_dict() for log in batch])
                logs_gzipped = gzip.compress(logs_json.encode())

                key = f"archived_logs/{org_id}/{datetime.now(UTC).date().isoformat()}_batch_{total_processed}.json.gz"

                try:
                    async with aioboto3.Session().client("s3") as s3:
                        # Upload with retry
                        await upload_to_s3_with_retry(s3, settings.archive_bucket, key, logs_gzipped)

                        # Verify upload
                        response = await s3.head_object(Bucket=settings.archive_bucket, Key=key)
                        if response["ContentLength"] != len(logs_gzipped):
                            raise ValueError(f"S3 upload size mismatch for key {key}")

                    # Delete batch from database
                    log_ids = [log.id for log in batch]
                    await session.execute(
                        delete(ActivityLog).where(ActivityLog.id.in_(log_ids))
                    )

                    # Update checkpoint after successful batch
                    total_processed += len(batch)
                    await update_checkpoint(
                        session,
                        checkpoint,
                        last_processed_id=batch[-1].id,
                        logs_processed=total_processed
                    )

                    # Commit after each batch for durability
                    await session.commit()

                    logger.info(
                        "archival_batch_processed",
                        extra={
                            "org_id": str(org_id),
                            "batch_size": len(batch),
                            "total_processed": total_processed,
                            "s3_key": key
                        }
                    )

                except Exception as e:
                    logger.error(
                        "s3_upload_failed",
                        extra={
                            "org_id": str(org_id),
                            "batch_size": len(batch),
                            "error": str(e),
                            "checkpoint_id": str(checkpoint.id)
                        }
                    )
                    await session.rollback()
                    raise  # Will be caught by outer try/except

            # Mark archival as complete
            await complete_checkpoint(session, checkpoint)
            await session.commit()

            logger.info(
                "archival_completed",
                extra={
                    "org_id": str(org_id),
                    "total_processed": total_processed,
                    "checkpoint_id": str(checkpoint.id)
                }
            )

        except Exception as e:
            await fail_checkpoint(session, checkpoint, str(e))
            await session.commit()
            logger.exception(
                "archival_failed",
                extra={
                    "org_id": str(org_id),
                    "error": str(e),
                    "checkpoint_id": str(checkpoint.id)
                }
            )
            raise
```

### Data Integrity Verification

After archival completes, verify that archived data matches the source:

```python
async def verify_s3_archive_integrity(
    org_id: UUID,
    from_date: date,
    to_date: date
) -> dict:
    """Verify archived logs match database source."""
    from redact_api.core.database import AsyncSessionLocal
    from redact_api.core.config import settings
    import json
    import gzip

    async with AsyncSessionLocal() as session:
        # Count logs in database before archival
        db_count_stmt = select(func.count(ActivityLog.id)).where(
            ActivityLog.org_id == org_id,
            ActivityLog.created_at >= from_date,
            ActivityLog.created_at < to_date
        )
        db_result = await session.execute(db_count_stmt)
        db_count = db_result.scalar()

        # Count logs in S3 archive
        s3_count = 0
        async with aioboto3.Session().client("s3") as s3:
            paginator = s3.get_paginator("list_objects_v2")
            prefix = f"archived_logs/{org_id}/"

            async for page in paginator.paginate(Bucket=settings.archive_bucket, Prefix=prefix):
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    response = await s3.get_object(Bucket=settings.archive_bucket, Key=obj["Key"])
                    body = await response["Body"].read()
                    decompressed = gzip.decompress(body)
                    logs = json.loads(decompressed)
                    s3_count += len(logs)

        # Verify counts match
        if db_count != s3_count:
            logger.error(
                "archive_integrity_mismatch",
                extra={
                    "org_id": str(org_id),
                    "db_count": db_count,
                    "s3_count": s3_count,
                    "difference": db_count - s3_count
                }
            )
            raise ValueError(f"Archive mismatch: DB has {db_count} logs, S3 has {s3_count}")

        logger.info(
            "archive_integrity_verified",
            extra={
                "org_id": str(org_id),
                "count": db_count
            }
        )

        return {
            "verified": True,
            "db_count": db_count,
            "s3_count": s3_count
        }
```

### S3 Unavailable Scenario

If S3 is unavailable, implement graceful degradation with retry and queuing:

```python
async def archive_logs_with_s3_fallback(
    org_id: UUID,
    days_older_than: int = 90
) -> None:
    """Archive to S3 with fallback to queue if S3 is down."""
    from redact_api.core.database import AsyncSessionLocal
    from redact_api.core.config import settings
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
    from botocore.exceptions import ClientError

    async def upload_with_fallback():
        try:
            # Try archival with S3
            await archive_logs_to_s3_with_checkpoint(org_id, days_older_than)
        except ClientError as e:
            if e.response["Error"]["Code"] in ["ServiceUnavailable", "RequestTimeTooLarge"]:
                logger.warning(
                    "s3_unavailable_queuing_for_retry",
                    extra={
                        "org_id": str(org_id),
                        "error": e.response["Error"]["Code"]
                    }
                )
                # Queue for retry later
                await queue_archival_retry(org_id, days_older_than, retry_count=0)

                # Alert ops
                await send_alert(
                    title="S3 Archival Delayed",
                    message=f"Log archival for org {org_id} queued due to S3 unavailability",
                    severity="warning"
                )
            else:
                # Other S3 errors should be re-raised
                raise

    await upload_with_fallback()

async def queue_archival_retry(org_id: UUID, days_older_than: int, retry_count: int = 0):
    """Queue failed archival for retry with exponential backoff."""
    from redact_api.core.database import AsyncSessionLocal

    max_retries = 5
    if retry_count >= max_retries:
        logger.critical(
            "archival_max_retries_exceeded",
            extra={"org_id": str(org_id), "retry_count": retry_count}
        )
        return

    # Schedule retry with exponential backoff
    retry_delay_seconds = (2 ** retry_count) * 60  # 1 min, 2 min, 4 min, 8 min, 16 min
    retry_time = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)

    # Store in database for async job processor to pick up
    async with AsyncSessionLocal() as session:
        archival_job = ArchivalRetryJob(
            org_id=org_id,
            days_older_than=days_older_than,
            retry_count=retry_count,
            next_retry_at=retry_time,
            created_at=datetime.now(UTC)
        )
        session.add(archival_job)
        await session.commit()

        logger.info(
            "archival_retry_queued",
            extra={
                "org_id": str(org_id),
                "retry_count": retry_count,
                "next_retry_at": retry_time.isoformat()
            }
        )
```

**Key principles for S3 unavailable scenarios:**

1. **Don't delete logs** - If S3 upload fails, logs stay in database
2. **Queue for later** - Store failed archival in retry queue with exponential backoff
3. **Alert operators** - Send warnings so ops team can investigate
4. **Preserve checkpoint** - Resume from last successful batch when retrying
5. **Max retry limit** - After 5 retries, escalate to critical alert instead of trying again

### Database Down Mid-Operation

Transaction rollback ensures safety if database fails mid-archival:

```python
async def safe_archival_with_transaction():
    """Transactions ensure atomicity - either fully succeeds or fully rolls back."""
    async with AsyncSessionLocal() as session:
        try:
            async with session.begin():  # Start transaction
                # Step 1: Upload to S3
                await upload_batch_to_s3(batch)

                # Step 2: Delete from database (only if upload succeeded)
                await session.execute(
                    delete(ActivityLog).where(...)
                )
                # Commit happens at end of 'async with session.begin()' block

        except Exception:
            # Transaction automatically rolls back on exception
            # Both upload (if idempotent) and delete are undone
            logger.exception("Archival transaction rolled back")
            raise
```

**Important**: S3 uploads are idempotent (same key = overwrite), so retrying a failed transaction is safe. Logs will be re-uploaded to S3 but won't be deleted from the database on retry.

---
## Archival Strategies

### Strategy 1: Move to S3 Archive Storage (Recommended)

**Best for**: Long-term compliance requirements, cost optimization, rarely accessed data.

**Setup**:
```bash
# Install AWS SDK
uv pip install boto3

# Add to .env
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
ARCHIVE_BUCKET=myapp-log-archives
```

**Implementation**:

```python
import json
import gzip
import aioboto3
from datetime import datetime, timedelta, UTC
from sqlalchemy import select, delete
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from botocore.exceptions import ClientError
from redact_api.models import ActivityLog

@retry(
    retry=retry_if_exception_type(ClientError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
async def upload_to_s3_with_retry(s3_client, bucket: str, key: str, data: bytes):
    """Upload to S3 with automatic retry on transient failures."""
    await s3_client.put_object(Bucket=bucket, Key=key, Body=data)

async def archive_logs_to_s3(
    org_id: UUID,
    days_older_than: int = 90,
    batch_size: int = 1000
):
    """Archive logs to S3 with proper transaction handling."""
    from redact_api.core.database import AsyncSessionLocal
    from redact_api.core.config import settings

    cutoff_date = datetime.now(UTC) - timedelta(days=days_older_than)

    async with AsyncSessionLocal() as session:
        try:
            # Step 1: Fetch logs in transaction
            logs_query = select(ActivityLog).where(
                ActivityLog.org_id == org_id,
                ActivityLog.created_at < cutoff_date
            ).limit(batch_size)

            result = await session.execute(logs_query)
            logs = result.scalars().all()

            if not logs:
                return

            # Step 2: Serialize logs
            logs_json = json.dumps([log.to_dict() for log in logs])
            logs_gzipped = gzip.compress(logs_json.encode())

            # Step 3: Upload to S3 (with retry)
            async with aioboto3.Session().client("s3") as s3:
                key = f"archived_logs/{org_id}/{datetime.now(UTC).date()}.json.gz"
                await upload_to_s3_with_retry(
                    s3, settings.archive_bucket, key, logs_gzipped
                )

            # Step 4: Verify upload succeeded (optional but recommended)
            async with aioboto3.Session().client("s3") as s3:
                response = await s3.head_object(Bucket=settings.archive_bucket, Key=key)
                if response["ContentLength"] != len(logs_gzipped):
                    raise ValueError("S3 upload size mismatch")

            # Step 5: Delete from database ONLY after S3 upload verified
            log_ids = [log.id for log in logs]
            await session.execute(
                delete(ActivityLog).where(ActivityLog.id.in_(log_ids))
            )
            await session.commit()

            logger.info(
                "archived_logs_to_s3",
                extra={"org_id": str(org_id), "count": len(logs), "s3_key": key}
            )

        except Exception as e:
            await session.rollback()
            logger.error(
                "s3_archival_failed",
                extra={"org_id": str(org_id), "error": str(e)}
            )
            raise
```

**Retrieval Pattern** (when you need archived logs):

```python
async def retrieve_archived_logs(
    org_id: UUID,
    from_date: date,
    to_date: date
) -> list[dict]:
    """Retrieve archived logs from S3."""
    import gzip
    import json
    import aioboto3
    from redact_api.core.config import settings

    all_logs = []
    session = aioboto3.Session()

    async with session.client("s3", region_name=settings.aws_region) as s3:
        # List all archives in date range
        current_date = from_date
        while current_date <= to_date:
            prefix = f"activity-logs/{org_id}/{current_date.isoformat()}/"

            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=settings.archive_bucket, Prefix=prefix):
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    # Download and decompress
                    response = await s3.get_object(Bucket=settings.archive_bucket, Key=obj["Key"])
                    body = await response["Body"].read()
                    decompressed = gzip.decompress(body)
                    logs = json.loads(decompressed)
                    all_logs.extend(logs)

            current_date += timedelta(days=1)

    return all_logs
```

---

### Strategy 2: Move to Cold Storage Table

**Best for**: Need to query archived logs occasionally, don't want S3 dependency.

**Setup**:
```python
# Create archived logs table with same schema as activity_logs
from sqlalchemy import Table, Column, String, DateTime, etc.

archived_activity_logs = Table(
    'archived_activity_logs',
    metadata,
    Column('id', UUID, primary_key=True),
    Column('org_id', UUID),
    Column('user_id', UUID),
    Column('action', String(50)),
    # ... same columns as ActivityLog
    Column('created_at', DateTime),
    Column('archived_at', DateTime, default=datetime.utcnow),
)
```

**Implementation**:

```python
async def archive_old_activity_logs_task(org_id: UUID, days_older_than: int) -> None:
    """Archive old activity logs to cold storage table."""
    try:
        logger.info(
            "archiving_old_activity_logs",
            extra={"org_id": str(org_id), "days_older_than": days_older_than},
        )

        from redact_api.core.database import AsyncSessionLocal
        from sqlalchemy import select, delete, insert

        cutoff_date = datetime.now(UTC) - timedelta(days=days_older_than)

        async with AsyncSessionLocal() as session:
            # Use INSERT...SELECT for atomic operation
            stmt = insert(ArchivedActivityLog).from_select(
                [
                    ActivityLog.id,
                    ActivityLog.org_id,
                    ActivityLog.user_id,
                    ActivityLog.action,
                    ActivityLog.resource_type,
                    ActivityLog.resource_id,
                    ActivityLog.created_at,
                    # ... all other columns
                ],
                select(ActivityLog).where(
                    ActivityLog.org_id == org_id,
                    ActivityLog.created_at < cutoff_date
                )
            )

            result = await session.execute(stmt)
            total_archived = result.rowcount

            # Delete from active table
            await session.execute(
                delete(ActivityLog).where(
                    ActivityLog.org_id == org_id,
                    ActivityLog.created_at < cutoff_date
                )
            )

            await session.commit()

            logger.info(
                "activity_logs_archived",
                extra={"org_id": str(org_id), "total_archived": total_archived},
            )

    except Exception:
        logger.exception(
            "Failed to archive activity logs",
            extra={"org_id": str(org_id)},
        )
```

**Query archived logs**:

```python
async def get_archived_logs(org_id: UUID, from_date: date, to_date: date):
    """Query archived logs from cold storage."""
    from redact_api.core.database import AsyncSessionLocal
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        stmt = select(ArchivedActivityLog).where(
            ArchivedActivityLog.org_id == org_id,
            ArchivedActivityLog.created_at >= from_date,
            ArchivedActivityLog.created_at < to_date,
        )
        result = await session.execute(stmt)
        return result.scalars().all()
```

---

### Strategy 3: Deletion (Destructive, Use Carefully)

**Best for**: Logs not needed for compliance, cost optimization is critical.

**⚠️ WARNING**: Deleted logs cannot be recovered. Only use if you don't need historical data.

**Implementation**:

```python
async def archive_old_activity_logs_task(org_id: UUID, days_older_than: int) -> None:
    """Delete old activity logs (non-recoverable)."""
    try:
        logger.warning(
            "deleting_old_activity_logs",
            extra={
                "org_id": str(org_id),
                "days_older_than": days_older_than,
                "warning": "Deleted logs cannot be recovered"
            },
        )

        from redact_api.core.database import AsyncSessionLocal
        from sqlalchemy import delete

        cutoff_date = datetime.now(UTC) - timedelta(days=days_older_than)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                delete(ActivityLog).where(
                    ActivityLog.org_id == org_id,
                    ActivityLog.created_at < cutoff_date
                )
            )
            await session.commit()

            logger.info(
                "activity_logs_deleted",
                extra={"org_id": str(org_id), "total_deleted": result.rowcount},
            )

    except Exception:
        logger.exception(
            "Failed to delete activity logs",
            extra={"org_id": str(org_id)},
        )
```

---

## Compliance Considerations

### GDPR (General Data Protection Regulation)

**Right to be Forgotten**: Users can request deletion of their personal data.

**Implementation**:
```python
async def handle_gdpr_deletion_request(
    session: AsyncSession,
    user_id: UUID,
    org_id: UUID
) -> None:
    """Delete all user activity logs per GDPR right to be forgotten."""
    try:
        logger.info(
            "processing_gdpr_deletion",
            extra={"user_id": str(user_id), "org_id": str(org_id)}
        )

        # Delete from active logs
        await session.execute(
            delete(ActivityLog).where(
                ActivityLog.user_id == user_id,
                ActivityLog.org_id == org_id
            )
        )

        # Delete from archived logs (if using cold storage)
        await session.execute(
            delete(ArchivedActivityLog).where(
                ArchivedActivityLog.user_id == user_id,
                ArchivedActivityLog.org_id == org_id
            )
        )

        # Delete from S3 archives (if using S3)
        await delete_user_archives_from_s3(user_id, org_id)

        await session.commit()

        logger.info(
            "gdpr_deletion_completed",
            extra={"user_id": str(user_id), "org_id": str(org_id)}
        )

    except Exception:
        await session.rollback()
        logger.exception(
            "GDPR deletion failed",
            extra={"user_id": str(user_id), "org_id": str(org_id)}
        )
        raise

async def delete_user_archives_from_s3(user_id: UUID, org_id: UUID) -> None:
    """Delete all S3 archives containing user's personal data."""
    import aioboto3
    from redact_api.core.config import settings

    session = aioboto3.Session()
    async with session.client("s3") as s3:
        # List all archives for this user
        paginator = s3.get_paginator("list_objects_v2")
        async for page in paginator.paginate(
            Bucket=settings.archive_bucket,
            Prefix=f"archived_logs/{org_id}/"
        ):
            if "Contents" not in page:
                continue

            # For each archive, download, filter out user's data, and re-upload
            for obj in page["Contents"]:
                # Download
                response = await s3.get_object(
                    Bucket=settings.archive_bucket,
                    Key=obj["Key"]
                )
                body = await response["Body"].read()

                # Decompress and parse
                import gzip, json
                decompressed = gzip.decompress(body)
                logs = json.loads(decompressed)

                # Filter out user's logs
                filtered_logs = [
                    log for log in logs
                    if log.get("user_id") != str(user_id)
                ]

                if not filtered_logs:
                    # No logs left, delete the object
                    await s3.delete_object(
                        Bucket=settings.archive_bucket,
                        Key=obj["Key"]
                    )
                else:
                    # Re-upload filtered logs
                    filtered_json = json.dumps(filtered_logs)
                    filtered_gzipped = gzip.compress(filtered_json.encode())
                    await s3.put_object(
                        Bucket=settings.archive_bucket,
                        Key=obj["Key"],
                        Body=filtered_gzipped
                    )
```

### HIPAA (Health Insurance Portability and Accountability Act)

**Audit Log Requirements**:
- Retention: 6+ years
- Immutable: Cannot be modified once written
- Encryption: At rest and in transit
- Access Control: Audit who accesses logs

**Implementation**:
```python
# Use WORM (Write-Once-Read-Many) S3 configuration
async def create_hipaa_compliant_s3_bucket() -> None:
    """Create S3 bucket with HIPAA compliance features."""
    import aioboto3
    from redact_api.core.config import settings

    session = aioboto3.Session()
    async with session.client("s3") as s3:
        # Enable Object Lock (WORM)
        await s3.create_bucket(
            Bucket=settings.archive_bucket,
            CreateBucketConfiguration={'LocationConstraint': settings.aws_region},
            ObjectLockEnabledForBucket=True
        )

        # Enable versioning (required for Object Lock)
        await s3.put_bucket_versioning(
            Bucket=settings.archive_bucket,
            VersioningConfiguration={'Status': 'Enabled'}
        )

        # Set Object Lock retention policy (6+ years = 2190 days)
        await s3.put_object_lock_configuration(
            Bucket=settings.archive_bucket,
            ObjectLockConfiguration={
                'ObjectLockEnabled': 'Enabled',
                'Rule': {
                    'DefaultRetention': {
                        'Mode': 'COMPLIANCE',  # Cannot be overridden
                        'Days': 2190  # 6 years
                    }
                }
            }
        )

        # Enable encryption at rest
        await s3.put_bucket_encryption(
            Bucket=settings.archive_bucket,
            ServerSideEncryptionConfiguration={
                'Rules': [
                    {
                        'ApplyServerSideEncryptionByDefault': {
                            'SSEAlgorithm': 'aws:kms',
                            'KMSMasterKeyID': settings.kms_key_id
                        }
                    }
                ]
            }
        )

        logger.info(
            "hipaa_compliant_bucket_created",
            extra={"bucket": settings.archive_bucket}
        )

async def archive_logs_hipaa_compliant(
    session: AsyncSession,
    org_id: UUID,
    days_older_than: int = 90
) -> None:
    """Archive logs with HIPAA compliance: immutable + 6+ year retention."""
    from datetime import datetime, timedelta, UTC
    import json, gzip
    import aioboto3
    from redact_api.core.config import settings

    cutoff_date = datetime.now(UTC) - timedelta(days=days_older_than)

    # Fetch logs
    logs_query = select(ActivityLog).where(
        ActivityLog.org_id == org_id,
        ActivityLog.created_at < cutoff_date
    ).limit(1000)

    result = await session.execute(logs_query)
    logs = result.scalars().all()

    if not logs:
        return

    # Serialize with audit metadata
    logs_data = {
        "archived_at": datetime.now(UTC).isoformat(),
        "org_id": str(org_id),
        "log_count": len(logs),
        "logs": [log.to_dict() for log in logs]
    }

    logs_json = json.dumps(logs_data)
    logs_gzipped = gzip.compress(logs_json.encode())

    # Upload to S3 (WORM bucket)
    session_aws = aioboto3.Session()
    async with session_aws.client("s3") as s3:
        key = f"hipaa-compliant-archives/{org_id}/{datetime.now(UTC).date().isoformat()}.json.gz"

        # Upload with metadata for audit trail
        await s3.put_object(
            Bucket=settings.archive_bucket,
            Key=key,
            Body=logs_gzipped,
            Metadata={
                "org_id": str(org_id),
                "archived_at": datetime.now(UTC).isoformat(),
                "compliance": "hipaa"
            },
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=settings.kms_key_id
        )

    # Delete from active table AFTER upload confirmed
    log_ids = [log.id for log in logs]
    await session.execute(
        delete(ActivityLog).where(ActivityLog.id.in_(log_ids))
    )
    await session.commit()

    logger.info(
        "logs_archived_hipaa_compliant",
        extra={"org_id": str(org_id), "s3_key": key}
    )
```

### SOC2 (System and Organization Controls)

**Audit Logging Requirements**:
- Log all access to sensitive data
- Least-privilege access control
- User identification (who did what when)

**Implementation**:
```python
async def log_audit_access(
    user_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID,
    org_id: UUID,
    timestamp: datetime = None
) -> None:
    """Log all access for SOC2 compliance."""
    from redact_api.core.database import AsyncSessionLocal
    from redact_api.models import AuditLog

    if timestamp is None:
        timestamp = datetime.now(UTC)

    async with AsyncSessionLocal() as session:
        audit = AuditLog(
            user_id=user_id,
            org_id=org_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            timestamp=timestamp,
            ip_address=get_client_ip(),  # From request context
            user_agent=get_user_agent()   # From request context
        )
        session.add(audit)
        await session.commit()

        logger.info(
            "audit_access_logged",
            extra={
                "user_id": str(user_id),
                "action": action,
                "resource": f"{resource_type}:{resource_id}"
            }
        )

# In API endpoints, wrap sensitive operations
@router.get("/organizations/{org_id}/logs")
async def get_organization_logs(
    org_id: UUID,
    current_user: CurrentUserDep = None
):
    """Get organization logs (audit all access)."""
    # Check permissions
    if not can_access_logs(current_user, org_id):
        raise HTTPException(status_code=403)

    # Log the access
    await log_audit_access(
        user_id=current_user.id,
        action="VIEW_LOGS",
        resource_type="ActivityLog",
        resource_id=org_id,
        org_id=org_id
    )

    # Return data
    return await get_logs_service(org_id)
```

---

## Transaction Handling

### Atomic Archive + Delete

Ensure logs are safely archived before deletion:

```python
async def safe_archive_with_transaction(org_id: UUID, days_older_than: int):
    """Archive with transaction rollback on failure."""
    from redact_api.core.database import AsyncSessionLocal
    from sqlalchemy import select, delete

    try:
        async with AsyncSessionLocal() as session:
            # Start transaction
            async with session.begin():
                cutoff_date = datetime.now(UTC) - timedelta(days=days_older_than)

                # Step 1: Insert into archive
                stmt = insert(ArchivedActivityLog).from_select(..., select(...).where(...))
                result = await session.execute(stmt)
                rows_archived = result.rowcount

                # Step 2: Verify archive count
                verify_stmt = select(func.count(ArchivedActivityLog.id)).where(...)
                verify_result = await session.execute(verify_stmt)
                rows_in_archive = verify_result.scalar()

                if rows_archived != rows_in_archive:
                    raise Exception(f"Archive count mismatch: {rows_archived} vs {rows_in_archive}")

                # Step 3: Delete from active table
                delete_stmt = delete(ActivityLog).where(...)
                await session.execute(delete_stmt)

            # If we get here, transaction committed successfully
            logger.info("Archive and delete completed successfully")

    except Exception as e:
        # Transaction auto-rolled back on exception
        logger.exception("Archive failed, rolled back", extra={"error": str(e)})
        raise
```

---

## Testing Log Archival

### Unit Test: Mock Database

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import UUID
from datetime import datetime, timedelta

@pytest.mark.asyncio
async def test_archive_old_activity_logs_s3():
    """Test archival with mocked S3 and database."""
    org_id = UUID("12345678-1234-5678-1234-567812345678")
    days_older_than = 90

    # Create test logs
    cutoff_date = datetime.now(UTC) - timedelta(days=days_older_than)
    old_logs = [
        ActivityLog(id=UUID(int=1), org_id=org_id, created_at=cutoff_date - timedelta(days=1)),
        ActivityLog(id=UUID(int=2), org_id=org_id, created_at=cutoff_date - timedelta(days=30)),
    ]

    with patch("aioboto3.Session") as mock_s3_session:
        with patch("SessionLocal") as mock_session_local:
            # Mock database
            mock_session = AsyncMock()
            mock_session_local.return_value = mock_session

            # Mock S3
            mock_s3 = AsyncMock()
            mock_s3_session.return_value.client.return_value.__aenter__.return_value = mock_s3

            # Call function
            await archive_old_activity_logs_task(org_id, days_older_than)

            # Verify S3 was called
            mock_s3.put_object.assert_called()
```

### Integration Test: Real Database (Test Database)

```python
@pytest.mark.asyncio
async def test_archive_cold_storage_integration(test_session):
    """Test archival with real test database."""
    org_id = UUID("12345678-1234-5678-1234-567812345678")

    # Create test logs
    cutoff_date = datetime.now(UTC) - timedelta(days=91)
    old_log = ActivityLog(
        id=UUID(int=1),
        org_id=org_id,
        user_id=UUID(int=100),
        action="CREATE",
        resource_type="User",
        resource_id=UUID(int=101),
        created_at=cutoff_date
    )
    test_session.add(old_log)
    await test_session.commit()

    # Verify old log exists
    stmt = select(func.count(ActivityLog.id)).where(
        ActivityLog.org_id == org_id,
        ActivityLog.created_at < cutoff_date
    )
    result = await test_session.execute(stmt)
    assert result.scalar() == 1

    # Run archival
    await archive_old_activity_logs_task(org_id, 90)

    # Verify log moved to archive
    stmt = select(func.count(ArchivedActivityLog.id)).where(
        ArchivedActivityLog.org_id == org_id
    )
    result = await test_session.execute(stmt)
    assert result.scalar() == 1

    # Verify log deleted from active table
    stmt = select(func.count(ActivityLog.id)).where(ActivityLog.org_id == org_id)
    result = await test_session.execute(stmt)
    assert result.scalar() == 0
```

### Edge Cases to Test

```python
@pytest.mark.asyncio
async def test_archive_with_zero_old_logs(test_session):
    """Test archival when no old logs exist."""
    org_id = UUID("12345678-1234-5678-1234-567812345678")

    # Don't create any logs
    # Should complete gracefully
    await archive_old_activity_logs_task(org_id, 90)

    # No errors should occur

@pytest.mark.asyncio
async def test_archive_empty_org(test_session):
    """Test archival for organization with no logs."""
    org_id = UUID("99999999-9999-9999-9999-999999999999")

    await archive_old_activity_logs_task(org_id, 90)

    # Should complete without errors
```

---

## Configuration Checklist

Before going to production:

- [ ] Archival strategy chosen (S3, cold storage, or deletion)
- [ ] Database indexes created on `org_id` and `created_at` columns
- [ ] S3 bucket created and configured (if using S3)
- [ ] IAM permissions verified for S3 access
- [ ] Batch size tuned for your database (1000-10000 based on log size)
- [ ] Date range processing configured for large datasets
- [ ] Transaction handling tested with failures
- [ ] Archived logs retrievable (if needed later)
- [ ] Scheduled job configured (cron, APScheduler, etc.)
- [ ] Monitoring/alerting set up for archival failures
- [ ] Dry-run completed on production-like database
- [ ] Rollback plan documented

---

## Common Mistakes to Avoid

### ❌ Mistake 1: Loading All Logs Into Memory

```python
# BAD - loads millions of logs into memory at once
logs = await session.execute(select(ActivityLog).where(...))
all_logs = logs.scalars().all()  # CRASH on large datasets
```

**Fix**: Use batch processing:
```python
# GOOD - processes in chunks
async for batch in process_logs_in_batches(session, org_id, 90, batch_size=1000):
    # Process batch
    pass
```

### ❌ Mistake 2: Missing Transaction Rollback

```python
# BAD - if S3 upload fails, logs deleted but not archived
for log in logs:
    archive_to_s3(log)  # Fails halfway
    session.execute(delete(ActivityLog).where(...))  # Executed anyway
```

**Fix**: Use transaction wrapping:
```python
# GOOD - all or nothing
async with session.begin():
    archive_result = await session.execute(insert(...))
    if archive_result.rowcount != expected:
        raise Exception("Archive count mismatch")
    delete_result = await session.execute(delete(...))
```

### ❌ Mistake 3: Archiving Too Aggressively

```python
# BAD - deletes logs users might need (e.g., regulatory audits)
await archive_old_activity_logs_task(org_id, days_older_than=7)
```

**Fix**: Use appropriate retention:
```python
# GOOD - matches compliance requirements
await archive_old_activity_logs_task(org_id, days_older_than=90)  # Per regulation
```

### ❌ Mistake 4: No Monitoring of Archival Task

```python
# BAD - task fails silently, logs never archived
asyncio.create_task(archive_old_activity_logs_task(...))
# No error tracking, monitoring, or alerting
```

**Fix**: Add proper error handling and monitoring:
```python
# GOOD - failures are logged and alerted
try:
    await archive_old_activity_logs_task(org_id, 90)
except Exception:
    logger.exception("Archive task failed", extra={"org_id": str(org_id)})
    send_alert("Log archival failed")  # Alert ops team
```

### ❌ Mistake 5: Archiving Active User Data

```python
# BAD - archives logs for users still accessing the system
cutoff_date = datetime.now(UTC) - timedelta(days=30)  # Too aggressive
```

**Fix**: Archive older logs:
```python
# GOOD - archive only truly old logs
cutoff_date = datetime.now(UTC) - timedelta(days=90)  # 3 months minimum
```

---

## Monitoring & Alerting

### Key Metrics to Track

Monitor these metrics to ensure reliable archival operations:

1. **archival_rows_total** (Counter)
   - Total number of rows successfully archived
   - Labels: org_id, strategy (s3, cold_storage, deletion)
   - Example: `archival_rows_total{org_id="...", strategy="s3"} 15000`

2. **archival_duration_seconds** (Histogram)
   - Time taken to archive a batch of logs
   - Tracks P50, P95, P99 latencies
   - Example: `archival_duration_seconds_bucket{strategy="s3", le="60"} 450`

3. **archival_failures_total** (Counter)
   - Number of failed archival attempts
   - Labels: org_id, strategy, error_type
   - Example: `archival_failures_total{org_id="...", strategy="s3", error="timeout"} 3`

### Prometheus Alert Rules

Add these alert rules to your Prometheus configuration:

```yaml
groups:
  - name: log_archival_alerts
    interval: 30s
    rules:
      # Alert: High archival failure rate
      - alert: LogArchivalFailureRate
        expr: |
          (rate(archival_failures_total[5m]) / rate(archival_rows_total[5m])) > 0.05
        for: 5m
        annotations:
          summary: "High log archival failure rate ([[ $value | humanizePercentage ]])"
          description: |
            Log archival is failing more than 5% of the time.
            Check S3 bucket permissions, network connectivity, and disk space.

      # Alert: Slow archival
      - alert: SlowLogArchival
        expr: |
          histogram_quantile(0.95, archival_duration_seconds_bucket) > 120
        for: 10m
        annotations:
          summary: "Log archival is slow (P95: [[ $value | humanizeDuration ]])"
          description: |
            95th percentile archival time exceeded 2 minutes.
            Check database query performance and S3 throughput limits.

      # Alert: No archival in 24 hours
      - alert: NoLogArchival
        expr: |
          increase(archival_rows_total[24h]) == 0
        for: 1h
        annotations:
          summary: "No log archival in 24 hours"
          description: |
            Archival task hasn't run or is completely failing.
            Check APScheduler/Celery configuration and logs.

      # Alert: S3 upload failures
      - alert: S3UploadFailures
        expr: |
          rate(archival_failures_total{strategy="s3", error="s3_error"}[5m]) > 0.1
        for: 5m
        annotations:
          summary: "S3 upload failures detected"
          description: |
            Multiple S3 upload errors. Check:
            - IAM permissions for S3 bucket
            - S3 bucket availability
            - Network connectivity to S3
            - KMS key encryption permissions (if using SSE-KMS)
```

### Structured Logging Best Practices

Use structured logging to enable better monitoring and debugging:

```python
from datetime import datetime, timedelta, UTC
import logging
import json

logger = logging.getLogger(__name__)

async def archive_logs_with_structured_logging(
    session: AsyncSession,
    org_id: UUID,
    days_older_than: int = 90
) -> None:
    """Archive logs with detailed structured logging."""
    start_time = datetime.now(UTC)
    rows_archived = 0

    try:
        logger.info(
            "archival_started",
            extra={
                "org_id": str(org_id),
                "days_older_than": days_older_than,
                "timestamp": start_time.isoformat()
            }
        )

        cutoff_date = datetime.now(UTC) - timedelta(days=days_older_than)

        # Fetch logs
        logs_query = select(func.count(ActivityLog.id)).where(
            ActivityLog.org_id == org_id,
            ActivityLog.created_at < cutoff_date
        )
        result = await session.execute(logs_query)
        total_to_archive = result.scalar()

        logger.info(
            "archival_logs_found",
            extra={
                "org_id": str(org_id),
                "total_count": total_to_archive
            }
        )

        if total_to_archive == 0:
            logger.info(
                "archival_skipped_no_logs",
                extra={"org_id": str(org_id)}
            )
            return

        # Archive in batches with progress tracking
        batch_size = 1000
        for batch_num in range(0, total_to_archive, batch_size):
            batch_start = datetime.now(UTC)

            # Archive batch...
            archive_stmt = select(ActivityLog).where(
                ActivityLog.org_id == org_id,
                ActivityLog.created_at < cutoff_date
            ).limit(batch_size)

            result = await session.execute(archive_stmt)
            batch = result.scalars().all()
            rows_archived += len(batch)

            batch_duration = (datetime.now(UTC) - batch_start).total_seconds()

            logger.info(
                "archival_batch_completed",
                extra={
                    "org_id": str(org_id),
                    "batch_number": batch_num // batch_size + 1,
                    "batch_size": len(batch),
                    "batch_duration_seconds": batch_duration,
                    "cumulative_rows": rows_archived,
                    "progress_percent": (rows_archived / total_to_archive * 100)
                }
            )

            # Delete from database
            await session.execute(
                delete(ActivityLog).where(
                    ActivityLog.org_id == org_id,
                    ActivityLog.created_at < cutoff_date
                ).limit(batch_size)
            )

        await session.commit()

        total_duration = (datetime.now(UTC) - start_time).total_seconds()

        logger.info(
            "archival_completed",
            extra={
                "org_id": str(org_id),
                "total_rows_archived": rows_archived,
                "total_duration_seconds": total_duration,
                "avg_rate_rows_per_second": rows_archived / total_duration if total_duration > 0 else 0
            }
        )

    except Exception as e:
        await session.rollback()

        duration = (datetime.now(UTC) - start_time).total_seconds()

        logger.exception(
            "archival_failed",
            extra={
                "org_id": str(org_id),
                "rows_archived_before_failure": rows_archived,
                "duration_seconds": duration,
                "error_type": type(e).__name__,
                "error_message": str(e)
            }
        )
        raise

# Tip: Structure logs as JSON for easier parsing by log aggregators
# Each log should have: timestamp, level, message, org_id, operation, metrics
```

### Log Aggregation & Dashboards

Configure your log aggregator to track archival operations:

**Elasticsearch/ELK Stack Query**:
```json
{
  "query": {
    "bool": {
      "must": [
        {"term": {"log_type": "archival"}},
        {"range": {"timestamp": {"gte": "now-24h"}}}
      ]
    }
  },
  "aggs": {
    "by_status": {
      "terms": {"field": "status"}
    },
    "avg_duration": {
      "avg": {"field": "duration_seconds"}
    }
  }
}
```

**Grafana Dashboard Panels**:
```
- Panel 1: Rows Archived Per Org (Graph)
  Query: rate(archival_rows_total[1h]) group by org_id

- Panel 2: Archival Success Rate (Gauge)
  Query: (rate(archival_rows_total[1h]) / (rate(archival_rows_total[1h]) + rate(archival_failures_total[1h]))) * 100

- Panel 3: P95 Duration By Strategy (Heatmap)
  Query: histogram_quantile(0.95, archival_duration_seconds_bucket) group by strategy

- Panel 4: Failures By Error Type (Pie Chart)
  Query: archival_failures_total group by error_type
```

---

## Summary

To implement log archival:

1. **Choose strategy** (S3, cold storage, or deletion)
2. **Set retention policy** (90 days recommended for compliance)
3. **Create database indexes** on org_id and created_at
4. **Process in batches** to avoid memory issues
5. **Use transactions** to ensure atomicity
6. **Test thoroughly** with edge cases
7. **Monitor task execution** and alert on failures
8. **Document retrieval process** if using S3 or cold storage

Choose **S3 archival** for compliance-heavy applications needing long-term retention without database bloat.

---

## Batch Size Tuning

Choosing the right batch size is critical for performance:

### Batch Size Guidelines

| Database Size | Log Size | Recommended Batch | Memory Impact |
|---------------|----------|-------------------|---------------|
| Small (< 1M logs) | < 5KB per log | 1,000 | ~5 MB |
| Medium (1M-10M) | 5-10KB per log | 2,000 | ~20 MB |
| Large (10M-100M) | 10-50KB per log | 500 | ~25 MB |
| Very Large (> 100M) | 50KB+ per log | 100-250 | ~15 MB |

### Tuning Logic

```python
async def determine_optimal_batch_size(
    session: AsyncSession,
    org_id: UUID
) -> int:
    """Calculate batch size based on average log size."""
    from sqlalchemy import func, select

    # Get average log size
    avg_size_stmt = select(
        func.avg(func.length(ActivityLog.metadata)).label("avg_size")
    ).where(ActivityLog.org_id == org_id)

    result = await session.execute(avg_size_stmt)
    avg_size = result.scalar() or 1000  # Default 1KB

    # Target: ~20MB per batch
    target_batch_memory = 20 * 1024 * 1024  # 20MB
    batch_size = max(100, int(target_batch_memory / avg_size))

    logger.info(
        "batch_size_calculated",
        extra={
            "org_id": str(org_id),
            "avg_log_size": avg_size,
            "recommended_batch_size": batch_size
        }
    )

    return batch_size
```

---

## Backup & Disaster Recovery

Implement backup strategy for archived logs:

```python
async def backup_s3_archives(org_id: UUID, from_date: date, to_date: date) -> None:
    """Backup S3 archives to secondary region for disaster recovery."""
    import aioboto3
    from datetime import datetime, UTC
    from redact_api.core.config import settings

    session_s3 = aioboto3.Session()

    # Copy from primary to backup bucket in different region
    async with session_s3.client("s3", region_name=settings.aws_region) as s3_primary:
        async with session_s3.client("s3", region_name=settings.aws_backup_region) as s3_backup:

            # List archives to backup
            paginator = s3_primary.get_paginator("list_objects_v2")
            async for page in paginator.paginate(
                Bucket=settings.archive_bucket,
                Prefix=f"archived_logs/{org_id}/"
            ):
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    try:
                        # Download from primary
                        response = await s3_primary.get_object(
                            Bucket=settings.archive_bucket,
                            Key=obj["Key"]
                        )
                        body = await response["Body"].read()

                        # Upload to backup bucket
                        await s3_backup.put_object(
                            Bucket=settings.backup_archive_bucket,
                            Key=obj["Key"],
                            Body=body,
                            Metadata={"backup_at": datetime.now(UTC).isoformat()}
                        )

                        logger.info(
                            "archive_backed_up",
                            extra={"s3_key": obj["Key"], "backup_bucket": settings.backup_archive_bucket}
                        )
                    except Exception:
                        logger.exception(
                            "backup_failed",
                            extra={"s3_key": obj["Key"]}
                        )
                        raise
```

---

## Concurrency & Partial Failure Handling

Handle failures gracefully when archiving multiple organizations:

```python
async def archive_all_orgs_with_concurrency(days_older_than: int = 90) -> None:
    """Archive logs for all organizations with proper concurrency control."""
    from redact_api.core.database import AsyncSessionLocal
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        # Get all organizations
        orgs_stmt = select(Organization)
        result = await session.execute(orgs_stmt)
        orgs = result.scalars().all()

    # Use semaphore to limit concurrent archival (prevent DB overload)
    semaphore = asyncio.Semaphore(3)  # Max 3 concurrent archival tasks

    async def archive_with_semaphore(org_id: UUID) -> None:
        async with semaphore:
            try:
                await archive_old_activity_logs_task(org_id, days_older_than)
            except Exception:
                logger.exception(
                    "org_archival_failed",
                    extra={"org_id": str(org_id)}
                )
                # Continue with next org instead of failing all

    # Create tasks for all organizations
    tasks = [archive_with_semaphore(org.id) for org in orgs]

    # Wait for all with proper error handling
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Report results
    successes = sum(1 for r in results if r is None)
    failures = sum(1 for r in results if isinstance(r, Exception))

    logger.info(
        "bulk_archival_completed",
        extra={
            "total_orgs": len(orgs),
            "successes": successes,
            "failures": failures
        }
    )
```

---

## S3 Retrieval Performance

Optimize retrieval of archived logs:

```python
async def retrieve_archived_logs_optimized(
    org_id: UUID,
    from_date: date,
    to_date: date,
    use_parallel: bool = True
) -> list[dict]:
    """Retrieve archived logs with optional parallel downloads."""
    import gzip, json
    import aioboto3
    from redact_api.core.config import settings

    all_logs = []
    session = aioboto3.Session()

    # List all archives in date range
    keys_to_download = []
    async with session.client("s3") as s3:
        current_date = from_date
        while current_date <= to_date:
            prefix = f"archived_logs/{org_id}/{current_date.isoformat()}/"

            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(
                Bucket=settings.archive_bucket,
                Prefix=prefix
            ):
                if "Contents" in page:
                    keys_to_download.extend([obj["Key"] for obj in page["Contents"]])

            current_date += timedelta(days=1)

    # Download in parallel if many files
    if use_parallel and len(keys_to_download) > 5:
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent downloads

        async def download_archive(key: str) -> list[dict]:
            async with semaphore:
                async with session.client("s3") as s3:
                    response = await s3.get_object(
                        Bucket=settings.archive_bucket,
                        Key=key
                    )
                    body = await response["Body"].read()
                    decompressed = gzip.decompress(body)
                    return json.loads(decompressed)

        tasks = [download_archive(key) for key in keys_to_download]
        results = await asyncio.gather(*tasks)
        all_logs = [log for result in results for log in result]
    else:
        # Sequential download for small number of files
        async with session.client("s3") as s3:
            for key in keys_to_download:
                response = await s3.get_object(
                    Bucket=settings.archive_bucket,
                    Key=key
                )
                body = await response["Body"].read()
                decompressed = gzip.decompress(body)
                logs = json.loads(decompressed)
                all_logs.extend(logs)

    return all_logs
```

---

## Monitoring & Alerting Continued

### Key Metrics for Archival Operations

```python
from prometheus_client import Counter, Histogram, Gauge

# Define metrics
archival_rows_total = Counter(
    "archival_rows_total",
    "Total rows successfully archived",
    ["org_id", "strategy"]
)

archival_duration_seconds = Histogram(
    "archival_duration_seconds",
    "Time to archive logs",
    ["org_id", "strategy"]
)

archival_failures_total = Counter(
    "archival_failures_total",
    "Total archival failures",
    ["org_id", "strategy", "error_type"]
)

database_rows_archived_total = Gauge(
    "database_rows_archived_total",
    "Total rows removed from active database",
    ["org_id"]
)

async def archive_with_metrics(
    session: AsyncSession,
    org_id: UUID,
    days_older_than: int = 90
) -> None:
    """Archive with Prometheus metrics."""
    import time

    start_time = time.time()
    rows_archived = 0

    try:
        # Archival logic...
        rows_archived = await archive_old_activity_logs_task(org_id, days_older_than)

        # Record success metrics
        archival_rows_total.labels(org_id=str(org_id), strategy="s3").inc(rows_archived)
        database_rows_archived_total.labels(org_id=str(org_id)).set(rows_archived)

    except Exception as e:
        archival_failures_total.labels(
            org_id=str(org_id),
            strategy="s3",
            error_type=type(e).__name__
        ).inc()
        raise
    finally:
        duration = time.time() - start_time
        archival_duration_seconds.labels(org_id=str(org_id), strategy="s3").observe(duration)
```
