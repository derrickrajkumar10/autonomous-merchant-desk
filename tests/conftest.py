"""Test fixtures.

Every test in this suite runs against a real Postgres, because the properties under
test — a monotonic sequence under concurrent writes, structurally enforced
append-only, a closed enum the database itself refuses to widen, a ceiling the
database will not let a row breach — are properties of the database and not of any
object we could stand in for it.

Resolution order for that Postgres:

1. ``STITCHAI_TEST_DATABASE_URL`` if set (CI, or ``docker compose up postgres``).
2. An embedded server via the ``pgserver`` dev dependency.
3. Skip, saying which of the two to supply.

The cast of characters below — a principal with a wallet, an agent with its own
keypair, both known to the Desk — is shared by the mandate and spend suites, because
both enter the way the real thing does. Nothing writes a mandate by hand or reaches
into a table, since a buyer agent could do neither.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail
from desk.audit import install_schema as install_audit_schema
from desk.freshness import install_schema as install_freshness_schema
from desk.identity import AgentIdentity, AgentRegistry, PrincipalDirectory
from desk.identity import install_schema as install_identity_schema
from desk.mandate import MandateCheck
from desk.spend import install_schema as install_spend_schema
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

PRINCIPAL_ID = "principal-asha"

#: One hour, which is roughly the "smallest value that lets the agent finish the task"
#: AP2 recommends, and long enough that a slow test does not expire mid-run.
AN_HOUR = 3600


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
    """A pool over a database holding nothing but a freshly installed Desk."""
    with ConnectionPool(database_url, min_size=1, max_size=8, open=True) as pool:
        with pool.connection() as conn:
            # CASCADE, because the per-consumer views sit on the table.
            conn.execute("DROP TABLE IF EXISTS audit_entry CASCADE")
            conn.execute("DROP TYPE IF EXISTS audit_event_type")
            conn.execute("DROP TYPE IF EXISTS audit_reason_code")
            conn.execute("DROP FUNCTION IF EXISTS audit_entry_append_only")
            conn.execute("DROP FUNCTION IF EXISTS audit_entry_chain_link")
            conn.execute("DROP TABLE IF EXISTS agent_identity")
            conn.execute("DROP TABLE IF EXISTS principal_key")
            conn.execute("DROP TABLE IF EXISTS mandate_spend")
            conn.execute("DROP TABLE IF EXISTS seen_nonce")
            install_audit_schema(conn)
            install_identity_schema(conn)
            install_spend_schema(conn)
            install_freshness_schema(conn)
        yield pool


@pytest.fixture
def trail(pool: ConnectionPool) -> AuditTrail:
    return AuditTrail(pool)


@pytest.fixture
def wallet() -> PrincipalKeypair:
    """The principal's keypair, in the wallet where it belongs and nowhere else."""
    return PrincipalKeypair.generate()


@pytest.fixture
def principals(pool: ConnectionPool, wallet: PrincipalKeypair) -> PrincipalDirectory:
    directory = PrincipalDirectory(pool)
    directory.enrol(principal_id=PRINCIPAL_ID, public_key=wallet.public_key)
    return directory


@pytest.fixture
def mandate_check(principals: PrincipalDirectory, trail: AuditTrail) -> MandateCheck:
    return MandateCheck(principals, trail)


@pytest.fixture
def agent() -> AgentKeypair:
    return AgentKeypair.generate()


@pytest.fixture
def identity(pool: ConnectionPool, trail: AuditTrail, agent: AgentKeypair) -> AgentIdentity:
    """The agent as check 1 would hand it on: registered, and authenticated."""
    return AgentRegistry(pool, trail).register(
        public_key=agent.public_key, principal_id=PRINCIPAL_ID
    )
