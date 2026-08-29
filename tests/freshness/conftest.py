"""Fixtures for check 4, the nonce store and the key-binding hop.

A check-4 test needs what check 4 needs: a mandate that has *already verified*, with a
proof of possession attached to the exact presentation that verified. So every test
here goes through the wallet, the agent and check 2 to get one. Nothing constructs a
hop by hand, because a hop constructed by hand is not signed by the key the mandate
endorses, which is half of what is under test.

The policy is stated explicitly rather than read from the environment, so that a test
run does not depend on what happens to be set in the shell. One test reads the
environment on purpose, and it is the one that proves the window is configurable.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail
from desk.freshness import FreshnessCheck, FreshnessPolicy, NonceStore
from desk.identity import AgentIdentity
from desk.mandate import MandateCheck, MandateOutcome, OpenCheckoutMandate
from tests.conftest import AN_HOUR, PRINCIPAL_ID
from tests.mandate.conftest import line_items
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

#: Not the default audience. A test that passed under the shipped default would also
#: pass if the check compared nothing at all.
DESK = "stitchai-desk-under-test"

WINDOW = timedelta(seconds=120)
SKEW = timedelta(seconds=30)


@pytest.fixture
def policy() -> FreshnessPolicy:
    return FreshnessPolicy(window=WINDOW, clock_skew=SKEW, audience=DESK)


@pytest.fixture
def nonces(pool: ConnectionPool) -> NonceStore:
    return NonceStore(pool)


@pytest.fixture
def freshness_check(
    nonces: NonceStore, trail: AuditTrail, policy: FreshnessPolicy
) -> FreshnessCheck:
    return FreshnessCheck(nonces, trail, policy)


def present(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    *,
    nonce: str | None = None,
    audience: str = DESK,
    hop_age: int = 0,
    mandate_age: int | None = None,
    lifetime: int | None = AN_HOUR,
    onto: str | None = None,
) -> MandateOutcome[OpenCheckoutMandate]:
    """Sign a mandate, attach a hop, and check 2 it -- the whole run-up to check 4.

    ``hop_age`` and ``mandate_age`` are seconds *before now*, negative for the future,
    which is how the timing tests avoid waiting for a clock. ``mandate_age`` follows
    ``hop_age`` unless a test says otherwise, because a mandate is always signed before
    it is presented -- a helper that aged the hop alone would build a presentation no
    honest agent can produce and then test check 4 against it.

    ``lifetime`` is measured forward from *now* rather than from the mandate's own
    ``iat``, so ageing a mandate does not quietly expire it and send check 2 home with
    the refusal instead. ``None`` produces a mandate with no ``exp`` at all, which AP2
    permits and which nothing but check 4 then bounds.

    ``onto`` attaches the hop to a different presentation to the one it is signed over,
    which is the lifted-hop attack and the only thing ``sd_hash`` exists to refuse.
    """
    now = int(time.time())
    mandate = wallet.sign_open_checkout_mandate(
        principal_id=PRINCIPAL_ID,
        agent_key=agent.public_key,
        constraints=[line_items()],
        issued_at=now - (hop_age if mandate_age is None else mandate_age),
        expires_at=None if lifetime is None else now + lifetime,
    )
    presented = agent.present(mandate, audience=audience, nonce=nonce, issued_at=now - hop_age)
    if onto is not None:
        presented = onto + presented.rpartition("~")[2]

    outcome = mandate_check.verify(presented, presented_by=identity)
    assert outcome.passed, outcome.entry.payload["reasoning"]
    return outcome
