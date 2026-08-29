"""Check 3: is what is being asked for inside what the principal authorised?

One test per acceptance criterion on ticket 04, plus the trail entry each outcome
leaves. Every mandate is signed by a real wallet and verified by check 2 before it
reaches check 3, because a request evaluated against unverified claims would be
evaluated against whatever the sender wrote.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from desk.audit import AuditTrail, EventType, ReasonCode
from desk.identity import AgentIdentity
from desk.mandate import MandateCheck, digest_of
from desk.spend import BudgetAccumulator, Money, SpendAuthorityCheck, SpendRequest
from tests.mandate.conftest import a_mandate, budget, execution_window, line_items
from tests.spend.conftest import present
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

COFFEE = "SKU-COFFEE-1KG"


def a_request(amount: str = "750.00", *, item: str = COFFEE, currency: str = "INR") -> SpendRequest:
    return SpendRequest(item_id=item, amount=Money.of(amount, currency))


def test_the_ceiling_is_read_from_the_mandates_own_budget_constraint(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The interoperability criterion: a stranger's agent sets its own ceiling.

    Two agents present mandates differing only in ``payment.budget.max`` and are told
    two different remaining balances. Nothing the Desk holds out-of-band could produce
    that, which is the point — an out-of-band ceiling would work and would not
    interoperate (ADR-0004).
    """
    modest = present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("2000.00", "INR")]
    )
    generous = present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("9000.00", "INR")]
    )

    against_modest = spend_check.evaluate(
        a_request("750.00"), presented_by=identity, checkout=modest.checkout, payment=modest.payment
    )
    against_generous = spend_check.evaluate(
        a_request("750.00"),
        presented_by=identity,
        checkout=generous.checkout,
        payment=generous.payment,
    )

    assert against_modest.remaining == Money.of("1250.00", "INR")
    assert against_generous.remaining == Money.of("8250.00", "INR")


def test_successive_deals_draw_down_the_accumulated_total(
    spend_check: SpendAuthorityCheck,
    accumulator: BudgetAccumulator,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """AP2's evaluation rule, run three times against one mandate.

    Requested plus accumulated, at or under ``max``; the amount added to the total
    after each deal closes. 2,000 authorised, drawn down 750 then 750, leaving 500 —
    at which point the same 750 no longer fits.
    """
    presented = present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("2000.00", "INR")]
    )

    first = spend_check.evaluate(
        a_request("750.00"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )
    assert first.remaining == Money.of("1250.00", "INR")
    accumulator.record_spend(presented.payment, amount=Money.of("750.00", "INR"))

    second = spend_check.evaluate(
        a_request("750.00"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )
    assert second.remaining == Money.of("500.00", "INR")
    accumulator.record_spend(presented.payment, amount=Money.of("750.00", "INR"))

    third = spend_check.evaluate(
        a_request("750.00"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )
    assert not third.passed
    assert third.reason_code is ReasonCode.EXCEEDS_REMAINING_BALANCE


def test_the_mandate_bytes_are_unchanged_after_each_deal(
    spend_check: SpendAuthorityCheck,
    accumulator: BudgetAccumulator,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """ADR-0004 made visible: the credential is never rewritten as it is spent.

    Re-verified rather than merely compared, because a mandate that is byte-identical
    and no longer verifies would be the same problem wearing a disguise.
    """
    presented = present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("2000.00", "INR")]
    )
    before = presented.payment_bytes

    for _ in range(3):
        spend_check.evaluate(
            a_request("500.00"),
            presented_by=identity,
            checkout=presented.checkout,
            payment=presented.payment,
        )
        accumulator.record_spend(presented.payment, amount=Money.of("500.00", "INR"))

    assert presented.payment_bytes == before
    reverified = mandate_check.verify_payment(before, presented_by=identity)
    assert reverified.passed
    assert reverified.mandate is not None
    assert reverified.mandate.budget is not None
    assert reverified.mandate.budget.maximum == Decimal("2000.00")


def test_a_request_beyond_the_remaining_balance_is_refused(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    presented = present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("2000.00", "INR")]
    )

    outcome = spend_check.evaluate(
        a_request("2000.01"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.EXCEEDS_REMAINING_BALANCE
    assert outcome.remaining is None


def test_a_request_for_exactly_the_ceiling_is_authorised(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """AP2's rule is "less than or equal to ``max``", and the boundary is the half worth
    testing: an off-by-one here refuses a deal the principal authorised."""
    presented = present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("2000.00", "INR")]
    )

    outcome = spend_check.evaluate(
        a_request("2000.00"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    assert outcome.passed
    assert outcome.remaining == Money.of("0", "INR")


def test_a_request_outside_the_authorised_category_is_refused(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A mandate to buy coffee is a valid mandate. It is not a mandate to buy a laptop."""
    presented = present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("9000.00", "INR")]
    )

    outcome = spend_check.evaluate(
        a_request("750.00", item="SKU-LAPTOP-14"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.CATEGORY_NOT_AUTHORISED


def test_a_request_outside_the_validity_window_is_refused(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The thing ``exp`` cannot say: authorised, but not yet.

    Check 2 passes this mandate — it is signed, in date and bound to this agent. What
    refuses it is the window inside it.
    """
    presented = present(
        mandate_check,
        wallet,
        agent,
        identity,
        payment_constraints=[budget(), execution_window(not_before="2099-01-01T00:00:00Z")],
    )

    outcome = spend_check.evaluate(
        a_request("750.00"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.OUTSIDE_VALIDITY_WINDOW


def test_a_payment_due_inside_its_window_is_authorised(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """AP2 compares the mandate's own ``execution_date`` against the window."""
    presented = present(
        mandate_check,
        wallet,
        agent,
        identity,
        payment_constraints=[
            budget(),
            execution_window(not_before="2026-01-01T00:00:00Z", not_after="2099-01-01T00:00:00Z"),
        ],
        execution_date="2026-09-01T09:00:00Z",
    )

    outcome = spend_check.evaluate(
        a_request("750.00"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    assert outcome.passed


def test_a_payment_dated_after_its_window_is_refused(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    presented = present(
        mandate_check,
        wallet,
        agent,
        identity,
        payment_constraints=[budget(), execution_window(not_after="2026-01-31T23:59:59Z")],
        execution_date="2026-06-01T09:00:00Z",
    )

    outcome = spend_check.evaluate(
        a_request("750.00"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.OUTSIDE_VALIDITY_WINDOW


def test_a_payment_mandate_for_a_different_checkout_is_refused(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The pairing attack AP2's ``payment.reference`` exists to stop.

    Both mandates are real, signed by this principal, bound to this agent and in date.
    The budget was simply signed for a different errand, and without the reference an
    agent could bring a generous one to somebody else's shopping list.
    """
    another_errand = a_mandate(wallet, agent, constraints=[line_items("SKU-LAPTOP-14")])
    presented = present(
        mandate_check,
        wallet,
        agent,
        identity,
        payment_constraints=[budget("9000.00", "INR")],
        pay_for=another_errand,
    )

    outcome = spend_check.evaluate(
        a_request("750.00"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.CATEGORY_NOT_AUTHORISED


def test_a_mandate_with_no_ceiling_is_refused_rather_than_read_as_unlimited(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``payment.budget`` is optional in AP2. Default-deny is ours, and deliberate."""
    presented = present(mandate_check, wallet, agent, identity, payment_constraints=[])

    outcome = spend_check.evaluate(
        a_request("1.00"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.EXCEEDS_REMAINING_BALANCE


def test_a_request_in_another_currency_is_refused_rather_than_converted(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """2,000 rupees is not 2,000 of anything else, and the Desk holds no exchange rate."""
    presented = present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("2000.00", "INR")]
    )

    outcome = spend_check.evaluate(
        a_request("750.00", currency="USD"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.CATEGORY_NOT_AUTHORISED


def test_check_three_will_not_run_on_a_mandate_that_did_not_verify(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A refusal is an answer already; a later check on it would invent a second one."""
    presented = present(mandate_check, wallet, agent, identity)
    forged = mandate_check.verify_payment("not-a-mandate~", presented_by=identity)

    with pytest.raises(ValueError, match="check 2 verified"):
        spend_check.evaluate(
            a_request(),
            presented_by=identity,
            checkout=presented.checkout,
            payment=forged,
        )


def test_a_pass_records_the_ceiling_the_total_and_what_is_left(
    spend_check: SpendAuthorityCheck,
    accumulator: BudgetAccumulator,
    mandate_check: MandateCheck,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """ "Within the balance" is an assertion until all three numbers are in the entry."""
    presented = present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("2000.00", "INR")]
    )
    accumulator.record_spend(presented.payment, amount=Money.of("800.00", "INR"))

    outcome = spend_check.evaluate(
        a_request("300.00"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    assert outcome.passed
    (entry,) = trail.query(event_type=EventType.CHECK_3_SPEND_AUTHORITY_PASSED)
    assert entry == outcome.entry
    assert entry.subject_id == identity.agent_id
    assert entry.reason_code is None
    assert entry.payload["check"] == 3
    # The ceiling is recorded at the scale the mandate's JSON number carried it at --
    # 2000.0, not 2000.00 -- because that is the value the Desk evaluated. JSON makes
    # no promise about trailing zeroes and neither does the trail.
    assert entry.payload["evidence"]["ceiling"] == "2000.0 INR"
    assert entry.payload["evidence"]["already_spent"] == "800.00 INR"
    assert entry.payload["evidence"]["remaining"] == "1200.00 INR"
    assert entry.payload["evidence"]["would_leave"] == "900.00 INR"
    assert entry.payload["evidence"]["requested_amount"] == "300.00 INR"
    assert entry.payload["evidence"]["mandate_id"] == presented.mandate_id.value


def test_a_refusal_records_what_was_asked_beside_what_was_authorised(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A refusal nobody can act on proves a check ran and nothing else."""
    presented = present(mandate_check, wallet, agent, identity)

    outcome = spend_check.evaluate(
        a_request("100.00", item="SKU-LAPTOP-14"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    (entry,) = trail.query(event_type=EventType.CHECK_3_SPEND_AUTHORITY_REFUSED)
    assert entry == outcome.entry
    assert entry.reason_code is ReasonCode.CATEGORY_NOT_AUTHORISED
    assert entry.payload["evidence"]["requested_item"] == "SKU-LAPTOP-14"
    assert entry.payload["evidence"]["authorised_items"] == [COFFEE]
    assert entry.payload["state_change"] == {"request": "refused"}


def test_evaluating_a_request_draws_nothing_down(
    spend_check: SpendAuthorityCheck,
    accumulator: BudgetAccumulator,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A deal the buyer walks away from must not cost the principal a rupee.

    Check 3 forecasts; only a closed deal spends. Walking away is a success in this
    system's vocabulary, and a ceiling consumed by one would make it a cost.
    """
    presented = present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("2000.00", "INR")]
    )

    for _ in range(5):
        assert spend_check.evaluate(
            a_request("2000.00"),
            presented_by=identity,
            checkout=presented.checkout,
            payment=presented.payment,
        ).passed

    ledger = accumulator.spent_against(presented.payment)
    assert ledger.spent == Money.of("0", "INR")
    assert ledger.remaining == Money.of("2000.00", "INR")


def test_a_mandate_restricting_its_merchants_is_refused_rather_than_ignored(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The Desk will not honour a mandate by ignoring part of what it says.

    ``checkout.allowed_merchants`` is a constraint AP2 defines and the Desk cannot yet
    evaluate -- doing so needs a merchant identity of its own, which nothing models.
    Reading it and carrying on would authorise, here, a mandate whose principal
    restricted it to somebody else. This is the same hole ``sdjwt._resolve`` refuses
    from the other side: there by withholding a constraint, here by ignoring one.
    """
    presented = present(
        mandate_check,
        wallet,
        agent,
        identity,
        checkout_constraints=[
            line_items(),
            {
                "type": "checkout.allowed_merchants",
                "allowed": [{"name": "Somebody Else", "website": "https://somebody-else.example"}],
            },
        ],
    )

    outcome = spend_check.evaluate(
        a_request("10.00"),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.CATEGORY_NOT_AUTHORISED
    assert outcome.entry.payload["evidence"]["unevaluated_constraint"] == (
        "checkout.allowed_merchants"
    )


def test_the_checkout_reference_is_digested_under_the_payment_mandates_algorithm(
    spend_check: SpendAuthorityCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """AP2 fixes the hash by the SD-JWT the constraint sits in, not by the one it names.

    Both mandates here are ``sha-256``, which is all anything emits -- so this pins the
    *input* to the comparison rather than the algorithm: the digest check 3 matches
    against must be one taken over the checkout mandate presented with it, under the
    payment mandate's own algorithm.
    """
    presented = present(mandate_check, wallet, agent, identity)
    assert presented.payment.mandate is not None
    assert presented.payment.digest is not None

    expected = digest_of(presented.checkout_bytes, algorithm=presented.payment.digest.algorithm)
    assert presented.payment.mandate.checkout_reference == expected.value

    outcome = spend_check.evaluate(
        a_request(),
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )
    assert outcome.passed
