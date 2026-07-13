# Background Job Patterns

Guide for implementing background jobs and asynchronous processing in FastAPI.

## Overview

Background jobs allow you to offload long-running or non-critical tasks from HTTP request handling:

- Sending emails (not blocking user response)
- Generating reports (can continue while user works)
- File processing (upload returns immediately)
- Cleanup tasks (run on schedule)

## Patterns

### Pattern 1: Fire-and-Forget with asyncio.create_task()

Simplest pattern - ideal for short-lived tasks that don't need tracking.

```python
import asyncio
from uuid import uuid4

@router.post("/send-email", status_code=202)
async def send_email_endpoint(email_data: EmailRequest) -> dict:
    """Send email in background, return immediately."""
    # Store email in database first (user sees confirmation)
    stored_email = await save_email_to_queue(email_data)

    # Send email in background (fire-and-forget)
    asyncio.create_task(send_email_task(stored_email.id))

    return {
        "message": "Email queued for sending",
        "id": str(stored_email.id),
    }

async def send_email_task(email_id: UUID) -> None:
    """Background task to actually send email."""
    try:
        email = await get_email(email_id)
        await smtp_client.send(email)
        await mark_email_sent(email_id)
    except Exception as exc:
        LOGGER.error(f"Failed to send email: {exc}")
        await mark_email_failed(email_id, str(exc))
```

**Pros:**
- Simple, no dependencies
- Lightweight
- Good for fire-and-forget

**Cons:**
- No job tracking
- No persistence (lost on restart)
- No scheduling support

### Pattern 2: Tracked Jobs with aiojobs

Track job progress and allow querying status.

```python
# Install: pip install aiojobs

import aiojobs
from typing import Any

# In main.py
scheduler = None

@app.on_event("startup")
async def startup():
    """Initialize job scheduler on startup."""
    global scheduler
    scheduler = await aiojobs.create_scheduler()

@app.on_event("shutdown")
async def shutdown():
    """Graceful shutdown of pending jobs."""
    global scheduler
    if scheduler:
        await scheduler.close()

# In endpoints
@router.post("/process-file", status_code=202)
async def process_file_endpoint(file: UploadFile) -> dict:
    """Process file in background with job tracking."""
    from redact_api.main import scheduler

    # Store file
    file_id = uuid4()
    await save_upload(file_id, file)

    # Schedule background job
    job = await scheduler.spawn(
        process_file_job(file_id),
        _name=f"process_file_{file_id}",
    )

    return {
        "message": "File queued for processing",
        "file_id": str(file_id),
        "job_id": job._id if hasattr(job, '_id') else str(file_id),
    }

async def process_file_job(file_id: UUID) -> None:
    """Background job to process uploaded file."""
    try:
        file = await get_file(file_id)
        # Expensive processing
        result = await expensive_processing(file)
        await save_result(file_id, result)
        LOGGER.info(f"File {file_id} processed successfully")
    except Exception as exc:
        LOGGER.error(f"Failed to process file {file_id}: {exc}")
        await save_error(file_id, str(exc))

# Endpoint to check job status
@router.get("/jobs/{file_id}/status")
async def get_job_status(file_id: UUID) -> dict:
    """Get status of file processing job."""
    result = await get_file_result(file_id)
    if result:
        return {
            "status": "completed",
            "result": result,
        }

    error = await get_file_error(file_id)
    if error:
        return {
            "status": "failed",
            "error": error,
        }

    # Check if still processing
    file = await get_file(file_id)
    if file and not file.processed_at:
        return {"status": "processing"}

    return {"status": "not_found"}
```

**Pros:**
- Track job progress
- Query job status
- Graceful shutdown
- Proper exception handling

**Cons:**
- Loses jobs on restart (in-memory only)
- Not persistent

### Pattern 3: Persistent Job Queue

Use external job queue for reliability and persistence.

```python
# Install: pip install redis rq
# OR: pip install celery

# With Redis + RQ
from rq import Queue
import redis

redis_conn = redis.Redis()
q = Queue(connection=redis_conn)

@router.post("/generate-report", status_code=202)
async def generate_report(params: ReportParams) -> dict:
    """Generate report in background job queue."""
    # Enqueue job
    job = q.enqueue(
        generate_report_task,
        params.dict(),
        job_timeout=600,  # 10 minute timeout
    )

    return {
        "message": "Report generation started",
        "job_id": job.id,
    }

def generate_report_task(params: dict) -> str:
    """Celery task to generate report."""
    # This runs on job queue worker, not in web process
    report_data = expensive_report_generation(params)
    report_id = save_report(report_data)
    return str(report_id)

@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str) -> dict:
    """Get status of queued job."""
    job = q.fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": job.id,
        "status": job.get_status(),
        "result": job.result if job.is_finished else None,
        "error": str(job.exc_info) if job.is_failed else None,
    }
```

**Pros:**
- Persistent across restarts
- Horizontal scaling (multiple workers)
- Good monitoring tools available
- Production-grade

**Cons:**
- More infrastructure (Redis/RabbitMQ)
- Operational complexity

## Graceful Shutdown

Always ensure pending jobs complete or are handled on shutdown:

```python
import signal
from contextlib import asynccontextmanager

active_jobs = set()

@asynccontextmanager
async def tracked_job(job_id: UUID):
    """Context manager to track active job."""
    active_jobs.add(job_id)
    try:
        yield
    finally:
        active_jobs.remove(job_id)

async def shutdown_handler(signum, frame):
    """Handle graceful shutdown of jobs."""
    LOGGER.info(f"Received signal {signum}, shutting down gracefully...")
    LOGGER.info(f"Waiting for {len(active_jobs)} jobs to complete...")

    # Wait for all jobs to finish (with timeout)
    import asyncio
    try:
        await asyncio.wait_for(
            asyncio.gather(*[wait_for_job(j) for j in active_jobs]),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        LOGGER.warning("Timeout waiting for jobs - force stopping")

    # Cleanup
    await scheduler.close() if scheduler else None

# Register signal handlers
signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)
```

## Job Patterns

### Pattern: Long-Running Upload Processing

```python
@router.post("/documents/upload", status_code=202)
async def upload_document(
    file: UploadFile,
    session: SessionDep,
) -> DocumentRead:
    """Upload document with async processing."""
    from redact_api.main import scheduler

    # Save metadata immediately (user sees response)
    document = Document(
        filename=file.filename,
        content_type=file.content_type,
        size_bytes=file.size or 0,
        status="processing",
    )
    session.add(document)
    await session.commit()

    # Store uploaded file
    file_data = await file.read()
    await storage_service.upload(document.id, file_data, file.content_type)

    # Schedule async processing (indexing, virus scan, etc.)
    await scheduler.spawn(
        process_document_job(document.id),
        _name=f"process_doc_{document.id}",
    )

    return DocumentRead.model_validate(document)

async def process_document_job(document_id: UUID) -> None:
    """Process uploaded document asynchronously."""
    async with async_session_maker() as session:
        document = await get_document(session, document_id)

        try:
            # Download from storage
            file_data = await storage_service.download(document_id)

            # Extract text
            text = await extract_text_from_pdf(file_data)

            # Index for search
            await search_engine.index_document(document_id, text)

            # Update document
            document.status = "ready"
            document.indexed_at = datetime.utcnow()
            session.add(document)
            await session.commit()

            LOGGER.info(f"Document {document_id} processed successfully")
        except Exception as exc:
            LOGGER.error(f"Failed to process document {document_id}: {exc}")
            document.status = "error"
            document.error = str(exc)
            session.add(document)
            await session.commit()
```

### Pattern: Scheduled Cleanup

```python
import aioscheduler
from datetime import timedelta

async def schedule_cleanup_jobs(scheduler):
    """Schedule periodic cleanup tasks."""
    # Delete files older than 30 days
    await scheduler.spawn(
        cleanup_old_files_job(),
        _name="cleanup_old_files",
    )

    # Archive activity logs older than 90 days
    await scheduler.spawn(
        archive_old_activity_logs(),
        _name="archive_logs",
    )

async def cleanup_old_files_job() -> None:
    """Periodic job to clean up old uploaded files."""
    while True:
        try:
            cutoff = datetime.utcnow() - timedelta(days=30)

            async with async_session_maker() as session:
                # Find old files
                stmt = select(Document).where(
                    Document.created_at < cutoff,
                    Document.status == "archived",
                )
                result = await session.execute(stmt)
                old_docs = result.scalars().all()

                # Delete from storage
                for doc in old_docs:
                    await storage_service.delete(doc.id)
                    await session.delete(doc)

                await session.commit()

                LOGGER.info(f"Cleaned up {len(old_docs)} old files")

        except Exception as exc:
            LOGGER.error(f"Cleanup job failed: {exc}")

        # Run daily
        await asyncio.sleep(24 * 3600)
```

### Pattern: Batch Processing

```python
@router.post("/batch/process", status_code=202)
async def submit_batch(batch_data: BatchRequest) -> dict:
    """Submit batch for processing."""
    from redact_api.main import scheduler

    # Create batch record
    batch = Batch(
        name=batch_data.name,
        total_items=len(batch_data.items),
        status="pending",
    )
    session.add(batch)
    await session.commit()

    # Schedule processing
    await scheduler.spawn(
        process_batch_job(batch.id, batch_data.items),
        _name=f"batch_{batch.id}",
    )

    return {
        "batch_id": str(batch.id),
        "status": "queued",
        "total_items": batch.total_items,
    }

async def process_batch_job(batch_id: UUID, items: list[Any]) -> None:
    """Process batch with progress tracking."""
    async with async_session_maker() as session:
        batch = await get_batch(session, batch_id)
        batch.status = "processing"
        batch.started_at = datetime.utcnow()
        session.add(batch)
        await session.commit()

        try:
            processed = 0
            for i, item in enumerate(items):
                await process_item(item)
                processed += 1

                # Update progress every 10 items
                if i % 10 == 0:
                    batch.processed_items = processed
                    session.add(batch)
                    await session.commit()

            batch.status = "completed"
            batch.completed_at = datetime.utcnow()
            session.add(batch)
            await session.commit()

        except Exception as exc:
            LOGGER.error(f"Batch {batch_id} failed: {exc}")
            batch.status = "failed"
            batch.error = str(exc)
            session.add(batch)
            await session.commit()
```

## Monitoring

### Status Endpoint

```python
@router.get("/health/jobs")
async def job_health() -> dict:
    """Get health status of job system."""
    from redact_api.main import scheduler

    return {
        "scheduler": "healthy" if scheduler else "not_running",
        "active_jobs": len(active_jobs),
        "pending_jobs": len(scheduler._jobs) if scheduler else 0,
    }
```

### Job Metrics

```python
from prometheus_client import Counter, Gauge, Histogram

jobs_total = Counter(
    "jobs_total",
    "Total number of jobs executed",
    ["status"],  # success, failure
)

jobs_active = Gauge(
    "jobs_active",
    "Number of currently active jobs",
)

job_duration = Histogram(
    "job_duration_seconds",
    "Job execution time in seconds",
    ["job_name"],
)

@asynccontextmanager
async def tracked_job_with_metrics(job_name: str):
    """Track job execution with Prometheus metrics."""
    import time
    jobs_active.inc()
    start = time.perf_counter()

    try:
        yield
        jobs_total.labels(status="success").inc()
    except Exception:
        jobs_total.labels(status="failure").inc()
        raise
    finally:
        jobs_active.dec()
        duration = time.perf_counter() - start
        job_duration.labels(job_name=job_name).observe(duration)
```

## Best Practices

### 1. Always Have Timeouts

```python
# Set job timeout to prevent hanging
job = await scheduler.spawn(
    long_task(),
    _timeout=3600,  # 1 hour timeout
)
```

### 2. Implement Idempotency

```python
async def send_notification_job(user_id: UUID, notification_id: UUID) -> None:
    """Send notification with idempotency."""
    # Check if already sent
    if await is_notification_sent(notification_id):
        LOGGER.info(f"Notification {notification_id} already sent")
        return

    # Send notification
    await send_notification(user_id)

    # Mark as sent (idempotent key)
    await mark_notification_sent(notification_id)
```

### 3. Log Everything

```python
async def background_task(task_id: UUID) -> None:
    """Background task with comprehensive logging."""
    try:
        LOGGER.info(f"Task {task_id} started")
        result = await expensive_operation()
        LOGGER.info(f"Task {task_id} completed", extra={"result": result})
    except Exception as exc:
        LOGGER.exception(f"Task {task_id} failed", extra={
            "error": str(exc),
            "error_type": type(exc).__name__,
        })
```

## See Also

- [Resilience Patterns](resilience_patterns.md) - Retry/circuit breaker for jobs
- [Activity Logging](activity_logging.md) - Log job execution
