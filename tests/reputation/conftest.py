"""What the reputation suite needs: a real front door, and a clock the test controls.

The ladder's two hard-to-test properties are dwell time and decay, and both are about
*elapsed time*. Every method on ``ReputationLadder`` and ``StandingGate`` takes an
optional ``now`` for exactly this reason, so a test advances a ``datetime`` by
``timedelta(days=...)`` instead of sleeping. ``START`` is the instant the clock starts
at; ``day(n)`` is ``n`` days later.

Requests are built and sent the way a running Desk would take them -- two mandates
signed in a wallet, a request signed with an agent key, through ``TrustSpine.receive``
-- so the ``SpineOutcome`` the gate reads is a real one. Nothing hand-builds an
outcome.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditEntry, AuditTrail
from desk.freshness import FreshnessCheck, FreshnessPolicy, NonceStore
from desk.identity import AgentIdentity, AgentRegistry, IdentityCheck, PrincipalDirectory
from desk.mandate import MandateCheck
from desk.reputation import ReputationLadder, StandingGate
from desk.spend import BudgetAccumulator, SpendAuthorityCheck
from desk.spine import SpineOutcome, TrustSpine
from tests.freshness.conftest import DESK, SKEW, WINDOW
from tests.spine.conftest import a_request
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

#: Where the controlled clock starts. Any fixed, timezone-aware instant does.
START = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

#: A mandate ceiling comfortably above every rung ceiling, so a request that the
#: standing gate refuses was refused *by the rung* and not by check 3.
GENEROUS_CEILING = "500000.00"


def day(n: float) -> datetime:
    """``n`` days after the clock started."""
    return START + timedelta(days=n)


@pytest.fixture
def ladder(pool: ConnectionPool, trail: AuditTrail) -> ReputationLadder:
    return ReputationLadder(pool, trail)


@pytest.fixture
def spine(pool: ConnectionPool, trail: AuditTrail, principals: PrincipalDirectory) -> TrustSpine:
    """The four deterministic checks, wired the way a running Desk wires them."""
    return TrustSpine(
        IdentityCheck(AgentRegistry(pool, trail), trail),
        MandateCheck(principals, trail),
        SpendAuthorityCheck(BudgetAccumulator(pool), trail),
        FreshnessCheck(
            NonceStore(pool), trail, FreshnessPolicy(window=WINDOW, clock_skew=SKEW, audience=DESK)
        ),
        trail,
    )


@pytest.fixture
def gate(ladder: ReputationLadder, trail: AuditTrail) -> StandingGate:
    return StandingGate(ladder, trail)


def authorised(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    *,
    amount: str = "750.00",
    ceiling: str = GENEROUS_CEILING,
    sku: str = "SKU-COFFEE-1KG",
) -> SpineOutcome:
    """One request that really cleared checks 1 to 4, through the real front door."""
    outcome = spine.receive(
        a_request(
            wallet,
            agent,
            identity,
            amount=amount,
            item_id=sku,
            sku=sku,
            ceiling=ceiling,
        )
    )
    assert outcome.passed, outcome.reason_code
    return outcome


def reputation_entries(trail: AuditTrail) -> list[AuditEntry]:
    """Every entry the ladder or the gate wrote, in order. One agent per test."""
    names = {
        "trust_score_changed",
        "rung_changed",
        "agent_blocked",
        "standing_gate_passed",
        "standing_gate_refused",
    }
    return [entry for entry in trail.query() if str(entry.event_type) in names]
