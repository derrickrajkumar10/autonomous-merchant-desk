"""Which presentations the Desk has already honoured, and the one place that changes.

One operation, and the shape of it is the whole design. ``claim`` does not ask whether
a nonce has been seen and then write it down; it writes it down and is told whether it
was already there. The two-step version reads correctly and is wrong under load: two
copies of one captured presentation arriving together both read *unseen*, both write,
and both are honoured. The single statement makes the primary key the arbiter, and a
uniqueness constraint has no race to lose.

Nothing here writes to the audit trail. Spending a nonce is not an event in its own
right -- it is what check 4 passing *means* -- so ``claim`` takes the caller's ``conn``
and the row commits with the entry that explains it, or neither does. That is the rule
``AgentRegistry.register`` follows, for the same reason: a nonce spent with no entry
saying why would be a refusal on the next presentation that nothing in the trail
accounts for.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from psycopg import Connection
from psycopg_pool import ConnectionPool

from desk.freshness.schema import TABLE


class NonceStore:
    """The Desk's record of every presentation it has honoured.

    Install the schema once with ``install_schema``; this class does not migrate.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    @contextmanager
    def transaction(self) -> Iterator[Connection[Any]]:
        """One transaction to claim a nonce and record the entry explaining it on.

        Exposed because check 4's pass *is* the nonce being spent, and the two writes
        have to be the same write. A caller with no entry to record can leave ``conn``
        off ``claim`` instead and let it take its own.
        """
        with self._pool.connection() as conn:
            yield conn

    def claim(
        self,
        nonce: str,
        *,
        agent_id: str,
        audience: str,
        presented_at: datetime,
        conn: Connection[Any] | None = None,
    ) -> bool:
        """Record this nonce as spent, and say whether it was already.

        ``True`` means the Desk had not seen it and now has. ``False`` means it had,
        which is a replay -- and the caller refuses rather than this method raising,
        because a replay is an ordinary refusal with a reason code and not a fault.

        ``presented_at`` is the hop's own ``iat``, kept so that ``forget`` can reason
        about the age of the *presentation* rather than about when the Desk got round
        to writing the row.
        """
        if conn is not None:
            return self._claim(conn, nonce, agent_id, audience, presented_at)
        with self._pool.connection() as pooled:
            return self._claim(pooled, nonce, agent_id, audience, presented_at)

    def has_seen(self, nonce: str, *, agent_id: str) -> bool:
        """Whether this agent has spent this nonce. A reader, for the trail and tests.

        Never the first half of a claim. Deciding on this and then writing is exactly
        the race ``claim`` exists to avoid.
        """
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {TABLE} WHERE agent_id = %s AND nonce = %s", (agent_id, nonce)
            ).fetchone()
        return row is not None

    def forget(self, *, presented_before: datetime, conn: Connection[Any] | None = None) -> int:
        """Drop nonces whose presentations are too old to be honoured anyway.

        The store would otherwise grow without bound, and the reason it may be trimmed
        at all is a coupling worth stating plainly, because getting it wrong reopens the
        hole this module closes:

        A forgotten nonce cannot be used to replay the presentation it came from,
        **provided that presentation would now be refused as stale**. That is only true
        while ``presented_before`` is at or before ``FreshnessPolicy.stale_before`` --
        which is why ``FreshnessCheck.forget_spent_nonces`` computes the instant from
        the policy and this method is not given a horizon of its own to guess at.

        What forgetting does allow is an agent minting a *new* hop that reuses an old
        nonce. That is a fresh signature over a fresh timestamp -- a new request, not a
        replayed one -- and it buys the agent nothing that an unused nonce would not.
        """
        if conn is not None:
            return self._forget(conn, presented_before)
        with self._pool.connection() as pooled:
            return self._forget(pooled, presented_before)

    @staticmethod
    def _claim(
        conn: Connection[Any], nonce: str, agent_id: str, audience: str, presented_at: datetime
    ) -> bool:
        row = conn.execute(
            f"INSERT INTO {TABLE} (agent_id, nonce, audience, presented_at, first_seen_at)"
            f" VALUES (%s, %s, %s, %s, clock_timestamp())"
            f" ON CONFLICT (agent_id, nonce) DO NOTHING"
            f" RETURNING nonce",
            (agent_id, nonce, audience, presented_at),
        ).fetchone()
        return row is not None

    @staticmethod
    def _forget(conn: Connection[Any], presented_before: datetime) -> int:
        cursor = conn.execute(f"DELETE FROM {TABLE} WHERE presented_at < %s", (presented_before,))
        return cursor.rowcount
