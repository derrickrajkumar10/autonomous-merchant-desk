"""Where receipts are kept, and how they are found again.

Two jobs, and the second is the one this ticket had to design for rather than discover.

**Keeping.** A receipt is written in the same transaction as the ledger row it drew
down, so there is no instant at which the Desk believes it charged a mandate and holds
nothing signed to show for it. ``store`` therefore takes the caller's connection and
never opens one of its own.

**Finding.** Ticket 17 matches a bank credit against the receipts that produced it. It
arrives holding an amount and a date and nothing else, so those are the two ways in:
``between`` for a date range, ``totalling`` for an exact amount, and both together.
Designing that here rather than there is what stops a migration against a table of
signed documents later.

**A row is an index, not a record.** Every column but ``receipt`` restates something
already inside the signed document. Nothing here believes a column: everything that
comes back out is the JWS, verified against the Desk's published key, and parsed from
what the signature actually covers. So a row edited in the database does not answer a
query with a number nobody signed -- it stops verifying, loudly, at the point of
reading. That is the same discipline the audit trail's hash chain applies to its own
table, pointed at this one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg import Connection, sql
from psycopg_pool import ConnectionPool

from desk.identity import DeskReceiptPublicKey
from desk.settlement.receipt import Receipt, ReceiptNotVerified, read_receipt
from desk.settlement.schema import TABLE
from desk.spend.money import Money

_COLUMNS = (
    "receipt_id, agent_id, open_checkout, open_payment, currency, amount,"
    " issued_at, rail, charge_id, receipt"
)


@dataclass(frozen=True)
class IssuedReceipt:
    """One receipt as it is held: the signed artefact, and what it says.

    Both halves, because they are used for different things. ``signed`` is what is
    handed to a buyer or a judge and is the only part that proves anything. ``receipt``
    is what the Desk reasons over, and exists only because it was parsed out of
    ``signed`` a moment ago.
    """

    signed: str
    receipt: Receipt

    @property
    def receipt_id(self) -> str:
        return self.receipt.receipt_id

    @property
    def charged(self) -> Money:
        return self.receipt.charged


class Receipts:
    """The Desk's receipts, kept so they can be produced and matched against later.

    Install the schema once with ``install_schema``; this class does not migrate.

    The public key is a constructor argument rather than something looked up per read,
    so that a ``Receipts`` wired to the wrong key refuses everything at once instead of
    quietly returning half a table.
    """

    def __init__(self, pool: ConnectionPool, key: DeskReceiptPublicKey) -> None:
        self._pool = pool
        self._key = key

    def store(self, signed: str, *, conn: Connection[Any]) -> IssuedReceipt:
        """Keep one receipt, on the caller's transaction.

        The columns are filled from the *verified* document rather than from anything
        the caller says about it, so an index entry that disagrees with the artefact it
        indexes is not a thing this method can be made to write.

        Takes ``conn`` and not a pool. A receipt exists because a charge completed and
        a ledger was drawn down, and those three facts commit together or not at all.
        """
        receipt = read_receipt(signed, key=self._key)
        conn.execute(
            f"INSERT INTO {TABLE} ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                receipt.receipt_id,
                receipt.agent_id,
                receipt.chain.open_checkout,
                receipt.chain.open_payment,
                receipt.charged.currency,
                receipt.charged.amount,
                receipt.issued_at,
                receipt.charge.rail,
                receipt.charge.charge_id,
                signed,
            ),
        )
        return IssuedReceipt(signed=signed, receipt=receipt)

    def find(self, receipt_id: str, *, conn: Connection[Any] | None = None) -> IssuedReceipt | None:
        """The receipt for one closed deal, or ``None`` if that deal was never settled.

        ``conn`` so that ``settle.py`` can ask this inside the transaction it is about
        to charge in -- "have I settled this deal already" is only a useful question if
        the answer cannot change between asking it and acting on it.
        """
        if conn is not None:
            return self._find(conn, receipt_id)
        with self._pool.connection() as pooled:
            return self._find(pooled, receipt_id)

    def between(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        *,
        totalling: Money | None = None,
        agent_id: str | None = None,
        limit: int | None = None,
    ) -> list[IssuedReceipt]:
        """Receipts matching every filter given, oldest first.

        ``since`` is inclusive and ``until`` exclusive, so adjacent windows tile without
        double-counting -- the same convention the audit trail's ``query`` uses, because
        a caller reading both should not have to hold two rules.

        ``totalling`` is an exact amount and a currency together, never an amount alone.
        Matching a 1,500 rupee credit against a 1,500 dollar receipt is a false match,
        which is the one outcome ticket 17 must never produce.
        """
        conditions: list[sql.Composable] = []
        params: list[Any] = []

        if since is not None:
            conditions.append(sql.SQL("issued_at >= %s"))
            params.append(since)
        if until is not None:
            conditions.append(sql.SQL("issued_at < %s"))
            params.append(until)
        if totalling is not None:
            conditions.append(sql.SQL("currency = %s AND amount = %s"))
            params.extend((totalling.currency, totalling.amount))
        if agent_id is not None:
            conditions.append(sql.SQL("agent_id = %s"))
            params.append(agent_id)

        statement = sql.SQL("SELECT {columns} FROM {table}").format(
            columns=sql.SQL(_COLUMNS), table=sql.Identifier(TABLE)
        )
        if conditions:
            statement = statement + sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
        statement = statement + sql.SQL(" ORDER BY issued_at, receipt_id")
        if limit is not None:
            statement = statement + sql.SQL(" LIMIT %s")
            params.append(limit)

        with self._pool.connection() as conn:
            rows = conn.execute(statement, params).fetchall()
        return [self._verified(row) for row in rows]

    def _find(self, conn: Connection[Any], receipt_id: str) -> IssuedReceipt | None:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM {TABLE} WHERE receipt_id = %s", (receipt_id,)
        ).fetchone()
        return None if row is None else self._verified(row)

    def _verified(self, row: Sequence[Any]) -> IssuedReceipt:
        """One row as the artefact it holds, checked against the Desk's own key.

        The row's own columns are not read at all. If they disagree with the document,
        the document wins -- and if the document does not verify, nothing wins.
        """
        signed = row[-1]
        try:
            return IssuedReceipt(signed=signed, receipt=read_receipt(signed, key=self._key))
        except ReceiptNotVerified as exc:
            raise ReceiptNotVerified(
                f"the receipt stored under {row[0]!r} does not verify against the Desk's "
                f"published key: {exc}"
            ) from exc
