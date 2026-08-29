"""Both directions against Google's own AP2 SDK.

This is the test that makes "we adopt AP2" a claim rather than a decoration. A
specification you implement alone is a specification you have interpreted alone, and
the interpretation is where conformance quietly dies. So:

- a mandate **the official SDK produced** must verify in the Desk's path, and
- a mandate **our wallet produced** must verify in the SDK's.

The SDK is deliberately not a dependency of this project -- its pins are all exact, so
declaring it would drag everything else down to its versions. It is installed into a
throwaway environment instead; ``pyproject.toml`` carries the commands, and the research
note section 8 says why it comes from Google's repository rather than from PyPI. Without
it these tests skip rather than pass quietly, and say what to do.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from desk.identity import AgentPublicKey
from desk.mandate import (
    digest_of,
    read_open_checkout_mandate,
    read_open_payment_mandate,
    verify_sd_jwt,
)
from tests.mandate.conftest import PRINCIPAL_ID, budget, execution_window, line_items
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

ap2_mandate = pytest.importorskip(
    "ap2.sdk.mandate",
    reason=(
        "the official AP2 SDK is not installed, so AP2 conformance was not exercised. "
        "It is not a dependency of this project on purpose -- see the throwaway-"
        "environment commands in pyproject.toml, above [build-system]."
    ),
)
ap2_open_checkout = pytest.importorskip("ap2.sdk.generated.open_checkout_mandate")
ap2_open_payment = pytest.importorskip("ap2.sdk.generated.open_payment_mandate")
jwk_module = pytest.importorskip("jwcrypto.jwk")


def _issuer_jwk(wallet: PrincipalKeypair, *, private: bool = False) -> Any:
    """The wallet's key in the form the SDK insists on: a ``jwcrypto`` JWK.

    The public form is built from our own ``PrincipalPublicKey``, so what the SDK
    verifies against is the key the Desk would have stored, not a second copy that
    happens to agree.
    """
    if not private:
        return jwk_module.JWK(**wallet.public_key.jwk())
    exported = json.loads(jwk_module.JWK.from_pyca(wallet._signing_key).export())  # noqa: SLF001
    return jwk_module.JWK(**{**exported, "kid": PRINCIPAL_ID})


def test_a_mandate_the_official_sdk_produced_verifies_in_our_path(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    now = int(time.time())
    theirs = ap2_mandate.MandateClient().create(
        payloads=[
            ap2_open_checkout.OpenCheckoutMandate(
                constraints=[
                    ap2_open_checkout.LineItems(
                        items=[
                            ap2_open_checkout.LineItemRequirements(
                                id="beans",
                                acceptable_items=[
                                    ap2_open_checkout.Item(
                                        id="SKU-COFFEE-1KG", title="Single origin beans, 1kg"
                                    )
                                ],
                                quantity=2,
                            )
                        ]
                    )
                ],
                cnf={"jwk": agent.public_key.jwk()},
                iat=now,
                exp=now + 3600,
            )
        ],
        issuer_key=_issuer_jwk(wallet, private=True),
    )

    mandate = read_open_checkout_mandate(verify_sd_jwt(theirs, wallet.public_key))

    assert mandate.binds(agent.public_key)
    assert mandate.expires_at is not None
    assert mandate.constraints[0]["type"] == "checkout.line_items"
    # The SDK selectively discloses the acceptable items, so resolving them at all is
    # the part that proves our disclosure handling matches theirs.
    assert mandate.constraints[0]["items"][0]["acceptable_items"] == [
        {"id": "SKU-COFFEE-1KG", "title": "Single origin beans, 1kg"}
    ]


def test_a_mandate_our_wallet_produced_verifies_in_the_official_sdk(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    now = int(time.time())
    ours = wallet.sign_open_checkout_mandate(
        principal_id=PRINCIPAL_ID,
        agent_key=agent.public_key,
        constraints=[line_items()],
        issued_at=now,
        expires_at=now + 3600,
    )

    verified = ap2_mandate.MandateClient().verify(
        token=ours,
        key_or_provider=_issuer_jwk(wallet),
        payload_type=ap2_open_checkout.OpenCheckoutMandate,
    )

    read = verified.mandate_payload
    assert read.vct == "mandate.checkout.open.1"
    assert read.exp == now + 3600
    assert AgentPublicKey.from_jwk(read.cnf["jwk"]) == agent.public_key


def test_a_payment_mandate_the_official_sdk_produced_verifies_in_our_path(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """The ceiling check 3 draws down, read off a mandate the SDK built.

    This is the half that matters for FR-11.1. A stranger's agent expresses its budget
    with the SDK's own ``Budget`` model, and the Desk has to find the ceiling in it
    without either side having read the other's source.
    """
    now = int(time.time())
    checkout = wallet.sign_open_checkout_mandate(
        principal_id=PRINCIPAL_ID,
        agent_key=agent.public_key,
        constraints=[line_items()],
        issued_at=now,
        expires_at=now + 3600,
    )
    theirs = ap2_mandate.MandateClient().create(
        payloads=[
            ap2_open_payment.OpenPaymentMandate(
                constraints=[
                    ap2_open_payment.PaymentReference(
                        conditional_transaction_id=digest_of(checkout).value
                    ),
                    ap2_open_payment.Budget(max=2000.00, currency="INR"),
                    ap2_open_payment.ExecutionDate(not_after="2027-01-01T00:00:00Z"),
                ],
                cnf={"jwk": agent.public_key.jwk()},
                iat=now,
                exp=now + 3600,
            )
        ],
        issuer_key=_issuer_jwk(wallet, private=True),
    )

    mandate = read_open_payment_mandate(verify_sd_jwt(theirs, wallet.public_key))

    assert mandate.checkout_reference == digest_of(checkout).value
    assert mandate.budget is not None
    # A Decimal, not the float the SDK's own model types ``max`` as. We read the
    # number off the wire rather than out of their object, so the exactness survives.
    assert mandate.budget.maximum == Decimal("2000.00")
    assert mandate.budget.currency == "INR"
    assert mandate.execution_window is not None
    assert mandate.execution_window.not_after == datetime(2027, 1, 1, tzinfo=UTC)


def test_a_payment_mandate_our_wallet_produced_verifies_in_the_official_sdk(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    now = int(time.time())
    checkout = wallet.sign_open_checkout_mandate(
        principal_id=PRINCIPAL_ID,
        agent_key=agent.public_key,
        constraints=[line_items()],
        issued_at=now,
        expires_at=now + 3600,
    )
    ours = wallet.sign_open_payment_mandate(
        principal_id=PRINCIPAL_ID,
        agent_key=agent.public_key,
        for_checkout=checkout,
        constraints=[budget(), execution_window(not_after="2027-01-01T00:00:00Z")],
        issued_at=now,
        expires_at=now + 3600,
    )

    verified = ap2_mandate.MandateClient().verify(
        token=ours,
        key_or_provider=_issuer_jwk(wallet),
        payload_type=ap2_open_payment.OpenPaymentMandate,
    )

    read = verified.mandate_payload
    assert read.vct == "mandate.payment.open.1"
    # The SDK parses the constraint array into its own discriminated models, so this
    # asserts our constraint objects are the shapes it expects rather than merely JSON.
    by_type = {constraint.type: constraint for constraint in read.constraints}
    assert by_type["payment.reference"].conditional_transaction_id == digest_of(checkout).value
    assert by_type["payment.budget"].currency == "INR"
    assert AgentPublicKey.from_jwk(read.cnf["jwk"]) == agent.public_key


def test_the_sdk_refuses_a_mandate_whose_disclosure_we_altered(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """The negative half. Interoperating on what verifies means little on its own.

    If the SDK accepted a tampered mandate, our own refusal of it would be a house
    rule rather than the specification doing its job.
    """
    ours = wallet.sign_open_checkout_mandate(
        principal_id=PRINCIPAL_ID,
        agent_key=agent.public_key,
        constraints=[line_items()],
        expires_at=int(time.time()) + 3600,
    )
    issuer_jws, disclosure, _ = ours.split("~")
    tampered = f"{issuer_jws}~{disclosure[:-4]}AAAA~"

    with pytest.raises(Exception):  # noqa: B017,PT011 - the SDK's own type, whatever it is
        ap2_mandate.MandateClient().verify(
            token=tampered,
            key_or_provider=_issuer_jwk(wallet),
            payload_type=ap2_open_checkout.OpenCheckoutMandate,
        )
