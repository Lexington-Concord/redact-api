"""Pytest fixtures for async API testing with Postgres + Alembic.

This module provides pytest-xdist compatible fixtures for parallel test execution.
Each xdist worker gets its own database (app_test_gw0, app_test_gw1, etc.) to
prevent data conflicts between parallel test runs.
"""

import asyncio
import contextlib
import os
import socket
from collections.abc import AsyncGenerator, Generator
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import filelock
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends, Request
from httpx import ASGITransport, AsyncClient
from psycopg import sql
from pytest_docker.plugin import DockerComposeExecutor, Services
from sqlalchemy import bindparam, create_engine, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from redact_api.core.auth import AuthMiddleware, CurrentUser, _parse_user_headers, get_user_from_headers
from redact_api.core.tenants import TenantContext
from redact_api.db import session as db_session
from redact_api.db.session import create_session_maker, get_session
from redact_api.main import app
from redact_api.models.membership import Membership, MembershipRole
from redact_api.models.organization import Organization
from redact_api.models.user import User

# Import settings fixtures for test isolation and pytest-xdist compatibility
from redact_api.tests.fixtures.settings import (  # noqa: F401
    test_settings,
    test_settings_factory,
    test_settings_with_activity_logging_disabled,
    test_settings_with_auth,
    test_settings_with_storage,
)

# Port constants
POSTGRES_PORT = 5432
SOCKET_TIMEOUT_SECONDS = 1
DOCKER_TIMEOUT_SECONDS = 30.0
DOCKER_PAUSE_SECONDS = 0.5


# =============================================================================
# pytest-xdist Docker Coordination
# =============================================================================


@pytest.fixture(scope="session")
def docker_compose_project_name(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Generate a consistent Docker project name shared across all xdist workers.

    By default, pytest-docker uses os.getpid() for the project name, which causes
    each xdist worker to create its own Docker network. This exhausts Docker's
    default address pool (~16 networks) when running with many parallel workers.

    This fixture uses FileLock to coordinate: the first worker generates a project
    name and saves it to a shared file; subsequent workers read from that file.

    Args:
        tmp_path_factory: pytest temp path factory for cross-worker coordination

    Returns:
        A consistent project name like "pytest_abc123" shared across all workers
    """
    # Get root tmp dir shared across workers
    root_tmp = tmp_path_factory.getbasetemp().parent
    lock_file = root_tmp / "docker_project.lock"
    name_file = root_tmp / "docker_project_name.txt"

    with filelock.FileLock(lock_file):
        if name_file.exists():
            # Another worker already generated the name - read it
            return name_file.read_text().strip()
        # First worker - generate a unique project name based on the shared tmp dir
        # Use the tmp dir basename which is consistent across workers (pytest-XXX)
        project_name = f"pytest_{root_tmp.name}"
        name_file.write_text(project_name)
        return project_name


@pytest.fixture(scope="session")
def docker_services(  # noqa: PLR0913 - pytest fixture params can't be restructured
    docker_compose_command: str,
    docker_compose_file: str,
    docker_compose_project_name: str,
    docker_setup: str,
    docker_cleanup: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Services]:
    """Start Docker Compose services with xdist-safe coordination.

    This fixture overrides pytest-docker's docker_services to add FileLock
    coordination. Only the first worker starts Docker Compose; other workers
    wait for the startup file marker and then connect to the existing container.

    Uses reference counting to track active workers - the last worker to finish
    performs the cleanup.

    Args:
        docker_compose_command: Docker compose command (e.g., "docker compose")
        docker_compose_file: Path to docker-compose.yml
        docker_compose_project_name: Shared project name across workers
        docker_setup: Docker setup command (e.g., "up --build --wait")
        docker_cleanup: Docker cleanup command (e.g., "down -v")
        tmp_path_factory: pytest temp path factory for cross-worker coordination

    Yields:
        Services object from pytest-docker for port lookups
    """
    docker_compose = DockerComposeExecutor(docker_compose_command, docker_compose_file, docker_compose_project_name)

    # Get root tmp dir shared across workers
    root_tmp = tmp_path_factory.getbasetemp().parent
    lock_file = root_tmp / "docker_startup.lock"
    ready_file = root_tmp / "docker_ready.txt"
    refcount_file = root_tmp / "docker_refcount.txt"

    # Startup: increment refcount and start Docker if first worker
    with filelock.FileLock(lock_file):
        # Increment reference count
        count = int(refcount_file.read_text()) if refcount_file.exists() else 0
        count += 1
        refcount_file.write_text(str(count))

        if not ready_file.exists():
            # First worker - start Docker
            if docker_setup:
                setup_commands = [docker_setup] if isinstance(docker_setup, str) else docker_setup
                for command in setup_commands:
                    docker_compose.execute(command)
            ready_file.write_text("ready")

    # All workers can now use the services
    yield Services(docker_compose)

    # Teardown: decrement refcount and cleanup if last worker
    with filelock.FileLock(lock_file):
        count = int(refcount_file.read_text()) if refcount_file.exists() else 1
        count -= 1
        refcount_file.write_text(str(count))

        if count == 0:
            # Last worker - clean up Docker
            if docker_cleanup:
                cleanup_commands = [docker_cleanup] if isinstance(docker_cleanup, str) else docker_cleanup
                for command in cleanup_commands:
                    docker_compose.execute(command)
            # Clean up marker files for next test run
            ready_file.unlink(missing_ok=True)
            refcount_file.unlink(missing_ok=True)


# =============================================================================
# pytest-xdist Database Isolation Helpers
# =============================================================================


def get_worker_database_name(worker_id: str) -> str:
    """Return database name for xdist worker.

    For pytest-xdist, each worker (gw0, gw1, etc.) gets its own database
    to prevent data conflicts during parallel test execution.

    Args:
        worker_id: pytest-xdist worker ID ("master" when not using xdist)

    Returns:
        Database name: "app_test" for master, "app_test_gw0" etc. for workers
    """
    if worker_id == "master" or not worker_id:
        return "app_test"
    return f"app_test_{worker_id}"


def create_database_if_not_exists(host: str, port: int, db_name: str) -> None:
    """Create database using sync psycopg connection to postgres database.

    Handles race conditions where multiple workers may try to create the
    same database simultaneously by catching DuplicateDatabase errors.

    Args:
        host: PostgreSQL host
        port: PostgreSQL port
        db_name: Name of database to create
    """
    conn_str = f"host={host} port={port} user=app password=app dbname=postgres"
    # Another worker may have created it first - suppress that specific error
    with (
        psycopg.connect(conn_str, autocommit=True) as conn,
        contextlib.suppress(psycopg.errors.DuplicateDatabase),
    ):
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))


def drop_database_if_exists(host: str, port: int, db_name: str) -> None:
    """Drop database at session end for cleanup.

    Terminates any active connections to the database before dropping.

    Args:
        host: PostgreSQL host
        port: PostgreSQL port
        db_name: Name of database to drop
    """
    conn_str = f"host={host} port={port} user=app password=app dbname=postgres"
    with psycopg.connect(conn_str, autocommit=True) as conn:
        # Terminate active connections to the database
        conn.execute(
            sql.SQL("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s"),
            (db_name,),
        )
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name)))


@pytest.fixture(scope="session")
def database_url(
    docker_ip: str,
    docker_services: object,
    worker_id: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[str]:
    """Get database URL with per-worker isolation and shared Docker container.

    Uses FileLock to ensure only one worker starts Docker Compose.
    All workers share the same Postgres container but get separate databases.

    For pytest-xdist compatibility, creates a separate database for each worker:
    - master (no xdist): app_test
    - gw0: app_test_gw0
    - gw1: app_test_gw1
    - etc.

    Sets DATABASE_URL environment variable for Alembic migrations (which run in
    subprocess), but does NOT mutate the global settings singleton to preserve
    pytest-xdist compatibility. Individual test sessions create fresh Settings
    instances via test_settings fixture.

    Args:
        docker_ip: Docker host IP from docker_services
        docker_services: pytest-docker services fixture
        worker_id: pytest-xdist worker ID ("master" when not using xdist)
        tmp_path_factory: pytest temp path factory for cross-worker coordination

    Yields:
        Database URL for test Postgres instance
    """
    # Get root tmp dir shared across workers for coordination files
    root_tmp = tmp_path_factory.getbasetemp().parent
    lock_file = root_tmp / "postgres.lock"
    port_file = root_tmp / "postgres_port.txt"

    with filelock.FileLock(lock_file):
        if port_file.exists():
            # Another worker already started Docker - read the port
            port = int(port_file.read_text())
        else:
            # First worker - start Docker and save port
            port = docker_services.port_for("postgres", POSTGRES_PORT)  # type: ignore[attr-defined]

            def is_responsive() -> bool:
                try:
                    socket.create_connection((docker_ip, port), timeout=SOCKET_TIMEOUT_SECONDS).close()
                except OSError:
                    return False
                return True

            docker_services.wait_until_responsive(  # type: ignore[attr-defined]
                timeout=DOCKER_TIMEOUT_SECONDS,
                pause=DOCKER_PAUSE_SECONDS,
                check=is_responsive,
            )
            port_file.write_text(str(port))

    # Get worker-specific database name
    db_name = get_worker_database_name(worker_id)

    # Create the database if it doesn't exist
    create_database_if_not_exists(docker_ip, port, db_name)

    # Build URL with worker-specific database
    url = f"postgresql+asyncpg://app:app@{docker_ip}:{port}/{db_name}"
    os.environ["DATABASE_URL"] = url

    yield url

    # Cleanup: drop worker database (skip for master to allow debugging)
    if worker_id != "master":
        drop_database_if_exists(docker_ip, port, db_name)


@pytest.fixture(scope="session")
def alembic_config(database_url: str) -> Config:
    # Find alembic.ini at project root (3 levels up from conftest.py)
    project_root = Path(__file__).parent.parent.parent
    alembic_ini_path = project_root / "alembic.ini"

    config = Config(str(alembic_ini_path))
    config.set_main_option(
        "sqlalchemy.url",
        database_url.replace("postgresql+asyncpg", "postgresql+psycopg"),
    )
    return config


@pytest.fixture(scope="session")
def alembic_engine(database_url: str) -> Generator[Engine]:
    url = make_url(database_url)
    if url.drivername.endswith("asyncpg"):
        url = url.set(drivername=url.drivername.replace("asyncpg", "psycopg"))
    engine = create_engine(url)
    yield engine
    engine.dispose()


def run_migrations(config: Config, engine: Engine) -> None:
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        try:
            command.upgrade(config, "head")
        finally:
            config.attributes.pop("connection", None)
        connection.commit()


async def truncate_tables(engine: AsyncEngine, alembic_config: Config, alembic_engine: Engine) -> None:
    table_names = [table.name for table in SQLModel.metadata.sorted_tables]
    if not table_names:
        return
    async with engine.begin() as connection:
        result = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN :names").bindparams(
                bindparam("names", expanding=True)
            ),
            {"names": table_names},
        )
        existing = [row[0] for row in result.fetchall()]
    if not existing:
        await asyncio.to_thread(run_migrations, alembic_config, alembic_engine)
        async with engine.begin() as connection:
            result = await connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN :names").bindparams(
                    bindparam("names", expanding=True)
                ),
                {"names": table_names},
            )
            existing = [row[0] for row in result.fetchall()]
    if not existing:
        return
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE " + ", ".join(existing) + " RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
async def engine(
    database_url: str,
    alembic_config: Config,
    alembic_engine: Engine,
) -> AsyncGenerator[AsyncEngine]:
    """Create async database engine for test session.

    This fixture is pytest-xdist compatible: it does NOT mutate the global
    db_session.engine or db_session.async_session_maker. Instead, tests
    use the fixtures directly and client fixtures inject them into app.state.

    Args:
        database_url: Worker-specific database URL from database_url fixture
        alembic_config: Alembic configuration
        alembic_engine: Sync engine for running migrations

    Yields:
        AsyncEngine for this test worker's database
    """
    # Run migrations on the worker's database
    await asyncio.to_thread(run_migrations, alembic_config, alembic_engine)

    # Create async engine for this worker (NullPool avoids connection leaks)
    test_engine = create_async_engine(database_url, poolclass=NullPool)

    # Update global session maker to use test engine for backward compatibility
    # with code that accesses db_session.async_session_maker directly
    # (e.g., activity_logging.py, tenants.py)
    db_session.engine = test_engine
    db_session.async_session_maker = create_session_maker(test_engine)

    yield test_engine

    # Cleanup
    await truncate_tables(test_engine, alembic_config, alembic_engine)
    await test_engine.dispose()


@pytest.fixture
def session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
async def session(
    session_maker: async_sessionmaker[AsyncSession],
    reset_db: None,  # noqa: ARG001 - Ensure DB reset happens first
) -> AsyncGenerator[AsyncSession]:
    """Provide a database session for tests that need direct database access."""
    async with session_maker() as session:
        yield session


@pytest.fixture(autouse=True)
async def reset_db(engine: AsyncEngine, alembic_config: Config, alembic_engine: Engine) -> None:
    await truncate_tables(engine, alembic_config, alembic_engine)


class TestAuthMiddleware(BaseHTTPMiddleware):
    """Test middleware that injects a test user and tenant context into all requests.

    Supports header-based user and organization specification for test isolation:
    - X-Test-User-ID: UUID of the user to authenticate as
    - X-Test-Org-ID: UUID of the organization to scope to

    If headers are not provided, uses default test user.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Any,  # noqa: ANN401
    ) -> Response:
        """Inject test user and tenant context into request state.

        Phase 4 update: Also injects Oathkeeper-style headers (X-User-ID, X-Email, X-Selected-Org)
        so that get_user_from_headers dependency can validate organization membership.

        Checks for X-Test-User-ID and X-Test-Org-ID headers to allow tests to
        specify which user is making the request. If headers are provided, uses
        those values. Otherwise uses default test user.

        Looks up the user's actual role from the database for proper RBAC testing.
        """
        # Try to get user and org from headers (for role-based testing)
        user_id_header = request.headers.get("X-Test-User-ID")
        org_id_header = request.headers.get("X-Test-Org-ID")

        if user_id_header and org_id_header:
            # Test-specified user
            test_user = CurrentUser(
                id=UUID(user_id_header),
                email="test@example.com",
                organization_id=UUID(org_id_header),
            )
        else:
            # Default fallback test user
            test_user = CurrentUser(
                id=UUID("00000000-0000-0000-0000-000000000001"),
                email="testuser@example.com",
                organization_id=UUID("00000000-0000-0000-0000-000000000000"),
            )

        # Phase 4: Inject Oathkeeper-style headers for get_user_from_headers validation
        # Modify the scope's headers list directly (lowercase keys as per ASGI spec)
        scope = request.scope
        headers_list = list(scope["headers"])
        headers_list.append((b"x-user-id", str(test_user.id).encode()))
        headers_list.append((b"x-email", test_user.email.encode()))
        if test_user.organization_id:
            headers_list.append((b"x-selected-org", str(test_user.organization_id).encode()))
        scope["headers"] = headers_list

        request.state.user = test_user

        # Look up the user's actual role from the database for proper RBAC testing
        async with request.app.state.async_session_maker() as session:
            result = await session.execute(
                select(Membership.role)
                .where(Membership.user_id == test_user.id)
                .where(Membership.organization_id == test_user.organization_id)
            )
            user_role = result.scalar_one_or_none()

            # Default to OWNER if no membership exists (for backwards compatibility with fixtures)
            if user_role is None:
                user_role = MembershipRole.OWNER

            # Set tenant context with actual role from database
            request.state.tenant = TenantContext(
                organization_id=test_user.organization_id,  # type: ignore[arg-type]
                user_id=test_user.id,
                role=user_role,
            )

        return await call_next(request)


@pytest.fixture
async def client_bypass_auth(
    engine: AsyncEngine,
    session_maker: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient]:
    """Test client that injects Oathkeeper-style auth headers.

    Simulates Oathkeeper API gateway by injecting X-User-ID and X-Email headers
    that the backend expects from the header-based authentication.

    Default test user:
    - X-User-ID: 00000000-0000-0000-0000-000000000001
    - X-Email: testuser@example.com
    """

    async def get_session_override() -> AsyncGenerator[AsyncSession]:
        async with session_maker() as session:
            yield session

    # Set app.state for pytest-xdist compatibility (lifespan pattern)
    app.state.engine = engine
    app.state.async_session_maker = session_maker

    # Override session dependency
    app.dependency_overrides[get_session] = get_session_override

    # Phase 4: Override get_user_from_headers to bypass org membership validation in tests
    # TestAuthMiddleware already validates membership when setting request.state.user
    async def get_user_from_headers_test_override(
        parsed_headers: Annotated[tuple[UUID, str, UUID | None], Depends(_parse_user_headers)],
    ) -> CurrentUser:
        """Test override that skips database membership validation.

        TestAuthMiddleware already ensures the default test user has a valid
        membership to the test organization. This override bypasses the database
        query while still parsing headers correctly.

        For tests that override headers (X-User-ID, X-Email), we construct a new
        CurrentUser from the parsed headers rather than using request.state.user.
        """
        user_id, email, organization_id = parsed_headers
        return CurrentUser(id=user_id, email=email, organization_id=organization_id)

    # We need both dependencies - parse headers normally, but skip DB validation
    app.dependency_overrides[get_user_from_headers] = get_user_from_headers_test_override

    # Reset middleware stack to allow modifications
    app.middleware_stack = None

    # Remove AuthMiddleware if present and add TestAuthMiddleware that injects test user
    app.user_middleware = [m for m in app.user_middleware if m.cls != AuthMiddleware]
    app.add_middleware(TestAuthMiddleware)

    # Need to rebuild the middleware stack
    app.middleware_stack = app.build_middleware_stack()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Inject default Oathkeeper headers for all requests
        # Phase 4: Added X-Selected-Org header for organization context
        client.headers.update(
            {
                "X-User-ID": "00000000-0000-0000-0000-000000000001",
                "X-Email": "testuser@example.com",
                "X-Selected-Org": "00000000-0000-0000-0000-000000000000",
            }
        )
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def authenticated_client(
    engine: AsyncEngine,
    session_maker: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient]:
    """Test client that keeps AuthMiddleware and requires valid JWT tokens.

    Use this fixture for tests that need to verify auth behavior. Set Authorization
    header with a valid JWT token.

    Example:
        async def test_protected_endpoint(authenticated_client):
            response = await authenticated_client.get(
                "/protected",
                headers={"Authorization": f"Bearer {valid_token}"}
            )
            assert response.status_code == 200
    """

    async def get_session_override() -> AsyncGenerator[AsyncSession]:
        async with session_maker() as session:
            yield session

    # Set app.state for pytest-xdist compatibility (lifespan pattern)
    app.state.engine = engine
    app.state.async_session_maker = session_maker

    # Override session dependency
    app.dependency_overrides[get_session] = get_session_override

    # Reset middleware stack to allow modifications
    app.middleware_stack = None

    # Keep AuthMiddleware but rebuild stack to apply overrides
    app.middleware_stack = app.build_middleware_stack()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def client(
    engine: AsyncEngine,
    session_maker: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient]:
    """HTTP client that injects Oathkeeper-style auth headers.

    Simulates Oathkeeper API gateway by injecting X-User-ID and X-Email headers
    that the backend expects from the header-based authentication.

    Default test user:
    - X-User-ID: 00000000-0000-0000-0000-000000000001
    - X-Email: testuser@example.com

    To test with different user:
        response = await client.get(
            "/users/123",
            headers={
                "X-User-ID": "different-user-id",
                "X-Email": "other@example.com"
            }
        )

    Note: These headers are automatically injected into all requests made
    through this client. Override by passing custom headers as shown above.
    """

    async def get_session_override() -> AsyncGenerator[AsyncSession]:
        async with session_maker() as session:
            yield session

    # Set app.state for pytest-xdist compatibility (lifespan pattern)
    app.state.engine = engine
    app.state.async_session_maker = session_maker

    # Override session dependency
    app.dependency_overrides[get_session] = get_session_override

    # Phase 4: Override get_user_from_headers to bypass org membership validation in tests
    # TestAuthMiddleware already validates membership when setting request.state.user
    async def get_user_from_headers_test_override(
        parsed_headers: Annotated[tuple[UUID, str, UUID | None], Depends(_parse_user_headers)],
    ) -> CurrentUser:
        """Test override that skips database membership validation.

        TestAuthMiddleware already ensures the default test user has a valid
        membership to the test organization. This override bypasses the database
        query while still parsing headers correctly.

        For tests that override headers (X-User-ID, X-Email), we construct a new
        CurrentUser from the parsed headers rather than using request.state.user.
        """
        user_id, email, organization_id = parsed_headers
        return CurrentUser(id=user_id, email=email, organization_id=organization_id)

    # We need both dependencies - parse headers normally, but skip DB validation
    app.dependency_overrides[get_user_from_headers] = get_user_from_headers_test_override

    # Reset middleware stack to allow modifications
    app.middleware_stack = None

    # Remove AuthMiddleware if present and add TestAuthMiddleware that injects test user
    app.user_middleware = [m for m in app.user_middleware if m.cls != AuthMiddleware]
    app.add_middleware(TestAuthMiddleware)

    # Need to rebuild the middleware stack
    app.middleware_stack = app.build_middleware_stack()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Inject default Oathkeeper headers for all requests
        # Phase 4: Added X-Selected-Org header for organization context
        client.headers.update(
            {
                "X-User-ID": "00000000-0000-0000-0000-000000000001",
                "X-Email": "testuser@example.com",
                "X-Selected-Org": "00000000-0000-0000-0000-000000000000",
            }
        )
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(client: AsyncClient) -> dict[str, Any]:
    """Create a test user and return user data.

    Note: Uses a unique email to avoid conflict with the default test user
    created by default_auth_user_in_org fixture (testuser@example.com).
    """
    response = await client.post(
        "/users",
        json={
            "name": "Test User",
            "email": "fixture-test-user@example.com",
        },
    )
    assert response.status_code == HTTPStatus.CREATED
    return response.json()


@pytest.fixture
async def test_organization(client: AsyncClient) -> dict[str, Any]:
    """Create a test organization and return organization data.

    Note: Uses client_bypass_auth which bypasses AuthMiddleware,
    so no membership creation is needed for the default test user.
    """
    response = await client.post(
        "/organizations",
        json={"name": "Test Organization"},
    )
    assert response.status_code == HTTPStatus.CREATED
    return response.json()


@pytest.fixture
async def multiple_users(client: AsyncClient) -> list[dict[str, Any]]:
    """Create multiple test users with varying data."""
    users = []
    for i in range(3):
        response = await client.post(
            "/users",
            json={
                "name": f"User {i}",
                "email": f"user{i}@example.com",
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        users.append(response.json())
    return users


@pytest.fixture
async def user_with_org(
    client: AsyncClient,
    test_user: dict[str, Any],
    test_organization: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a user with an organization membership."""
    # Create membership
    membership_response = await client.post(
        "/memberships",
        json={
            "user_id": test_user["id"],
            "organization_id": test_organization["id"],
        },
    )
    assert membership_response.status_code == HTTPStatus.CREATED

    # Return user and org
    return test_user, test_organization


@pytest.fixture(autouse=True)
async def default_auth_user_in_org(
    session_maker: async_sessionmaker[AsyncSession],
    reset_db: None,  # noqa: ARG001 - Ensure DB is reset before creating default user/org
) -> None:
    """Ensure default test user and default org exist with OWNER membership.

    This fixture creates the user/org/membership required for tests that rely on
    the default auth middleware credentials to have RBAC permissions.

    Runs automatically for all tests (autouse=True) so tests don't need to declare it.
    """
    test_org_id = UUID("00000000-0000-0000-0000-000000000000")
    test_user_id = UUID("00000000-0000-0000-0000-000000000001")

    async with session_maker() as session:
        # Create test user if it doesn't exist
        user_result = await session.execute(select(User).where(User.id == test_user_id))
        if not user_result.scalar_one_or_none():
            test_user = User(
                id=test_user_id,
                email="testuser@example.com",
                name="Test User",
            )
            session.add(test_user)
            await session.commit()

        # Create test organization if it doesn't exist
        org_result = await session.execute(select(Organization).where(Organization.id == test_org_id))
        if not org_result.scalar_one_or_none():
            test_org = Organization(id=test_org_id, name="Test Organization")
            session.add(test_org)
            await session.commit()

        # Create default membership for test user with OWNER role
        membership_result = await session.execute(
            select(Membership).where(
                Membership.user_id == test_user_id,
                Membership.organization_id == test_org_id,
            )
        )
        if not membership_result.scalar_one_or_none():
            test_membership = Membership(
                user_id=test_user_id,
                organization_id=test_org_id,
                role=MembershipRole.OWNER,
            )
            session.add(test_membership)
            await session.commit()


# =============================================================================
# HTTP Client Mock Fixtures for Auth Tests
# =============================================================================


@pytest.fixture
def mock_http_client_factory() -> Generator[Any]:
    """Factory for creating properly configured mock HTTP clients.

    Creates mock HTTP clients that correctly implement the async context manager
    protocol to avoid RuntimeWarnings from unawaited coroutines.

    Usage:
        def test_auth0_success(mock_http_client_factory):
            mock_client = mock_http_client_factory(
                get_response={"sub": "user-123", "email": "test@example.com"},
                get_status=200,
            )
            with patch("redact_api.core.auth.http_client", return_value=mock_client):
                # test code

    Args:
        get_response: JSON response for GET requests
        post_response: JSON response for POST requests
        get_status: HTTP status code for GET responses (default: 200)
        post_status: HTTP status code for POST responses (default: 200)
        get_side_effect: Exception to raise on GET (for error testing)
        post_side_effect: Exception to raise on POST (for error testing)

    Returns:
        Factory function that creates configured mock clients
    """

    def _create_mock(  # noqa: PLR0913 - factory needs all params for flexibility
        get_response: dict[str, Any] | None = None,
        post_response: dict[str, Any] | None = None,
        get_status: int = 200,
        post_status: int = 200,
        get_side_effect: Exception | None = None,
        post_side_effect: Exception | None = None,
    ) -> MagicMock:
        mock_client = AsyncMock()

        # Configure async context manager properly to avoid RuntimeWarnings
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # Configure GET
        if get_side_effect:
            mock_client.get = AsyncMock(side_effect=get_side_effect)
        else:
            get_mock_response = MagicMock()
            get_mock_response.status_code = get_status
            get_mock_response.json.return_value = get_response or {}
            get_mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=get_mock_response)

        # Configure POST
        if post_side_effect:
            mock_client.post = AsyncMock(side_effect=post_side_effect)
        else:
            post_mock_response = MagicMock()
            post_mock_response.status_code = post_status
            post_mock_response.json.return_value = post_response or {}
            post_mock_response.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=post_mock_response)

        return mock_client

    return _create_mock  # type: ignore[return-value]
