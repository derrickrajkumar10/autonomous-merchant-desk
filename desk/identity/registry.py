"""The agent registry: who the Desk has met, and under whose authority they claim to act.

Registration is cheap and confers almost nothing. It buys an identity, not trust: a
newly registered agent sits at the bottom rung under the strictest scrutiny, and
nothing on ``AgentIdentity`` can be read as authority to spend. What it does buy is
accountability -- from here on, behaviour attaches to a key.

The identity is the key's own thumbprint (ADR-0011), so one key is one identity for
ever and a returning agent keeps the identity its key already earned.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn

from psycopg import Connection
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, EventType, ReasonCode
from desk.identity.jws import AGENT_REQUEST_ALG
from desk.identity.keys import AgentPublicKey
from desk.identity.schema import TABLE

_COLUMNS = "agent_id, public_key, key_algorithm, principal_id, registered_at"


class RegistrationConflict(RuntimeError):
    """A key already registered, presented as something other than what it is."""


@dataclass(frozen=True)
class AgentIdentity:
    """A registered agent: a stable handle across sessions, and nothing more.

    Deliberately four fields. A ceiling, a trust score or a balance living here would
    make identity look like authority, which is the confusion this whole subsystem is
    built to prevent. Those belong to the reputation ladder and the spend accumulator,
    each keyed by ``agent_id``.
    """

    agent_id: str
    public_key: AgentPublicKey
    principal_id: str
    registered_at: datetime


class AgentRegistry:
    """The Desk's record of every agent it has issued an identity to.

    Install the schema once with ``install_schema``; this class does not migrate.
    """

    def __init__(self, pool: ConnectionPool, trail: AuditTrail) -> None:
        self._pool = pool
        self._trail = trail

    def register(self, *, public_key: AgentPublicKey, principal_id: str) -> AgentIdentity:
        """Issue an identity for this key, and record that the Desk did so.

        Idempotent for a returning agent: the same key under the same principal gets
        the identity it already has, and the trail is not told twice about one arrival.

        The row and its trail entry commit together or not at all. A registered agent
        the trail never saw arrive, or an arrival recorded for an agent that was never
        registered, are both the trail disagreeing with reality.

        Refused when a key already registered comes back naming a different principal.
        A public key is public, so this is a thing a stranger can attempt: it is an
        attempt to move an identity's stated source of authority, and it is recorded
        under ``agent_principal_mismatch`` rather than merely raised.
        """
        if not isinstance(public_key, AgentPublicKey):
            raise TypeError(
                "an agent registers its own key, not a principal's. The principal's key "
                "authorises spending; the agent's key only proves who is asking."
            )
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise ValueError("an agent must name the principal it acts for")

        agent_id = public_key.agent_id

        with self._pool.connection() as conn:
            registered = self._find(conn, agent_id)
            if registered is not None:
                return self._returning_agent(registered, principal_id)

            row = conn.execute(
                f"INSERT INTO {TABLE} ({_COLUMNS})"
                f" VALUES (%s, %s, %s, %s, clock_timestamp())"
                f" ON CONFLICT DO NOTHING"
                f" RETURNING {_COLUMNS}",
                (agent_id, public_key.base64url(), AGENT_REQUEST_ALG, principal_id),
            ).fetchone()
            if row is None:
                # Another writer registered this key between the read and the insert.
                # The conflict is on whichever unique constraint that writer reached
                # first, so no target is named; read-committed means its row is visible
                # now that it has committed.
                registered = self._find(conn, agent_id)
                if registered is None:  # pragma: no cover - impossible while ids derive from keys
                    raise RegistrationConflict(
                        f"{agent_id} conflicted with a row that is not there. Not a refusal: "
                        f"the registry contradicts itself."
                    )
                return self._returning_agent(registered, principal_id)

            identity = _to_identity(row)
            self._trail.record(
                conn=conn,
                actor="desk",
                event_type=EventType.AGENT_REGISTERED,
                subject_id=identity.agent_id,
                payload={
                    "reasoning": (
                        "the agent presented a public key and named the principal it "
                        "acts for; the Desk issued it an identity"
                    ),
                    "evidence": {
                        "public_key": identity.public_key.base64url(),
                        "key_algorithm": AGENT_REQUEST_ALG,
                        "principal_id": identity.principal_id,
                    },
                    "state_change": {"agent_identity": "issued", "spend_authority": "none"},
                },
            )
        return identity

    def find(self, agent_id: str) -> AgentIdentity | None:
        """The identity registered under this handle, or ``None`` for a stranger."""
        with self._pool.connection() as conn:
            return self._find(conn, agent_id)

    @staticmethod
    def _find(conn: Connection[Any], agent_id: str) -> AgentIdentity | None:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM {TABLE} WHERE agent_id = %s", (agent_id,)
        ).fetchone()
        return None if row is None else _to_identity(row)

    def _returning_agent(self, registered: AgentIdentity, principal_id: str) -> AgentIdentity:
        """The identity a returning agent keeps, unless it is not who it was before.

        The key needs no comparison here: the identity *is* its thumbprint, so a row
        found under this identity is a row for this key or the registry is broken.
        """
        if registered.principal_id != principal_id:
            self._refuse_principal_change(registered, principal_id)
        return registered

    def _refuse_principal_change(self, registered: AgentIdentity, claimed: str) -> NoReturn:
        """Record the attempt, then refuse it.

        Written on its own transaction rather than the caller's: nothing was
        registered, so there is no state change for the entry to commit with, and it
        has to outlive a call that ends by raising.
        """
        reasoning = (
            f"{registered.agent_id} acts for {registered.principal_id!r} and a registration "
            f"claimed {claimed!r} for it. An identity does not change principal; a new key "
            f"is a new identity."
        )
        self._trail.record(
            actor="desk",
            event_type=EventType.AGENT_REGISTRATION_REFUSED,
            subject_id=registered.agent_id,
            reason_code=ReasonCode.AGENT_PRINCIPAL_MISMATCH,
            payload={
                "reasoning": reasoning,
                "evidence": {
                    "registered_principal_id": registered.principal_id,
                    "claimed_principal_id": claimed,
                },
                "state_change": {"agent_identity": "unchanged"},
            },
        )
        raise RegistrationConflict(reasoning)


def _to_identity(row: Sequence[Any]) -> AgentIdentity:
    agent_id, public_key, _algorithm, principal_id, registered_at = row
    return AgentIdentity(
        agent_id=agent_id,
        public_key=AgentPublicKey.from_base64url(public_key),
        principal_id=principal_id,
        registered_at=registered_at,
    )
