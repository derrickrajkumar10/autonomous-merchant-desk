"""Finding receipts again, by the two things a bank line arrives holding.

Ticket 17 matches a bank credit against the receipts that produced it. It knows an
amount and a date and nothing else -- no agent, no deal, no mandate -- so those are the
two ways in, and they are designed here rather than there because a migration against a
table of signed artefacts is a worse thing to write later.

Everything that comes back out is the signed document, verified against the Desk's
published key on the way. The last test in this file is the one that makes that
load-bearing rather than decorative.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from psycopg_pool import ConnectionPool

from desk.identity import AgentIdentity, DeskKeyVault
from desk.negotiation import Desk
from desk.settlement import ReceiptNotVerified, Receipts, Settlement
from desk.spend import Money
from desk.spine import TrustSpine
from tests.settlement.conftest import StubRail, closed_deal, completed, rupees, settle
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

#: Two kilos of beans, then three, then four. Three different totals on purpose: an
#: index that matched on anything but the amount would answer all three the same.
QUANTITIES = (2, 3, 4)
TOTALS = ("1500.00", "2250.00", "3000.00")


@pytest.fixture
def settled(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> list[str]:
    """Three real settled deals, at three different totals. Returns their receipt ids."""
    ids = []
    for index, quantity in enumerate(QUANTITIES):
        rail.answer = completed(charge_id=f"pay_TESTMODE000000{index}")
        deal = closed_deal(
            spine, selling, wallet, agent, identity, quantity=quantity
        )
        result = settle(settlement, deal, identity)
        assert result.receipt is not None
        ids.append(result.receipt.receipt_id)
    return ids


def test_receipts_are_queryable_by_amount(receipts: Receipts, settled: list[str]) -> None:
    """The acceptance criterion. One exact total, and only the receipt for it."""
    found = receipts.between(totalling=rupees("2250.00"))

    assert len(found) == 1
    assert found[0].charged == rupees("2250.00")
    assert found[0].receipt.agreed["line_items"][0]["quantity"] == 3


def test_an_amount_in_another_currency_is_not_a_match(
    receipts: Receipts, settled: list[str]
) -> None:
    """Matching 1,500 rupees against 1,500 dollars is a false match, which is the one
    outcome ticket 17 must never produce. So an amount is never a number alone."""
    assert receipts.between(totalling=rupees("1500.00")) != []
    assert receipts.between(totalling=Money.of("1500.00", "USD")) == []


def test_receipts_are_queryable_by_date(receipts: Receipts, settled: list[str]) -> None:
    """The other acceptance criterion, and the window convention that goes with it."""
    now = datetime.now(UTC)

    assert len(receipts.between(now - timedelta(hours=1), now + timedelta(hours=1))) == 3
    assert receipts.between(now + timedelta(minutes=1)) == []
    assert receipts.between(until=now - timedelta(hours=1)) == []


def test_adjacent_windows_tile_without_double_counting(
    receipts: Receipts, settled: list[str]
) -> None:
    """``since`` inclusive and ``until`` exclusive, the same rule the trail uses.

    A matcher walking a month a day at a time must not see one receipt on two days.
    """
    everything = receipts.between()
    assert len(everything) == 3
    boundary = everything[1].receipt.issued_at

    before = receipts.between(until=boundary)
    after = receipts.between(boundary)

    assert len(before) + len(after) == 3
    assert {found.receipt_id for found in before}.isdisjoint(
        {found.receipt_id for found in after}
    )


def test_amount_and_date_narrow_together(receipts: Receipts, settled: list[str]) -> None:
    """Which is how a bank line is actually matched: this much, on about this day."""
    now = datetime.now(UTC)

    found = receipts.between(
        now - timedelta(hours=1), now + timedelta(hours=1), totalling=rupees("3000.00")
    )

    assert [receipt.charged for receipt in found] == [rupees("3000.00")]


def test_one_receipt_is_findable_by_the_deal_it_settled(
    receipts: Receipts, settled: list[str]
) -> None:
    """What ``settle`` itself asks before charging, and what a buyer asks afterwards."""
    found = receipts.find(settled[0])

    assert found is not None
    assert found.receipt_id == settled[0]
    assert receipts.find("no-such-deal-digest-at-all") is None


def test_a_row_edited_in_the_database_stops_verifying(
    receipts: Receipts, settled: list[str], pool: ConnectionPool, vault: DeskKeyVault
) -> None:
    """The columns are an index; the signed document is the truth.

    Somebody with write access to the table can change the number in a column. What they
    cannot do is make the artefact agree with them -- and a query returns the artefact,
    checked, rather than the column. So the tamper surfaces loudly at the point of
    reading rather than quietly in a total.
    """
    with pool.connection() as conn:
        conn.execute(
            "UPDATE receipt SET amount = 1, receipt = %s WHERE receipt_id = %s",
            ("eyJhIjoiYiJ9.eyJjIjoiZCJ9.ZmFrZQ", settled[0]),
        )

    with pytest.raises(ReceiptNotVerified, match="does not verify"):
        receipts.find(settled[0])
