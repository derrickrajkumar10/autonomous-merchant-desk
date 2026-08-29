"""The accumulated total: what AP2 asks the verifier to track, and who may change it.

The properties here are the ledger's rather than check 3's — that evaluating spends
nothing, that a closed deal spends exactly once, that concurrent closes cannot slip
past each other, and that the ceiling holds even with the code taken out of the way.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from psycopg import errors
from psycopg_pool import ConnectionPool

from desk.identity import AgentIdentity, PrincipalPublicKey
from desk.mandate import (
    MandateCheck,
    MandateNotVerified,
    digest_of,
    verify_presentation,
)
from desk.spend import BudgetAccumulator, CeilingExceeded, LedgerContradiction, Money
from tests.mandate.conftest import budget
from tests.spend.conftest import Presented, present
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

CLOSERS = 8


@pytest.fixture
def presented(
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> Presented:
    """A verified pair of mandates carrying a 2,000 rupee ceiling."""
    return present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("2000.00", "INR")]
    )


def test_a_mandate_nobody_has_spent_against_reports_its_whole_ceiling(
    accumulator: BudgetAccumulator, presented: Presented
) -> None:
    ledger = accumulator.spent_against(presented.payment)

    assert ledger.spent == Money.of("0", "INR")
    assert ledger.remaining == ledger.ceiling
    assert ledger.mandate_id == presented.mandate_id.value


def test_reading_a_balance_opens_no_row(
    accumulator: BudgetAccumulator, pool: ConnectionPool, presented: Presented
) -> None:
    """A table with a row per mandate ever *considered* could not answer "was this used"."""
    accumulator.spent_against(presented.payment)

    with pool.connection() as conn:
        (rows,) = conn.execute("SELECT count(*) FROM mandate_spend").fetchone() or (None,)
    assert rows == 0


def test_closed_deals_accumulate(accumulator: BudgetAccumulator, presented: Presented) -> None:
    accumulator.record_spend(presented.payment, amount=Money.of("750.00", "INR"))
    ledger = accumulator.record_spend(presented.payment, amount=Money.of("250.50", "INR"))

    assert ledger.spent == Money.of("1000.50", "INR")
    assert ledger.remaining == Money.of("999.50", "INR")


def test_a_deal_past_the_ceiling_is_refused_by_the_accumulator(
    accumulator: BudgetAccumulator, presented: Presented
) -> None:
    """Check 3's answer can go stale between evaluating a deal and closing it.

    The accumulator is the arbiter rather than the reporter: it re-evaluates under the
    row's lock, so a deal that passed check 3 against a balance that has since been
    drawn down still cannot breach the ceiling.
    """
    accumulator.record_spend(presented.payment, amount=Money.of("1900.00", "INR"))

    with pytest.raises(CeilingExceeded, match="of which 100.00 INR is left"):
        accumulator.record_spend(presented.payment, amount=Money.of("200.00", "INR"))


def test_the_ceiling_holds_even_with_the_code_taken_out_of_the_way(
    accumulator: BudgetAccumulator, pool: ConnectionPool, presented: Presented
) -> None:
    """The property that is the database's rather than ours.

    If every line of ``accumulator.py`` were wrong, the ceiling a human signed would
    still hold, because the row that breached it cannot be written.
    """
    accumulator.record_spend(presented.payment, amount=Money.of("500.00", "INR"))

    with pytest.raises(errors.CheckViolation), pool.connection() as conn:
        conn.execute(
            "UPDATE mandate_spend SET spent = ceiling + 1 WHERE mandate_id = %s",
            (presented.mandate_id.value,),
        )


def test_a_spend_rolls_back_with_the_transaction_it_was_recorded_in(
    accumulator: BudgetAccumulator, pool: ConnectionPool, presented: Presented
) -> None:
    """A deal that failed to close must not have drawn the principal's ceiling down.

    ``conn`` is how the ledger row and whatever entry explains it commit together or
    not at all.
    """
    with pytest.raises(RuntimeError, match="the deal fell over"), pool.connection() as conn:  # noqa: PT012
        accumulator.record_spend(presented.payment, amount=Money.of("750.00", "INR"), conn=conn)
        raise RuntimeError("the deal fell over after the spend was recorded")

    ledger = accumulator.spent_against(presented.payment)
    assert ledger.spent == Money.of("0", "INR")


def test_concurrent_closes_cannot_slip_past_each_other(
    accumulator: BudgetAccumulator, presented: Presented
) -> None:
    """Eight deals of 500 close at once against a ceiling of 2,000. Four may land.

    Without the row lock, several would read the same total and all write over it --
    the classic lost update, and here it spends money nobody authorised.
    """

    def close(_: int) -> bool:
        try:
            accumulator.record_spend(presented.payment, amount=Money.of("500.00", "INR"))
        except CeilingExceeded:
            return False
        return True

    with ThreadPoolExecutor(max_workers=CLOSERS) as executor:
        landed = list(executor.map(close, range(CLOSERS)))

    assert sum(landed) == 4
    ledger = accumulator.spent_against(presented.payment)
    assert ledger.spent == Money.of("2000.00", "INR")
    assert ledger.remaining == Money.of("0", "INR")


def test_two_mandates_never_share_a_running_total(
    accumulator: BudgetAccumulator,
    presented: Presented,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Two authorisations the principal signed separately never share a running total.

    This is the property that makes a mismatched ceiling unreachable rather than merely
    caught: the row is keyed by a digest that names one signed mandate, and the ceiling
    is read from the mandate that digest names. Spending against one leaves the other
    untouched, whatever the two mandates happen to say.
    """
    other = present(
        mandate_check, wallet, agent, identity, payment_constraints=[budget("2000.00", "INR")]
    )
    assert other.mandate_id != presented.mandate_id

    accumulator.record_spend(presented.payment, amount=Money.of("1500.00", "INR"))

    assert accumulator.spent_against(presented.payment).spent == Money.of("1500.00", "INR")
    assert accumulator.spent_against(other.payment).spent == Money.of("0", "INR")


def test_the_ledger_will_not_draw_against_a_mandate_that_did_not_verify(
    accumulator: BudgetAccumulator,
    mandate_check: MandateCheck,
    identity: AgentIdentity,
) -> None:
    """Taking check 2's whole outcome is what makes a mispairing unrepresentable.

    The alternative -- a digest and a ceiling passed separately -- would let a caller
    open a mandate's row with some other mandate's ceiling, and the first spend is what
    fixes that ceiling for good.
    """
    refused = mandate_check.verify_payment("not-a-mandate~", presented_by=identity)

    with pytest.raises(ValueError, match="check 2 verified"):
        accumulator.record_spend(refused, amount=Money.of("1.00", "INR"))


def test_a_spend_in_another_currency_is_never_drawn_against_the_ceiling(
    accumulator: BudgetAccumulator, presented: Presented
) -> None:
    """Check 3 refuses this before a deal closes; the ledger refuses to be the fallback."""
    with pytest.raises(LedgerContradiction, match="cannot be drawn against a ceiling"):
        accumulator.record_spend(presented.payment, amount=Money.of("750.00", "USD"))


def test_the_row_records_which_hash_its_key_was_taken_under(
    accumulator: BudgetAccumulator, pool: ConnectionPool, presented: Presented
) -> None:
    """Two digests are only comparable when they were taken alike."""
    accumulator.record_spend(presented.payment, amount=Money.of("100.00", "INR"))

    with pool.connection() as conn:
        row = conn.execute(
            "SELECT digest_algorithm FROM mandate_spend WHERE mandate_id = %s",
            (presented.mandate_id.value,),
        ).fetchone()
    assert row is not None
    assert row[0] == presented.mandate_id.algorithm == "sha-256"


def test_a_key_that_is_not_a_digest_is_refused_by_the_database(pool: ConnectionPool) -> None:
    """The key is a digest, and the column says so rather than trusting its callers.

    Written straight to the table, because the accumulator's own interface no longer
    lets a caller name a row that is not a verified mandate's digest. The constraint is
    the layer below that, and it is the one that would still hold if the layer above
    changed.
    """
    with pytest.raises(errors.CheckViolation), pool.connection() as conn:
        conn.execute(
            "INSERT INTO mandate_spend"
            " (mandate_id, digest_algorithm, currency, ceiling, spent,"
            "  first_seen_at, updated_at)"
            " VALUES ('short', 'sha-256', 'INR', 2000, 0,"
            "         clock_timestamp(), clock_timestamp())"
        )


def _with_a_mangled_signature(mandate: str, key: PrincipalPublicKey) -> str:
    """The same mandate under a different issuer JWS, still verifying.

    A JWS is ``header.payload.signature`` and the signature is not part of what it
    covers, so it can be varied while the mandate still verifies. Base64url leaves
    spare bits in the last character of a sixty-four byte ECDSA signature: several
    characters decode to the very same signature bytes, so swapping one changes the
    JWS string and nothing the verifier reads. It is the cheapest of the several ways
    to do this -- ECDSA's second valid signature for every one it makes is the other --
    and enough to prove the point.

    Every candidate is *verified* rather than assumed. Most of the alphabet decodes to
    different bytes and is simply an invalid signature; picking one of those would make
    the test pass for the wrong reason.
    """
    issuer_jws, separator, disclosures = mandate.partition("~")
    head, payload, signature = issuer_jws.split(".")
    for candidate in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_":
        if candidate == signature[-1]:
            continue
        mangled = f"{head}.{payload}.{signature[:-1]}{candidate}{separator}{disclosures}"
        if digest_of(mangled) == digest_of(mandate):  # pragma: no cover - a changed char
            continue
        try:
            verify_presentation(mangled, key)
        except MandateNotVerified:
            continue
        return mangled
    raise AssertionError("no variant of this signature verified")  # pragma: no cover


def test_a_mandate_re_presented_under_a_mangled_signature_keeps_its_running_total(
    accumulator: BudgetAccumulator,
    presented: Presented,
    mandate_check: MandateCheck,
    identity: AgentIdentity,
    wallet: PrincipalKeypair,
) -> None:
    """The ceiling would mean nothing if a holder could mint itself a fresh one.

    The signature bytes are not covered by the signature, so a holder can present one
    signed mandate under many issuer JWSs, every one of which passes check 2 and reads
    back the same ceiling. If the ledger were keyed by anything covering those bytes,
    each variant would open its own row -- and 2,000 rupees of authority would become
    as much money as the holder had patience.

    So the key is the *signing input*: the one thing about a mandate that cannot be
    changed without the change being exactly what a signature check catches.
    """
    mangled = _with_a_mangled_signature(presented.payment_bytes, wallet.public_key)
    re_presented = mandate_check.verify_payment(mangled, presented_by=identity)
    assert re_presented.passed, "the mangled mandate must still verify, or it proves nothing"
    assert re_presented.digest != presented.digest

    accumulator.record_spend(presented.payment, amount=Money.of("1800.00", "INR"))

    assert re_presented.mandate_id == presented.mandate_id
    assert accumulator.spent_against(re_presented).spent == Money.of("1800.00", "INR")
    with pytest.raises(CeilingExceeded):
        accumulator.record_spend(re_presented, amount=Money.of("1800.00", "INR"))
