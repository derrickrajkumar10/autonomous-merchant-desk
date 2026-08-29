"""Fixtures for check 3 and the accumulator.

A check-3 test needs what check 3 needs: two mandates that have *already verified*.
So every test here goes through check 2 to get them, rather than constructing the
mandate objects directly — a caller that skipped check 2 would be evaluating a
request against claims nobody had checked, which is the thing check 3 is forbidden
to do.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail
from desk.identity import AgentIdentity
from desk.mandate import (
    Budget,
    MandateCheck,
    MandateDigest,
    MandateOutcome,
    OpenCheckoutMandate,
    OpenPaymentMandate,
)
from desk.spend import BudgetAccumulator, SpendAuthorityCheck
from tests.mandate.conftest import a_mandate, a_payment_mandate
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


@pytest.fixture
def accumulator(pool: ConnectionPool) -> BudgetAccumulator:
    return BudgetAccumulator(pool)


@pytest.fixture
def spend_check(accumulator: BudgetAccumulator, trail: AuditTrail) -> SpendAuthorityCheck:
    return SpendAuthorityCheck(accumulator, trail)


@dataclass(frozen=True)
class Presented:
    """One buyer agent's presentation: both mandates, as check 2 left them.

    ``checkout_bytes`` and ``payment_bytes`` are kept so a test can prove the thing
    ADR-0004 is about — that the credential is never rewritten as it is drawn down.
    """

    checkout: MandateOutcome[OpenCheckoutMandate]
    payment: MandateOutcome[OpenPaymentMandate]
    checkout_bytes: str
    payment_bytes: str

    @property
    def budget(self) -> Budget:
        """The ceiling the payment mandate carries. Absent only where a test omits it."""
        assert self.payment.mandate is not None
        assert self.payment.mandate.budget is not None
        return self.payment.mandate.budget

    @property
    def mandate_id(self) -> MandateDigest:
        """What the accumulator keys this mandate's running total by.

        The signing input's digest, not the issuer JWS's -- a holder can vary the
        latter without breaking the signature.
        """
        assert self.payment.mandate_id is not None
        return self.payment.mandate_id

    @property
    def digest(self) -> MandateDigest:
        """What AP2 pairs the two mandates by -- the issuer JWS's digest.

        Not what the ledger is keyed by; see ``mandate_id``.
        """
        assert self.payment.digest is not None
        return self.payment.digest


def present(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    *,
    checkout_constraints: Sequence[Mapping[str, Any]] | None = None,
    payment_constraints: Sequence[Mapping[str, Any]] | None = None,
    execution_date: str | None = None,
    pay_for: str | None = None,
) -> Presented:
    """Sign both mandates, present them, and check 2 them — the whole run-up to check 3.

    ``pay_for`` pairs the payment mandate with a *different* checkout mandate, which is
    the only way to build the mismatched pairing the Desk has to refuse. The wallet
    computes the reference digest itself, so an agent cannot choose it.
    """
    checkout_bytes = a_mandate(wallet, agent, constraints=checkout_constraints)
    payment_bytes = a_payment_mandate(
        wallet,
        agent,
        pay_for if pay_for is not None else checkout_bytes,
        constraints=payment_constraints,
        execution_date=execution_date,
    )

    checkout = mandate_check.verify(checkout_bytes, presented_by=identity)
    payment = mandate_check.verify_payment(payment_bytes, presented_by=identity)
    assert checkout.passed and payment.passed

    return Presented(
        checkout=checkout,
        payment=payment,
        checkout_bytes=checkout_bytes,
        payment_bytes=payment_bytes,
    )
