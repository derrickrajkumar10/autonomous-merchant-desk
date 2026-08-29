"""Check 2: does a human really authorise this, and is this the agent they named?

One test per acceptance criterion on ticket 03, plus the trail entry each outcome
leaves. Every mandate here is signed by a real wallet with a real key; nothing is
stubbed, because the thing under test is a signature.
"""

from __future__ import annotations

import time

from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, EventType, ReasonCode
from desk.identity import AgentIdentity, AgentRegistry
from desk.mandate import MandateCheck
from tests.mandate.conftest import PRINCIPAL_ID, a_mandate, line_items
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


def test_a_mandate_the_principal_signed_for_this_agent_is_valid(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    outcome = mandate_check.verify(a_mandate(wallet, agent), presented_by=identity)

    assert outcome.passed
    assert outcome.reason_code is None
    assert outcome.mandate is not None
    assert outcome.mandate.constraints == (line_items(),)
    assert outcome.mandate.binds(agent.public_key)


def test_a_mandate_signed_by_the_wrong_key_is_refused(
    mandate_check: MandateCheck, agent: AgentKeypair, identity: AgentIdentity
) -> None:
    """A well-formed mandate naming the right principal, signed by somebody else.

    The forger sets ``kid`` to the principal the agent registered under, which is the
    only lie available to them. The Desk never reads it: the key comes from the
    directory, and the signature does not verify against it.
    """
    forger = PrincipalKeypair.generate()

    outcome = mandate_check.verify(a_mandate(forger, agent), presented_by=identity)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID
    assert outcome.mandate is None


def test_an_expired_mandate_is_refused(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    outcome = mandate_check.verify(a_mandate(wallet, agent, lifetime=-60), presented_by=identity)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.MANDATE_EXPIRED


def test_a_mandate_bound_to_another_agent_is_refused(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    identity: AgentIdentity,
) -> None:
    """The stolen-mandate case, which is the whole point of the ``cnf`` claim.

    The mandate is real, in date, and signed by the principal this agent acts for. It
    simply names a different agent's key, and that is enough.
    """
    another_agent = AgentKeypair.generate()

    outcome = mandate_check.verify(a_mandate(wallet, another_agent), presented_by=identity)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.AGENT_MANDATE_MISMATCH


def test_a_mandate_from_an_unenrolled_principal_is_refused(
    mandate_check: MandateCheck, pool: ConnectionPool, trail: AuditTrail
) -> None:
    """No key for the principal means nothing can establish that a human authorised it.

    The agent is registered and the mandate is genuinely signed by the principal it
    names. The Desk simply does not hold that principal's key, and there is no path by
    which the mandate itself can supply one.
    """
    stranger = PrincipalKeypair.generate()
    agent = AgentKeypair.generate()
    identity = AgentRegistry(pool, trail).register(
        public_key=agent.public_key, principal_id="principal-not-enrolled"
    )

    outcome = mandate_check.verify(
        a_mandate(stranger, agent, principal_id="principal-not-enrolled"),
        presented_by=identity,
    )

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID


def test_a_mandate_of_the_wrong_kind_is_refused(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A closed Checkout Mandate, correctly signed, in the place an open one belongs."""
    now = int(time.time())
    wrong_kind = wallet.sign_mandate_content(
        {
            "vct": "mandate.checkout.1",
            "checkout_jwt": "not-read-here",
            "checkout_hash": "not-read-here",
            "iat": now,
            "exp": now + 3600,
        },
        principal_id=PRINCIPAL_ID,
    )

    outcome = mandate_check.verify(wrong_kind, presented_by=identity)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID


def test_a_mandate_authorising_nothing_is_refused(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """AP2's schema requires a line-items constraint; a mandate without one is not one."""
    outcome = mandate_check.verify(
        a_mandate(
            wallet,
            agent,
            constraints=[{"type": "checkout.allowed_merchants", "allowed": [{"id": "stitchai"}]}],
        ),
        presented_by=identity,
    )

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID


def test_a_mandate_without_a_key_binding_is_refused(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    identity: AgentIdentity,
) -> None:
    """Without ``cnf`` there is nothing to steal-proof the mandate, so AP2 requires it."""
    now = int(time.time())
    unbound = wallet.sign_mandate_content(
        {
            "vct": "mandate.checkout.open.1",
            "constraints": [line_items()],
            "iat": now,
            "exp": now + 3600,
        },
        principal_id=PRINCIPAL_ID,
    )

    outcome = mandate_check.verify(unbound, presented_by=identity)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID


def test_a_partly_disclosed_mandate_is_refused(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Sending less of a mandate is not a way to be authorised for more.

    Nothing is altered -- the disclosure is simply dropped, and the signature over what
    is left still verifies. Check 2 refuses it anyway, because check 3 cannot evaluate
    constraints it was not shown.
    """
    signed_part = a_mandate(wallet, agent).split("~")[0]

    outcome = mandate_check.verify(f"{signed_part}~", presented_by=identity)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID
    assert "withheld" in outcome.entry.payload["reasoning"]


def test_every_outcome_is_recorded_in_the_trail(
    mandate_check: MandateCheck,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A pass and a refusal, each findable afterwards under the agent it concerned."""
    mandate_check.verify(a_mandate(wallet, agent), presented_by=identity)
    mandate_check.verify(a_mandate(wallet, agent, lifetime=-60), presented_by=identity)

    entries = [
        entry
        for entry in trail.query(subject_id=identity.agent_id)
        if entry.payload.get("check") == 2
    ]
    assert [entry.event_type for entry in entries] == [
        EventType.CHECK_2_MANDATE_VALIDITY_PASSED,
        EventType.CHECK_2_MANDATE_VALIDITY_REFUSED,
    ]
    assert [entry.reason_code for entry in entries] == [None, ReasonCode.MANDATE_EXPIRED]
    assert trail.verify().ok


def test_the_trail_records_what_was_claimed_beside_what_was_checked(
    mandate_check: MandateCheck,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A forged mandate names a principal; the entry shows which key was really used.

    The two sitting side by side is what makes an attempt findable later rather than
    merely refused now.
    """
    forger = PrincipalKeypair.generate()

    outcome = mandate_check.verify(
        a_mandate(forger, agent, principal_id="principal-someone-else"),
        presented_by=identity,
    )

    evidence = outcome.entry.payload["evidence"]
    assert evidence["claimed_principal_id"] == "principal-someone-else"
    assert evidence["verified_against"] == PRINCIPAL_ID
    assert evidence["algorithm"] == "ES256"


def test_a_refusal_records_the_dates_it_compared(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """ "Expired" is an assertion until the entry carries both instants."""
    outcome = mandate_check.verify(a_mandate(wallet, agent, lifetime=-60), presented_by=identity)

    evidence = outcome.entry.payload["evidence"]
    assert evidence["expires_at"] < evidence["presented_at"]


def test_an_unreadable_mandate_is_refused_without_a_signer_claim(
    mandate_check: MandateCheck, identity: AgentIdentity
) -> None:
    outcome = mandate_check.verify("not a mandate at all", presented_by=identity)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID
    assert outcome.entry.payload["evidence"]["claimed_principal_id"] is None


def test_check_two_says_nothing_about_spend_authority(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Valid, not funded. Whether the amount is inside the constraints is check 3."""
    outcome = mandate_check.verify(a_mandate(wallet, agent), presented_by=identity)

    assert outcome.entry.payload["state_change"] == {"mandate": "valid"}
