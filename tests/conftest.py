"""Test fixtures.

Every test in this suite runs against a real Postgres, because the properties under
test — a monotonic sequence under concurrent writes, structurally enforced
append-only, a closed enum the database itself refuses to widen — are properties of
the database and not of any object we could stand in for it.

Resolution order for that Postgres:

1. ``STITCHAI_TEST_DATABASE_URL`` if set (CI, or ``docker compose up postgres``).
2. An embedded server via the ``pgserver`` dev dependency.
3. Skip, saying which of the two to supply.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, install_schema


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    supplied = os.environ.get("STITCHAI_TEST_DATABASE_URL")
    if supplied:
        yield supplied
        return

    try:
        import pgserver
    except ImportError:  # pragma: no cover - depends on the local install
        pytest.skip(
            "no Postgres available: set STITCHAI_TEST_DATABASE_URL or install the "
            "'dev' extra, which brings an embedded server"
        )

    data_dir: Path = tmp_path_factory.mktemp("pgdata")
    server = pgserver.get_server(data_dir)
    try:
        yield server.get_uri()
    finally:
        server.cleanup()


@pytest.fixture
def pool(database_url: str) -> Iterator[ConnectionPool]:
    """A pool over a database holding nothing but a freshly installed trail."""
    with ConnectionPool(database_url, min_size=1, max_size=8, open=True) as pool:
        with pool.connection() as conn:
            conn.execute("DROP TABLE IF EXISTS audit_entry")
            conn.execute("DROP TYPE IF EXISTS audit_event_type")
            conn.execute("DROP TYPE IF EXISTS audit_reason_code")
            conn.execute("DROP FUNCTION IF EXISTS audit_entry_append_only")
            conn.execute("DROP FUNCTION IF EXISTS audit_entry_chain_link")
            install_schema(conn)
        yield pool


@pytest.fixture
def trail(pool: ConnectionPool) -> AuditTrail:
    return AuditTrail(pool)
