"""The nonce store: the properties that belong to the database rather than to the code.

These run against a real Postgres for the same reason the audit trail's do. "Two
concurrent claims of one nonce and exactly one wins" is a property of a primary key,
and a stand-in for the database would be a stand-in for the thing under test.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from psycopg.errors import CheckViolation
from psycopg_pool import ConnectionPool

from desk.freshness import MAX_CLAIM_CHARS, NonceStore

AUDIENCE = "stitchai-desk-under-test"


def _now() -> datetime:
    return datetime.now(UTC)


def test_the_first_claim_wins_and_the_second_is_told_it_lost(nonces: NonceStore) -> None:
    """The whole contract, in two calls."""
    assert nonces.claim("n", agent_id="agent-a", audience=AUDIENCE, presented_at=_now())
    assert not nonces.claim("n", agent_id="agent-a", audience=AUDIENCE, presented_at=_now())
    assert nonces.has_seen("n", agent_id="agent-a")


def test_two_claims_racing_the_same_nonce_produce_exactly_one_winner(
    pool: ConnectionPool,
) -> None:
    """The replay hole in miniature, run for real.

    A store that read *unseen* and then wrote would let both copies of one captured
    presentation through under load. Claiming is a single ``INSERT ... ON CONFLICT``,
    so the two attempts are settled by the index and one of them has to lose.
    """
    nonces = NonceStore(pool)
    presented_at = _now()

    with ThreadPoolExecutor(max_workers=8) as pool_of_threads:
        outcomes = list(
            pool_of_threads.map(
                lambda _: nonces.claim(
                    "contested", agent_id="agent-a", audience=AUDIENCE, presented_at=presented_at
                ),
                range(8),
            )
        )

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 7


def test_a_nonce_is_scoped_to_the_agent_that_spent_it(nonces: NonceStore) -> None:
    """One agent may not burn a value another was about to use.

    Nonces are the holder's to choose until the Desk issues challenges, so a global
    uniqueness rule would be a denial-of-service anyone could run by guessing. Scoping
    costs nothing: a hop captured from another agent is signed by that agent's key and
    is refused by check 2's key binding before check 4 ever reads a nonce out of it.
    """
    assert nonces.claim("shared", agent_id="agent-a", audience=AUDIENCE, presented_at=_now())

    assert nonces.claim("shared", agent_id="agent-b", audience=AUDIENCE, presented_at=_now())
    assert not nonces.has_seen("shared", agent_id="agent-c")


def test_the_database_refuses_a_nonce_the_check_should_never_have_let_through(
    nonces: NonceStore,
) -> None:
    """The bound said twice: once in ``key_binding``, once by the database.

    Only one of those two statements survives a bug in the other, which is the same
    arrangement as ``spent <= ceiling`` on the accumulator and the append-only trigger
    on the trail.
    """
    with pytest.raises(CheckViolation):
        nonces.claim(
            "n" * (MAX_CLAIM_CHARS + 1),
            agent_id="agent-a",
            audience=AUDIENCE,
            presented_at=_now(),
        )


def test_forgetting_is_bounded_by_when_the_presentation_was_made(nonces: NonceStore) -> None:
    """The horizon is read against the hop's own ``iat``, not against the write.

    A row written now for a hop stamped yesterday is a row about yesterday. Trimming by
    write time would keep nonces whose presentations are already refused as stale and
    drop ones whose presentations are not, which is the coupling backwards.
    """
    now = _now()
    nonces.claim("old", agent_id="agent-a", audience=AUDIENCE, presented_at=now - timedelta(days=1))
    nonces.claim("new", agent_id="agent-a", audience=AUDIENCE, presented_at=now)

    forgotten = nonces.forget(presented_before=now - timedelta(hours=1))

    assert forgotten == 1
    assert not nonces.has_seen("old", agent_id="agent-a")
    assert nonces.has_seen("new", agent_id="agent-a")
