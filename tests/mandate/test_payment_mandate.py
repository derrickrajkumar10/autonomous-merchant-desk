"""The open Payment Mandate: what the Desk reads out of one, and what it refuses.

Check 2's three questions are already covered by ``test_check_two.py`` and are
questions about a mandate rather than about a kind of mandate. What is new here is
the *shape* -- the constraints AP2 puts on this mandate and nowhere else, and the
pairing digest that ties it to the checkout it pays for.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from desk.audit import ReasonCode
from desk.identity import AgentIdentity
from desk.mandate import (
    MandateCheck,
    MandateNotVerified,
    digest_of,
    read_open_payment_mandate,
    verify_sd_jwt,
)
from tests.mandate.conftest import (
    PRINCIPAL_ID,
    a_mandate,
    a_payment_mandate,
    budget,
    execution_window,
)
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


def test_a_payment_mandate_carries_its_ceiling_window_and_checkout_reference(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    checkout = a_mandate(wallet, agent)
    payment = a_payment_mandate(
        wallet,
        agent,
        checkout,
        constraints=[
            budget("2000.00", "INR"),
            execution_window(not_before="2026-01-01T00:00:00Z", not_after="2026-12-31T23:59:59Z"),
        ],
    )

    outcome = mandate_check.verify_payment(payment, presented_by=identity)

    assert outcome.passed
    assert outcome.mandate is not None
    assert outcome.mandate.budget is not None
    assert outcome.mandate.budget.maximum == Decimal("2000.00")
    assert outcome.mandate.budget.currency == "INR"
    assert outcome.mandate.execution_window is not None
    assert outcome.mandate.execution_window.not_before is not None
    assert outcome.mandate.checkout_reference == digest_of(checkout).value


def test_the_ceiling_is_read_as_a_decimal_and_never_as_a_float(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """The acceptance criterion behind ``Decimal`` everywhere: an exact ceiling.

    ``0.1 + 0.2`` is the reason. A ceiling parsed as a float is not the number the
    principal signed, and a balance drawn down against it would not be either.
    """
    checkout = a_mandate(wallet, agent)
    payment = a_payment_mandate(wallet, agent, checkout, constraints=[budget("1999.95", "INR")])

    read = read_open_payment_mandate(verify_sd_jwt(payment, wallet.public_key))

    assert read.budget is not None
    assert isinstance(read.budget.maximum, Decimal)
    assert read.budget.maximum == Decimal("1999.95")


def test_a_payment_mandate_with_no_reference_constraint_is_refused(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """AP2's schema makes ``payment.reference`` mandatory, via a ``contains`` rule.

    Signed here by hand, because the wallet always adds one -- which is the point of
    the wallet adding it rather than the agent.
    """
    now = int(time.time())
    unpaired = wallet.sign_mandate_content(
        {
            "vct": "mandate.payment.open.1",
            "constraints": [budget()],
            "cnf": {"jwk": agent.public_key.jwk()},
            "iat": now,
            "exp": now + 3600,
        },
        principal_id=PRINCIPAL_ID,
    )

    outcome = mandate_check.verify_payment(unpaired, presented_by=identity)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID


def test_a_checkout_mandate_presented_as_a_payment_mandate_is_refused(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``vct`` is read before anything else is believed about the shape."""
    outcome = mandate_check.verify_payment(a_mandate(wallet, agent), presented_by=identity)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID


def test_a_payment_mandate_presented_as_a_checkout_mandate_is_refused(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    checkout = a_mandate(wallet, agent)

    outcome = mandate_check.verify(
        a_payment_mandate(wallet, agent, checkout), presented_by=identity
    )

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID


def test_a_budget_whose_max_is_not_a_number_is_refused(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    checkout = a_mandate(wallet, agent)
    payment = a_payment_mandate(
        wallet,
        agent,
        checkout,
        constraints=[{"type": "payment.budget", "max": "2000.00", "currency": "INR"}],
    )

    with pytest.raises(MandateNotVerified, match="must be a number"):
        read_open_payment_mandate(verify_sd_jwt(payment, wallet.public_key))


def test_a_budget_in_something_that_is_not_a_currency_is_refused(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    checkout = a_mandate(wallet, agent)
    payment = a_payment_mandate(
        wallet,
        agent,
        checkout,
        constraints=[{"type": "payment.budget", "max": 2000, "currency": "rupees"}],
    )

    with pytest.raises(MandateNotVerified, match="ISO 4217"):
        read_open_payment_mandate(verify_sd_jwt(payment, wallet.public_key))


def test_a_budget_of_nothing_is_refused(wallet: PrincipalKeypair, agent: AgentKeypair) -> None:
    checkout = a_mandate(wallet, agent)
    payment = a_payment_mandate(wallet, agent, checkout, constraints=[budget("0.00")])

    with pytest.raises(MandateNotVerified, match="authorises no spending"):
        read_open_payment_mandate(verify_sd_jwt(payment, wallet.public_key))


def test_two_ceilings_in_one_mandate_are_refused_rather_than_chosen_between(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """Taking whichever came first would be taking whichever the sender put first."""
    checkout = a_mandate(wallet, agent)
    payment = a_payment_mandate(
        wallet, agent, checkout, constraints=[budget("2000.00"), budget("9000.00")]
    )

    with pytest.raises(MandateNotVerified, match="will not choose between them"):
        read_open_payment_mandate(verify_sd_jwt(payment, wallet.public_key))


def test_a_window_that_ends_before_it_begins_is_refused(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    checkout = a_mandate(wallet, agent)
    payment = a_payment_mandate(
        wallet,
        agent,
        checkout,
        constraints=[
            budget(),
            execution_window(not_before="2026-12-31T00:00:00Z", not_after="2026-01-01T00:00:00Z"),
        ],
    )

    with pytest.raises(MandateNotVerified, match="ends before it begins"):
        read_open_payment_mandate(verify_sd_jwt(payment, wallet.public_key))


def test_a_window_written_as_a_bare_date_is_read_as_utc(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """Valid ISO 8601, and what a wallet writing a date rather than an instant sends."""
    checkout = a_mandate(wallet, agent)
    payment = a_payment_mandate(
        wallet,
        agent,
        checkout,
        constraints=[budget(), execution_window(not_after="2026-12-31")],
    )

    read = read_open_payment_mandate(verify_sd_jwt(payment, wallet.public_key))

    assert read.execution_window is not None
    assert read.execution_window.not_after is not None
    assert read.execution_window.not_after.tzinfo is not None
    assert read.execution_window.not_after.isoformat() == "2026-12-31T00:00:00+00:00"


def test_a_mandate_with_no_ceiling_reads_as_having_none(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """``payment.budget`` is optional in AP2, so reading one is not refusing one.

    Refusing it is check 3's call, and it does -- an absent ceiling bounds nothing.
    The reader's job is to say truthfully that there is none.
    """
    checkout = a_mandate(wallet, agent)
    payment = a_payment_mandate(wallet, agent, checkout, constraints=[])

    read = read_open_payment_mandate(verify_sd_jwt(payment, wallet.public_key))

    assert read.budget is None
    assert read.execution_window is None
    assert read.checkout_reference == digest_of(checkout).value
