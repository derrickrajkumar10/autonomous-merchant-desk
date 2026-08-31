"""The Desk's own two keys, kept so that they outlive the process that made them.

Everything else in ``desk/identity`` is about believing somebody else, and holds no
private key at all. This is the exception, and it is the smallest exception the rest of
the system can be built on.

**Why it has to exist.** FR-7.3 asks that a third party verify a receipt given nothing
but the Desk's public key. A key generated at start-up cannot answer that: restart the
Desk and every receipt it ever issued stops verifying, against a published key that no
longer exists. A receipt is a claim about something that happened, so it has to remain
checkable after the process that signed it is gone. The same goes for the closed
Checkout Mandates a receipt points back at.

**What is stored, and the limit worth stating plainly.** Two rows, one per purpose,
each holding the private half as an opaque string alongside the public half. The
private halves are stored *unencrypted*, in the same database as the audit trail and
the catalogue. That is a real limitation and not a design: a deployment that mattered
would put these in a KMS or an HSM and hand this module a handle rather than a secret.
Whoever can read this table can forge the Desk's signature, and the honest thing is to
say so rather than let the word "vault" imply otherwise. What it is *not* is the
delegation hole the wallet exists to close -- the principal's key is still nowhere near
``desk/`` (CONTEXT.md section 7), and neither of these keys authorises spending.

**Load or generate, once.** The first Desk to start writes the keys; every Desk after
reads them. Two processes starting at the same instant race on the insert, and the
loser reads the winner's key rather than overwriting it -- the same
``ON CONFLICT DO NOTHING``-then-read shape ``principals.py`` uses, and for the same
reason: a key that a second start-up quietly replaced would invalidate everything
signed before it.

    from desk.identity import DeskKeyVault, install_schema

    with pool.connection() as conn:
        install_schema(conn)

    vault = DeskKeyVault(pool)
    mandate_key = vault.mandate_key()      # ES256, signs closed Checkout Mandates
    receipt_key = vault.receipt_key()      # EdDSA, signs receipts

    vault.published()                      # the two public halves, for a stranger
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from psycopg import Connection
from psycopg_pool import ConnectionPool

from desk.identity.keys import DeskPublicKey, DeskReceiptPublicKey
from desk.identity.schema import DESK_KEY_TABLE
from desk.identity.signing import (
    DESK_ALG,
    DESK_KEY_ID,
    DESK_RECEIPT_ALG,
    DESK_RECEIPT_KEY_ID,
    DeskKeypair,
    DeskReceiptKeypair,
)

#: What each row is keyed by: the question the key answers, not the algorithm it
#: answers it in. An algorithm can change under a purpose; a purpose cannot.
MANDATE_PURPOSE = "mandate"
RECEIPT_PURPOSE = "receipt"

_COLUMNS = "purpose, key_algorithm, private_key, public_key, created_at"


class KeyPurposeConflict(RuntimeError):
    """A stored key whose algorithm is not the one that purpose is signed under.

    Reached only by a change to which scheme a purpose uses, made against a database
    that already holds keys under the old one. Raised rather than regenerated, because
    replacing the key would silently invalidate every artefact signed under it, and
    that is a migration somebody should have to write.
    """


@dataclass(frozen=True)
class PublishedKeys:
    """Both public halves, which is everything the Desk owes a stranger.

    Handed over together because a reader holding a receipt and a closed Checkout
    Mandate needs both, and finding out that there were two keys after fetching one is
    how a verification path ends up trying the wrong one.
    """

    mandate: DeskPublicKey
    receipt: DeskReceiptPublicKey

    def as_jwks(self) -> dict[str, Any]:
        """The two keys as an RFC 7517 JWK Set, the form a stranger's library expects.

        Each ``kid`` here is the ``kid`` the matching key actually signs under, which is
        the only thing that makes the set usable: a reader takes the ``kid`` off the
        artefact's header, looks it up in this set, and verifies. A set whose names were
        its own -- "mandate", "receipt" -- would look tidy and answer nothing, because the
        header would name neither.
        """
        return {
            "keys": [
                {**self.mandate.jwk(), "alg": DESK_ALG, "use": "sig", "kid": DESK_KEY_ID},
                {
                    **self.receipt.jwk(),
                    "alg": DESK_RECEIPT_ALG,
                    "use": "sig",
                    "kid": DESK_RECEIPT_KEY_ID,
                },
            ]
        }


class DeskKeyVault:
    """Where the Desk's two signing keys live between restarts.

    Install the schema once with ``install_schema``; this class does not migrate.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def mandate_key(self) -> DeskKeypair:
        """The ``ES256`` key that signs closed Checkout Mandates. Made on first use."""
        return DeskKeypair.restore(
            self._load_or_generate(
                MANDATE_PURPOSE, DESK_ALG, lambda: _stored(DeskKeypair.generate())
            )
        )

    def receipt_key(self) -> DeskReceiptKeypair:
        """The ``EdDSA`` key that signs receipts. Made on first use."""
        return DeskReceiptKeypair.restore(
            self._load_or_generate(
                RECEIPT_PURPOSE, DESK_RECEIPT_ALG, lambda: _stored(DeskReceiptKeypair.generate())
            )
        )

    def published(self) -> PublishedKeys:
        """The two public halves. Generates whichever key is not there yet.

        A published key that does not exist until something happens to sign with it
        would make "here is the Desk's public key" depend on whether the Desk had
        traded today, so asking for it is enough to bring it into being.
        """
        return PublishedKeys(
            mandate=self.mandate_key().public_key, receipt=self.receipt_key().public_key
        )

    def _load_or_generate(
        self, purpose: str, algorithm: str, fresh: Callable[[], tuple[str, str]]
    ) -> str:
        with self._pool.connection() as conn:
            stored = self._find(conn, purpose)
            if stored is None:
                secret, public = fresh()
                # No conflict target and no update: a second process that got here
                # first has already written the key everything is signed under, and
                # this one adopts it rather than replacing it.
                conn.execute(
                    f"INSERT INTO {DESK_KEY_TABLE} ({_COLUMNS})"
                    f" VALUES (%s, %s, %s, %s, clock_timestamp())"
                    f" ON CONFLICT DO NOTHING",
                    (purpose, algorithm, secret, public),
                )
                stored = self._find(conn, purpose)

        if stored is None:  # pragma: no cover - the insert above put it there
            raise KeyPurposeConflict(
                f"the Desk's {purpose} key was written and is not there. Not a refusal: "
                f"the key store contradicts itself."
            )
        held_algorithm, secret = stored
        if held_algorithm != algorithm:
            raise KeyPurposeConflict(
                f"the Desk's {purpose} key is stored as {held_algorithm} and this Desk "
                f"signs {purpose}s with {algorithm}. Changing the scheme for a purpose "
                f"invalidates everything already signed under it and needs a migration."
            )
        return secret

    @staticmethod
    def _find(conn: Connection[Any], purpose: str) -> tuple[str, str] | None:
        row = conn.execute(
            f"SELECT key_algorithm, private_key FROM {DESK_KEY_TABLE} WHERE purpose = %s",
            (purpose,),
        ).fetchone()
        return None if row is None else (row[0], row[1])


def _stored(keypair: DeskKeypair | DeskReceiptKeypair) -> tuple[str, str]:
    """A fresh keypair as the two strings the row holds."""
    return keypair.secret(), keypair.public_key.base64url()
