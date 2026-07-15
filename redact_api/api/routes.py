"""API router composition for the service."""

from fastapi import APIRouter

from redact_api.api import (
    documents,
    health,
    jobs,
    memberships,
    organizations,
    ping,
    users,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(ping.router)
router.include_router(organizations.router)
router.include_router(users.router)
router.include_router(memberships.router)
router.include_router(documents.router)
router.include_router(jobs.router)
