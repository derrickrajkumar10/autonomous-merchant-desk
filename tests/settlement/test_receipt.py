"""The receipt as a document: what it refuses to be, and what it refuses to read.

``test_third_party_verification.py`` proves the claim that matters -- a stranger with an
off-the-shelf library and the published key can check one. This file is the other side:
the Desk's own reader, and the things it will not accept as a receipt even when the
signature is genuine.

The distinction those tests are about is worth stating. A valid signature says *the Desk
wrote these bytes*. It does not say the bytes are a receipt. Anything the Desk signs
under its receipt key -- a closed mandate's inner payload, a future artefact nobody has
thought of yet -- would carry a genuine signature and must not read back as evidence
that money moved.
"""

from __future__ import annotations

import pytest

from desk.identity import AgentIdentity, DeskKeyVault, DeskReceiptKeypair
from desk.mandate import read_closed_checkout
from desk.negotiation import Desk
from desk.settlement import RECEIPT_TYP, ReceiptNotVerified, Settlement, issue_receipt, read_receipt
from desk.spine import TrustSpine
from tests.settlement.conftest import closed_deal, declined, rupees, settle
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

AGREED = "1500.00"


def test_no_receipt_can_be_asked_for_over_a_charge_that_did_not_complete(
    spine: TrustSpine,
    selling: Desk,
    vault: DeskKeyVault,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Held here as well as in ``settle.py``, and on purpose.

    ``settle`` decides *when* to issue one. This decides that there is no way to ask for
    one at all that is not about money which actually moved -- so a later caller, a
    replay tool, a fixture, cannot mint a receipt for a charge that was declined.
    """
    deal = closed_deal(spine, selling, wallet, agent, identity)
    closed = read_closed_checkout(deal.closed_mandate, key=vault.published().mandate)
    assert deal.payment.mandate_id is not None

    with pytest.raises(ReceiptNotVerified, match="records something that happened"):
        issue_receipt(
            closed,
            payment_mandate=deal.payment.mandate_id,
            charge=declined(),
            charged=rupees(AGREED),
            agent_id=identity.agent_id,
            signed_by=vault.receipt_key(),
        )


def test_something_else_the_desk_signed_is_not_a_receipt(vault: DeskKeyVault) -> None:
    """A genuine signature over the wrong kind of document.

    The ``typ`` header is what separates them, which is why it is set rather than left
    to default -- without it, every artefact the Desk ever signs under this key becomes
    a candidate receipt.
    """
    not_a_receipt = vault.receipt_key().sign({"iss": "desk", "hello": "world"}, typ="mandate+jwt")

    with pytest.raises(ReceiptNotVerified, match="carries typ"):
        read_receipt(not_a_receipt, key=vault.published().receipt)


def test_a_receipt_signed_by_somebody_else_does_not_read(vault: DeskKeyVault) -> None:
    """Anyone can generate an Ed25519 key and sign a document that says ``iss: desk``.

    What makes a receipt the Desk's is the key it verifies under, and nothing it says
    about itself.
    """
    impostor = DeskReceiptKeypair.generate()
    forged = impostor.sign({"iss": "desk", "jti": "whatever"}, typ=RECEIPT_TYP)

    with pytest.raises(ReceiptNotVerified, match="not a receipt the Desk signed"):
        read_receipt(forged, key=vault.published().receipt)


def test_a_receipt_that_names_a_different_deal_than_its_chain_does_not_read(
    vault: DeskKeyVault,
) -> None:
    """``jti`` and the chain's ``closed_checkout`` are one fact written twice.

    They are both there because ``jti`` is where a stranger's library looks for a
    document's identity and the chain is where the Desk's own reasoning looks. Two
    places holding one fact is a place they can disagree, so disagreeing is refused.
    """
    inconsistent = vault.receipt_key().sign(
        {
            "iss": "desk",
            "jti": "one-deal",
            "sub": "agent-whoever",
            "iat": 1_800_000_000,
            "mandate_chain": {
                "open_checkout": "a",
                "open_payment": "b",
                "closed_checkout": "another-deal",
            },
            "agreed": {"total": AGREED},
            "charged": {"amount": AGREED, "currency": "INR"},
            "rail": {"rail": "razorpay", "status": "captured", "charge_id": "pay_x"},
        },
        typ=RECEIPT_TYP,
    )

    with pytest.raises(ReceiptNotVerified, match="named by the closed Checkout Mandate"):
        read_receipt(inconsistent, key=vault.published().receipt)


def test_a_receipt_without_the_rails_identifiers_does_not_read(vault: DeskKeyVault) -> None:
    """A charge nobody can trace back to the rail is most of a receipt's value gone."""
    untraceable = vault.receipt_key().sign(
        {
            "iss": "desk",
            "jti": "one-deal",
            "sub": "agent-whoever",
            "iat": 1_800_000_000,
            "mandate_chain": {
                "open_checkout": "a",
                "open_payment": "b",
                "closed_checkout": "one-deal",
            },
            "agreed": {"total": AGREED},
            "charged": {"amount": AGREED, "currency": "INR"},
            "rail": {"rail": "razorpay", "status": "captured"},
        },
        typ=RECEIPT_TYP,
    )

    with pytest.raises(ReceiptNotVerified, match="charge_id"):
        read_receipt(untraceable, key=vault.published().receipt)


def test_the_amount_on_a_receipt_keeps_its_exact_decimal(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    vault: DeskKeyVault,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Money is a string in the claims and a ``Decimal`` on the way back, never a float.

    A receipt is the one document whose whole value is saying exactly what was charged,
    and a number that round-tripped through a float would be a different number.
    """
    deal = closed_deal(spine, selling, wallet, agent, identity)
    settled = settle(settlement, deal, identity)
    assert settled.receipt is not None

    read_back = read_receipt(settled.receipt.signed, key=vault.published().receipt)
    assert str(read_back.charged.amount) == AGREED
    assert read_back.charged == rupees(AGREED)
