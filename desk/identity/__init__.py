"""Agent identity -- check 1 of the trust spine, and the registry behind it.

Before the Desk can decide whether a request is authorised, it has to know who is
asking. A buyer agent generates its own Ed25519 keypair, registers the public half
along with the principal it acts for, and receives an identity. Every request after
that is a JWS the Desk verifies against that registered key (FR-2.1, FR-2.2).

One distinction runs through the whole module: **the principal's key authorises
spending; the agent's key only proves who is asking.** They are separate types
(``AgentPublicKey``, ``PrincipalPublicKey``) so that no path can confuse them.

Registration confers minimal privilege (FR-2.3). It buys an identity, not trust.

    from psycopg_pool import ConnectionPool
    from desk.audit import AuditTrail
    from desk.identity import AgentRegistry, IdentityCheck, install_schema

    with pool.connection() as conn:
        install_schema(conn)

    registry = AgentRegistry(pool, trail)
    identity = registry.register(public_key=agent_key, principal_id="principal-asha")

    outcome = IdentityCheck(registry, trail).verify(signed_request)
    if outcome.passed:
        ...                              # outcome.body is what the signature covered

See ADR-0002 for the signing scheme and ADR-0011 for where an identity comes from.
"""

from desk.identity.check import UNIDENTIFIED_AGENT, IdentityCheck, IdentityOutcome
from desk.identity.jws import (
    AGENT_REQUEST_ALG,
    AGENT_REQUEST_TYP,
    RequestHeader,
    RequestNotVerified,
    read_header,
    verify_request,
)
from desk.identity.keys import (
    AGENT_ID_PREFIX,
    AgentPublicKey,
    DeskPublicKey,
    DeskReceiptPublicKey,
    ES256PublicKey,
    PrincipalPublicKey,
)
from desk.identity.principals import Principal, PrincipalConflict, PrincipalDirectory
from desk.identity.registry import AgentIdentity, AgentRegistry, RegistrationConflict
from desk.identity.schema import install_schema
from desk.identity.signing import (
    DESK_ALG,
    DESK_KEY_ID,
    DESK_RECEIPT_ALG,
    DESK_RECEIPT_KEY_ID,
    DeskKeypair,
    DeskReceiptKeypair,
)

__all__ = [
    "AGENT_ID_PREFIX",
    "AGENT_REQUEST_ALG",
    "AGENT_REQUEST_TYP",
    "DESK_ALG",
    "DESK_KEY_ID",
    "DESK_RECEIPT_ALG",
    "DESK_RECEIPT_KEY_ID",
    "UNIDENTIFIED_AGENT",
    "AgentIdentity",
    "AgentPublicKey",
    "AgentRegistry",
    "DeskKeypair",
    "DeskPublicKey",
    "DeskReceiptKeypair",
    "DeskReceiptPublicKey",
    "ES256PublicKey",
    "IdentityCheck",
    "IdentityOutcome",
    "Principal",
    "PrincipalConflict",
    "PrincipalDirectory",
    "PrincipalPublicKey",
    "RegistrationConflict",
    "RequestHeader",
    "RequestNotVerified",
    "install_schema",
    "read_header",
    "verify_request",
]
