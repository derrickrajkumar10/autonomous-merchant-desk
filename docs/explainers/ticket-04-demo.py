"""The worked example in ticket 04's explainer, section 7. Run it, don't trust it.

Wires up the whole spine against a real Postgres -- enrol a principal, register an
agent, sign both mandates, run check 2 on each and check 3 on a series of requests --
and prints what actually comes back. The explainer quotes this output verbatim, so if
the two ever disagree, the explainer is the one that is wrong.

    .venv/Scripts/python.exe docs/explainers/ticket-04-demo.py

Needs a Postgres the same way the tests do: ``STITCHAI_TEST_DATABASE_URL`` if it is
set, otherwise the embedded ``pgserver`` from the dev extra.
"""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail
from desk.audit import install_schema as install_audit_schema
from desk.identity import AgentRegistry, PrincipalDirectory
from desk.identity import install_schema as install_identity_schema
from desk.mandate import MandateCheck
from desk.spend import BudgetAccumulator, Money, SpendAuthorityCheck, SpendRequest
from desk.spend import install_schema as install_spend_schema
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

PRINCIPAL_ID = "principal-asha"
COFFEE = "SKU-COFFEE-1KG"
CEILING = "2000.00"


@contextmanager
def a_desk() -> Iterator[ConnectionPool]:
    """A pool over a database holding nothing but a freshly installed Desk."""
    supplied = os.environ.get("STITCHAI_TEST_DATABASE_URL")
    server = None
    if supplied:
        url = supplied
    else:
        import pgserver

        server = pgserver.get_server(tempfile.mkdtemp(prefix="stitchai-demo-"))
        url = server.get_uri()
    try:
        with ConnectionPool(url, min_size=1, max_size=4, open=True) as pool:
            with pool.connection() as conn:
                conn.execute("DROP TABLE IF EXISTS audit_entry CASCADE")
                conn.execute("DROP TYPE IF EXISTS audit_event_type")
                conn.execute("DROP TYPE IF EXISTS audit_reason_code")
                conn.execute("DROP TABLE IF EXISTS agent_identity")
                conn.execute("DROP TABLE IF EXISTS principal_key")
                conn.execute("DROP TABLE IF EXISTS mandate_spend")
                install_audit_schema(conn)
                install_identity_schema(conn)
                install_spend_schema(conn)
            yield pool
    finally:
        if server is not None:
            server.cleanup()


def main() -> None:
    with a_desk() as pool:
        trail = AuditTrail(pool)

        # The human edge: a principal's key lives in their wallet, and the Desk holds
        # only the public half. The agent generates its own keypair and registers.
        wallet = PrincipalKeypair.generate()
        agent = AgentKeypair.generate()
        principals = PrincipalDirectory(pool)
        principals.enrol(principal_id=PRINCIPAL_ID, public_key=wallet.public_key)
        identity = AgentRegistry(pool, trail).register(
            public_key=agent.public_key, principal_id=PRINCIPAL_ID
        )

        # One errand, two signed mandates. The wallet pairs them itself.
        now = int(time.time())
        checkout_bytes = wallet.sign_open_checkout_mandate(
            principal_id=PRINCIPAL_ID,
            agent_key=agent.public_key,
            constraints=[
                {
                    "type": "checkout.line_items",
                    "items": [
                        {
                            "id": "beans",
                            "acceptable_items": [{"id": COFFEE, "title": "Beans, 1kg"}],
                            "quantity": 2,
                        }
                    ],
                }
            ],
            issued_at=now,
            expires_at=now + 3600,
        )
        payment_bytes = wallet.sign_open_payment_mandate(
            principal_id=PRINCIPAL_ID,
            agent_key=agent.public_key,
            for_checkout=checkout_bytes,
            constraints=[
                {"type": "payment.budget", "max": float(Decimal(CEILING)), "currency": "INR"}
            ],
            issued_at=now,
            expires_at=now + 3600,
        )

        check = MandateCheck(principals, trail)
        checkout = check.verify(checkout_bytes, presented_by=identity)
        payment = check.verify_payment(payment_bytes, presented_by=identity)

        accumulator = BudgetAccumulator(pool)
        spend = SpendAuthorityCheck(accumulator, trail)

        def ask(amount: str, item: str = COFFEE) -> None:
            request = SpendRequest(item_id=item, amount=Money.of(amount, "INR"))
            outcome = spend.evaluate(
                request, presented_by=identity, checkout=checkout, payment=payment
            )
            if outcome.passed:
                print(
                    f"  ask {amount:>8} {item:<17} -> authorised, would leave {outcome.remaining}"
                )
                # Only a *closed deal* draws the ceiling down. Evaluating spends nothing.
                accumulator.record_spend(payment, amount=request.amount)
            else:
                print(f"  ask {amount:>8} {item:<17} -> refused: {outcome.reason_code}")

        print(f"A ceiling of {CEILING} INR, drawn down across deals:")
        ask("750.00")
        ask("900.00")
        ask("500.00")
        ask("350.00")

        print("\nThe wrong thing entirely:")
        ask("10.00", "SKU-LAPTOP-14")

        reverified = check.verify_payment(payment_bytes, presented_by=identity)
        ledger = accumulator.spent_against(payment)
        print(f"\nSame mandate still verifies:  {reverified.passed}")
        print(f"Same mandate_id as before:    {reverified.mandate_id == payment.mandate_id}")
        print(f"Mandate bytes unchanged:      {payment_bytes == payment.presentation}")
        print(f"What changed is one ledger row: {ledger.spent} of {ledger.ceiling} spent")


if __name__ == "__main__":
    main()
