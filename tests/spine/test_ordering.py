"""The order, and the short-circuit: the two properties this ticket exists for.

Every test drives a whole signed request through ``TrustSpine.receive`` and then reads
the audit trail, because the trail is where the claim is actually made. "The Desk
refused at check 2" is only worth something if the record shows checks 3 and 4 left no
entry, and the only way to see that is to look at what was written.
"""

from __future__ import annotations

import pytest

from desk.audit import AuditTrail, EventType, ReasonCode
from desk.identity import AgentIdentity
from desk.spend import Money
from desk.spine import ORDER, SpineOutcome, SpineOutOfOrder, TrustSpine
from tests.freshness.conftest import WINDOW
from tests.spine.conftest import LAPTOP, a_request, checks_recorded
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


def test_the_order_is_identity_mandate_spend_freshness_and_is_written_down_once(
    spine: TrustSpine,
) -> None:
    """Cheapest and most certain first, named in one place rather than implied by code.

    A test on a constant looks like a tautology and is not one. ``ORDER`` is what the
    spine's own self-check compares each run against, so pinning it here is what makes
    a swapped pair of statements a failing test rather than a silent change of
    behaviour.
    """
    assert [check.position for check in ORDER] == [1, 2, 3, 4]
    assert [check.name for check in ORDER] == [
        "identity",
        "mandate validity",
        "spend authority",
        "replay and freshness",
    ]
    assert str(ORDER[3]) == "check 4 (replay and freshness)"


def test_a_wholly_valid_request_passes_all_four_and_is_recorded_as_such(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The happy path, and the shape of the trail it leaves.

    Six entries, not four: check 2 and check 4 each run once per mandate, because AP2
    splits an authorisation into a Checkout Mandate and a Payment Mandate and RFC 9901
    binds a proof of possession to exactly one presentation.
    """
    outcome = spine.receive(a_request(wallet, agent, identity))

    assert outcome.passed
    assert outcome.refused_at is None
    assert outcome.reason_code is None
    assert outcome.identity == identity
    assert outcome.remaining == Money.of("1250.00", "INR")
    assert checks_recorded(trail) == [1, 2, 2, 3, 4, 4]
    assert [entry.reason_code for entry in outcome.entries] == [None] * 6
    assert trail.verify().ok


def test_a_refusal_at_check_one_leaves_no_entry_for_any_later_check(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A request signed by a key the Desk never registered, claiming an identity it has.

    Checks 2, 3 and 4 do not run, and the point is not that they would have refused it
    too -- they would have *passed* it, since the mandates are real. Nothing later ran
    because nothing later was asked.
    """
    outcome = spine.receive(
        a_request(wallet, agent, identity, signed_by=AgentKeypair.generate())
    )

    assert not outcome.passed
    assert outcome.refused_at == ORDER[0]
    assert outcome.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID
    assert outcome.identity is None
    assert checks_recorded(trail) == [1]


def test_a_refusal_at_check_two_leaves_no_entry_for_any_later_check(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Mandates signed by a wallet the Desk holds no key for. Check 1 passed; 3 and 4 did
    not run, so a request that was affordable and fresh is recorded as neither."""
    outcome = spine.receive(
        a_request(wallet, agent, identity, issued_by=PrincipalKeypair.generate())
    )

    assert outcome.refused_at == ORDER[1]
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID
    assert outcome.identity == identity
    assert outcome.checkout is None
    assert checks_recorded(trail) == [1, 2]


def test_a_refusal_at_check_three_leaves_no_entry_for_check_four(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A request for something the mandate does not authorise.

    Both mandates verified, so check 2 recorded two passes; check 4 recorded nothing.
    That last part is the one with teeth: check 4 spends nonces, and a check-3 refusal
    that had already run it would burn a presentation the agent could otherwise still
    use.
    """
    outcome = spine.receive(a_request(wallet, agent, identity, item_id=LAPTOP))

    assert outcome.refused_at == ORDER[2]
    assert outcome.reason_code is ReasonCode.CATEGORY_NOT_AUTHORISED
    assert outcome.checkout is not None and outcome.payment is not None
    assert checks_recorded(trail) == [1, 2, 2, 3]


def test_a_refusal_at_check_four_is_the_last_thing_written(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A proof of possession older than the freshness window.

    The trail ends on the refusal: five entries, the fifth being check 4 on the Checkout
    Mandate. The second hop is never read, because the request was already answered.
    """
    outcome = spine.receive(
        a_request(wallet, agent, identity, hop_age=int(WINDOW.total_seconds()) + 60)
    )

    assert outcome.refused_at == ORDER[3]
    assert outcome.reason_code is ReasonCode.REQUEST_STALE
    assert checks_recorded(trail) == [1, 2, 2, 3, 4]
    assert trail.query()[-1].event_type is EventType.CHECK_4_REPLAY_FRESHNESS_REFUSED


def test_a_check_three_refusal_spends_no_nonce_so_the_request_can_be_corrected(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Short-circuiting is not only about the record; it protects the agent too.

    An agent that asks for the wrong thing gets a refusal and keeps its presentations.
    Were check 4 to run first, an honest agent could be made to burn its nonces by
    anyone who could provoke a check-3 refusal.
    """
    for_the_checkout, for_the_payment = "nonce-one", "nonce-two"
    refused = spine.receive(
        a_request(
            wallet,
            agent,
            identity,
            item_id=LAPTOP,
            checkout_nonce=for_the_checkout,
            payment_nonce=for_the_payment,
        )
    )
    assert not refused.passed

    # The same two nonces again. Had check 4 run on the refused request it would have
    # honoured them, and this would come back a replay rather than a purchase.
    corrected = spine.receive(
        a_request(
            wallet,
            agent,
            identity,
            checkout_nonce=for_the_checkout,
            payment_nonce=for_the_payment,
        )
    )
    assert corrected.passed


def test_the_spine_will_not_record_a_run_that_skipped_a_check(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The self-check, driven directly, because no request can reach it.

    ``SpineOutcome`` refuses to exist describing checks 1, 2 and 4 -- a run that skipped
    spend authority. This is the guard that survives a refactor: every other test here
    asserts what the spine does today, and this one asserts that a future spine cannot
    quietly do something else and still report success.
    """
    passed = spine.receive(a_request(wallet, agent, identity))
    one, _checkout, _payment, _three, four, _ = passed.entries

    with pytest.raises(SpineOutOfOrder, match="not .1, 2, 3, 4. walked from the start"):
        SpineOutcome(
            identity=None,
            request=None,
            checkout=None,
            payment=None,
            remaining=None,
            refused_at=None,
            reason_code=None,
            entries=(one, four),
        )


def test_the_spine_will_not_report_passing_a_run_that_stopped_early(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The other half of the guard: the end of a run has to agree with its verdict.

    Positions 1, 2, 2, 3 are in order and skip nothing, so the first half of the check is
    satisfied -- and the run never reached check 4. This is the shape a refactor that
    dropped the freshness loop would produce, and it would otherwise be reported as a
    request that cleared all four.
    """
    passed = spine.receive(a_request(wallet, agent, identity))

    with pytest.raises(SpineOutOfOrder, match="has to reach check 4"):
        SpineOutcome(
            identity=None,
            request=None,
            checkout=None,
            payment=None,
            remaining=None,
            refused_at=None,
            reason_code=None,
            entries=passed.entries[:4],
        )

