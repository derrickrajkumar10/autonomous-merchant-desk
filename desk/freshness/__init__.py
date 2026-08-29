"""Replay and freshness -- check 4 of the trust spine, and the nonce store behind it.

Checks 1 to 3 answer three questions about a request and none of them is *when*. A
recording of a request that passed all three passes all three again, for as long as the
mandate lives. This is the check that makes a request happen once.

Two layers, because AP2 puts the two halves of "now" in two places: ``iat`` and ``exp``
sit on the mandate, while ``nonce`` and ``aud`` sit on the key-binding hop the agent
signs per presentation (``docs/research/ap2-mandate-model.md``, section 3). Reading
either alone leaves a hole, and ``check.py`` says which hole.

    from desk.audit import AuditTrail
    from desk.freshness import FreshnessCheck, FreshnessPolicy, NonceStore
    from desk.freshness import install_schema

    with pool.connection() as conn:
        install_schema(conn)

    check = FreshnessCheck(NonceStore(pool), trail)      # policy from the environment
    outcome = check.evaluate(checkout_outcome, presented_by=identity)
    if outcome.passed:
        ...                       # the nonce is spent; this presentation is now used up

The window, the clock-skew allowance and the Desk's audience name are read from the
environment (``STITCHAI_FRESHNESS_WINDOW_SECONDS`` and the two beside it in
``policy.py``), so a merchant may tighten or widen them without touching this package
-- FR-3.4's "short configurable window".
"""

from desk.freshness.check import FreshnessCheck, FreshnessOutcome
from desk.freshness.key_binding import (
    KEY_BINDING_ALG,
    KEY_BINDING_TYP,
    MAX_CLAIM_CHARS,
    KeyBinding,
    NotFresh,
    read_key_binding,
)
from desk.freshness.nonces import NonceStore
from desk.freshness.policy import (
    AUDIENCE_VARIABLE,
    CLOCK_SKEW_VARIABLE,
    DEFAULT_AUDIENCE,
    DEFAULT_CLOCK_SKEW_SECONDS,
    DEFAULT_WINDOW_SECONDS,
    FRESHNESS_WINDOW_VARIABLE,
    FreshnessPolicy,
    Misconfigured,
)
from desk.freshness.schema import TABLE, install_schema

__all__ = [
    "AUDIENCE_VARIABLE",
    "CLOCK_SKEW_VARIABLE",
    "DEFAULT_AUDIENCE",
    "DEFAULT_CLOCK_SKEW_SECONDS",
    "DEFAULT_WINDOW_SECONDS",
    "FRESHNESS_WINDOW_VARIABLE",
    "KEY_BINDING_ALG",
    "KEY_BINDING_TYP",
    "MAX_CLAIM_CHARS",
    "TABLE",
    "FreshnessCheck",
    "FreshnessOutcome",
    "FreshnessPolicy",
    "KeyBinding",
    "Misconfigured",
    "NonceStore",
    "NotFresh",
    "install_schema",
    "read_key_binding",
]
