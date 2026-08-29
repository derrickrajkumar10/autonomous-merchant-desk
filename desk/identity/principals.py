"""The principals whose signatures the Desk will honour, and their public keys.

Check 2 asks whether a mandate carries *the principal's* signature. That question has
no answer until the Desk knows which key is the principal's, and a mandate cannot
supply it: a forger would simply name their own. So the key comes from here, resolved
through the principal the presenting agent registered under (ticket 02) rather than
through anything the mandate claims about itself.

That indirection is the point. It means a validly signed mandate from principal B,
presented by an agent registered to principal A, does not verify -- there is no path
by which the Desk reaches B's key while checking A's agent.

This is a small table on purpose. It is the Desk's configuration -- *whose
authorisations do we honour* -- not a record of anything a counterparty did, which is
why enrolling a principal writes no trail entry while registering an agent does.
Nothing here confers spend authority; a mandate does that, one deal at a time.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg import Connection
from psycopg_pool import ConnectionPool

from desk.identity.keys import PrincipalPublicKey
from desk.identity.schema import PRINCIPAL_KEY_ALG, PRINCIPAL_TABLE

_COLUMNS = "principal_id, public_key, key_algorithm, enrolled_at"


class PrincipalConflict(RuntimeError):
    """A principal already enrolled, presented with a different key.

    Rotation is a real need and this is not a refusal of it -- it is a refusal to do
    it silently, from a path whose only job is to look a key up.
    """


@dataclass(frozen=True)
class Principal:
    """A human whose signature the Desk will honour, and the key that proves it."""

    principal_id: str
    public_key: PrincipalPublicKey
    enrolled_at: datetime


class PrincipalDirectory:
    """Which humans the Desk honours mandates from, and under which key.

    Install the schema once with ``install_schema``; this class does not migrate.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def enrol(self, *, principal_id: str, public_key: PrincipalPublicKey) -> Principal:
        """Record this principal's public key. Idempotent for the same key.

        Refused two ways, and both are the same refusal wearing different clothes: a
        principal already enrolled coming back under a different key, and a key already
        enrolled coming back under a different principal. From here those are
        indistinguishable from a rotation, and a lookup table is the wrong place to be
        deciding which -- so neither happens by accident.
        """
        if not isinstance(public_key, PrincipalPublicKey):
            raise TypeError(
                "a principal enrols the key that signs its mandates, not an agent's. "
                "The principal's key authorises spending; the agent's key only proves "
                "who is asking."
            )
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise ValueError("a principal must be named")

        with self._pool.connection() as conn:
            # No conflict target named, so this covers the key's own UNIQUE constraint
            # as well as the principal's. Naming one would let the other surface as a
            # raw database exception -- with the key material in its message.
            conn.execute(
                f"INSERT INTO {PRINCIPAL_TABLE} ({_COLUMNS})"
                f" VALUES (%s, %s, %s, clock_timestamp())"
                f" ON CONFLICT DO NOTHING",
                (principal_id, public_key.base64url(), PRINCIPAL_KEY_ALG),
            )
            enrolled = self._find(conn, principal_id)

        if enrolled is None:
            # Nothing was written and this principal is not there, so the row that
            # blocked it was some other principal's holding this very key.
            raise PrincipalConflict(
                f"that key is already enrolled under a different principal, so "
                f"{principal_id!r} cannot take it. One key is one human."
            )
        if enrolled.public_key != public_key:
            raise PrincipalConflict(
                f"{principal_id!r} is already enrolled under a different key. Rotating "
                f"a principal's key is a deliberate act, not a side effect of a lookup."
            )
        return enrolled

    def find(self, principal_id: str) -> Principal | None:
        """The principal enrolled under this name, or ``None`` for a stranger."""
        with self._pool.connection() as conn:
            return self._find(conn, principal_id)

    @staticmethod
    def _find(conn: Connection[Any], principal_id: str) -> Principal | None:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM {PRINCIPAL_TABLE} WHERE principal_id = %s", (principal_id,)
        ).fetchone()
        return None if row is None else _to_principal(row)


def _to_principal(row: Sequence[Any]) -> Principal:
    principal_id, public_key, _algorithm, enrolled_at = row
    return Principal(
        principal_id=principal_id,
        public_key=PrincipalPublicKey.from_base64url(public_key),
        enrolled_at=enrolled_at,
    )
