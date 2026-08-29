"""The principal's wallet -- the human edge of the protocol.

The wallet is where the human's authority lives. It holds the principal's signing key
and turns "restock my coffee, keep it under 2,000 rupees" into a signed mandate the
Desk can verify. CONTEXT.md section 7 is emphatic about the one rule: this is a
**separate process** from the buyer agent, and the key never crosses into it.

It sits in ``world/`` rather than ``desk/`` because it is environment rather than
merchant -- but it is the root of authority in the whole system, so "environment" here
means *not ours to defend*, not *unimportant*.

    from world.wallet import PrincipalKeypair

    wallet = PrincipalKeypair.generate()
    mandate = wallet.sign_open_checkout_mandate(
        principal_id="principal-asha",
        agent_key=agent.public_key,
        constraints=[{"type": "checkout.line_items", "items": [...]}],
        expires_at=int(time.time()) + 3600,
    )
"""

from world.wallet.keys import SALT_BYTES, SD_JWT_TYP, PrincipalKeypair

__all__ = ["SALT_BYTES", "SD_JWT_TYP", "PrincipalKeypair"]
