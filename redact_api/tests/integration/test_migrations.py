from collections.abc import Sequence

from alembic.runtime.migration import MigrationContext as AlembicMigrationContext
from pytest_alembic.runner import MigrationContext

# Constants for migration testing
FIRST_DIRECTIVE_INDEX = 0
BASE_MIGRATION = "base"


def test_upgrade(alembic_runner: MigrationContext) -> None:
    for head in alembic_runner.heads:
        alembic_runner.migrate_up_to(head)


def test_downgrade(alembic_runner: MigrationContext) -> None:
    for head in alembic_runner.heads:
        alembic_runner.migrate_up_to(head)
        alembic_runner.migrate_down_to(BASE_MIGRATION)
        alembic_runner.migrate_up_to(head)


def test_model_definitions_match_ddl(alembic_runner: MigrationContext) -> None:
    for head in alembic_runner.heads:
        alembic_runner.migrate_up_to(head)
    has_changes = False

    def check_revision(
        _context: AlembicMigrationContext,
        _revision: str,
        directives: Sequence[object],
    ) -> None:
        nonlocal has_changes
        script = directives[FIRST_DIRECTIVE_INDEX]
        has_changes = not script.upgrade_ops.is_empty()  # type: ignore[attr-defined]

    alembic_config = alembic_runner.config.alembic_config
    assert alembic_config is not None
    alembic_config.attributes["process_revision_directives"] = check_revision
    alembic_runner.generate_revision(autogenerate=True)
    assert not has_changes, "Schema drift detected. Generate a new Alembic migration."
