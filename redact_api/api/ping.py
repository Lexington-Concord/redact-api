"""Simple ping endpoint for liveness checks."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/ping", tags=["health"])
async def ping() -> dict[str, str]:
    return {"message": "pong"}
