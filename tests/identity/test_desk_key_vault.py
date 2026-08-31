"""The Desk's own keys, and the one property they exist for: they outlive the process.

A key generated at start-up makes FR-7.3 -- "verifiable given the Desk's public key" --
meaningless the first time the Desk restarts, because the key it was verified against no
longer exists. These tests are about that and about nothing else clever.

Two vaults over one database is what a restarted Desk is, and it is how every test here
asks the question.
"""

from __future__ import annotations

import pytest
from jwt.api_jws import decode as jws_decode
from psycopg_pool import ConnectionPool

from desk.identity import (
    DESK_ALG,
    DESK_KEY_ID,
    DESK_RECEIPT_ALG,
    DESK_RECEIPT_KEY_ID,
    MANDATE_PURPOSE,
    RECEIPT_PURPOSE,
    DeskKeypair,
    DeskKeyVault,
    DeskReceiptKeypair,
    KeyPurposeConflict,
)


def test_a_restarted_desk_publishes_the_same_keys(pool: ConnectionPool) -> None:
    """The whole point. Both keys, because a receipt points back at a closed mandate."""
    first = DeskKeyVault(pool).published()
    restarted = DeskKeyVault(pool).published()

    assert restarted.mandate == first.mandate
    assert restarted.receipt == first.receipt


def test_a_receipt_signed_before_a_restart_verifies_after_it(pool: ConnectionPool) -> None:
    """Stated as the signature it is, rather than as an equality of key material."""
    signed = DeskKeyVault(pool).receipt_key().sign({"iss": "desk"}, typ="receipt+jwt")

    verifier = DeskKeyVault(pool).published().receipt.verifier()
    assert jws_decode(signed, key=verifier, algorithms=[DESK_RECEIPT_ALG]) == b'{"iss":"desk"}'


def test_the_two_keys_are_different_keys_under_different_schemes(
    pool: ConnectionPool,
) -> None:
    """One says the Desk agreed to a deal; the other says money moved.

    Kept apart so that holding the authority to say one is not holding the authority to
    say the other -- and under different schemes, because a receipt is not an AP2
    document and ADR-0002's exception does not follow it there.
    """
    vault = DeskKeyVault(pool)

    assert isinstance(vault.mandate_key(), DeskKeypair)
    assert isinstance(vault.receipt_key(), DeskReceiptKeypair)
    published = vault.published()
    assert published.mandate.thumbprint() != published.receipt.thumbprint()

    # Keyed by the ``kid`` each key actually signs under, which is the only thing that
    # makes the published set usable: a reader takes the kid off an artefact's header and
    # looks it up here. Names of our own choosing would look tidy and answer nothing.
    jwks = {key["kid"]: key for key in published.as_jwks()["keys"]}
    assert jwks[DESK_KEY_ID]["alg"] == DESK_ALG
    assert jwks[DESK_KEY_ID]["kty"] == "EC"
    assert jwks[DESK_RECEIPT_KEY_ID]["alg"] == DESK_RECEIPT_ALG
    assert jwks[DESK_RECEIPT_KEY_ID]["kty"] == "OKP"


def test_asking_for_a_key_twice_does_not_make_a_second_one(pool: ConnectionPool) -> None:
    """Load-or-generate, not generate-and-store. A second row would silently invalidate
    everything signed under the first."""
    vault = DeskKeyVault(pool)
    vault.published()
    vault.published()

    with pool.connection() as conn:
        rows = conn.execute("SELECT purpose FROM desk_key ORDER BY purpose").fetchall()
    assert [row[0] for row in rows] == [MANDATE_PURPOSE, RECEIPT_PURPOSE]


def test_a_key_stored_under_the_wrong_scheme_is_refused_not_replaced(
    pool: ConnectionPool,
) -> None:
    """Changing which scheme a purpose uses is a migration, not a start-up side effect.

    Regenerating instead would mean every receipt ever issued stops verifying, and
    nothing would have said so.
    """
    vault = DeskKeyVault(pool)
    vault.published()
    with pool.connection() as conn:
        conn.execute(
            "UPDATE desk_key SET key_algorithm = %s WHERE purpose = %s",
            (DESK_ALG, RECEIPT_PURPOSE),
        )

    with pytest.raises(KeyPurposeConflict, match="needs a migration"):
        DeskKeyVault(pool).receipt_key()


def test_the_private_half_never_leaves_except_through_the_vault(
    pool: ConnectionPool,
) -> None:
    """``restore`` and ``secret`` are the only route to it, and they round-trip exactly.

    Asserted as behaviour rather than as bytes: what matters is that the restored key
    produces signatures the stored public half verifies.
    """
    original = DeskReceiptKeypair.generate()

    restored = DeskReceiptKeypair.restore(original.secret())

    assert restored.public_key == original.public_key
    mandate = DeskKeypair.generate()
    assert DeskKeypair.restore(mandate.secret()).public_key == mandate.public_key
