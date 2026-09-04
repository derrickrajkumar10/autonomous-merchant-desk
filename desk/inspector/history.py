"""One agent's past requests, read back out of the audit trail.

The behavioural half of check 5 scores a request against *this agent's own history*
(ADR-0009). That history is not a thing the Desk keeps separately -- it is already in
the trail, one entry per check per request, and re-deriving it here keeps a single
source of truth rather than a second ledger to keep true.

A request leaves a run of entries: a ``check_1_*`` entry always (it is where an agent
becomes identified), then ``check_2_*``, ``check_3_*`` and so on until the next
request's ``check_1_*``. This module walks that run and turns it into one
``RequestEvent``: when it happened, what it asked for and for how much (from the
``check_3_*`` entry, which carries both whether it passed or was refused there), and
whether anything in the run refused it.

Requests where check 1 itself refused are not in here. Those never belonged to a
registered agent -- the subject on that entry is a placeholder -- so they are not part
of anyone's baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from desk.audit import AuditEntry, AuditTrail

#: How many of an agent's most recent requests the score ever looks at. A baseline is
#: "lately", not "for ever": an agent that behaved one way for a month and then changed
#: should look anomalous, not be averaged back to calm by its own distant past.
DEFAULT_WINDOW = 30

#: The most trail entries one request ever writes under an agent's id -- the four
#: checks (twice each for the two mandates), both halves of check 5, several
#: negotiation lines, a settlement or two. Times the window, this is how many rows
#: ``read_history`` asks the database for: enough to be sure of ``window`` whole
#: requests, and bounded, so a long-lived agent does not make the query grow without
#: end.
ENTRIES_PER_REQUEST = 40


@dataclass(frozen=True)
class RequestEvent:
    """One request an identified agent made, as the trail recorded it.

    ``amount`` and ``sku`` are ``None`` when the request did not reach check 3 -- it
    was refused at check 2, say -- because there is then nothing in the trail that says
    what it was for. Such a request still counts toward timing and refusal rate.
    """

    at: datetime
    amount: Decimal | None
    currency: str | None
    sku: str | None
    refused: bool
    reason_code: str | None


def read_history(
    trail: AuditTrail, agent_id: str, *, window: int = DEFAULT_WINDOW
) -> list[RequestEvent]:
    """This agent's requests, oldest first, at most ``window`` of the most recent.

    The current request is included: by the time the behavioural check runs, the spine
    has already written its check entries, so the newest ``RequestEvent`` here is the
    one being assessed.

    Only the tail of the agent's entries is read -- ``window`` requests' worth, with
    room to spare -- so the cost of one assessment does not grow with how long the
    agent has been around.
    """
    if window <= 0:
        return _walk(trail.query(subject_id=agent_id))
    entries = trail.query(subject_id=agent_id, most_recent=window * ENTRIES_PER_REQUEST)
    return _walk(entries)[-window:]


def _walk(entries: list[AuditEntry]) -> list[RequestEvent]:
    """Group an agent's entries into one ``RequestEvent`` per request.

    A ``check_1_*`` entry opens a request; everything up to the next one belongs to it.
    Entries before the first ``check_1_*`` (there should be none for an identified
    agent, but registration writes its own) are ignored.
    """
    events: list[RequestEvent] = []
    span: list[AuditEntry] = []

    def flush() -> None:
        if span:
            events.append(_event(span))

    for entry in entries:
        name = str(entry.event_type)
        if name.startswith("check_1_"):
            flush()
            span = [entry]
        elif span and name.startswith("check_"):
            span.append(entry)
    flush()
    return events


def _event(span: list[AuditEntry]) -> RequestEvent:
    opened = span[0]
    refused = any(entry.reason_code is not None for entry in span)
    reason = next((str(e.reason_code) for e in span if e.reason_code is not None), None)

    amount: Decimal | None = None
    currency: str | None = None
    sku: str | None = None
    for entry in span:
        if str(entry.event_type).startswith("check_3_"):
            evidence = entry.payload.get("evidence", {})
            amount, currency = _split_amount(evidence.get("requested_amount"))
            raw_sku = evidence.get("requested_item")
            sku = raw_sku if isinstance(raw_sku, str) and raw_sku else None
            break

    return RequestEvent(
        at=opened.ts,
        amount=amount,
        currency=currency,
        sku=sku,
        refused=refused,
        reason_code=reason,
    )


def _split_amount(value: Any) -> tuple[Decimal | None, str | None]:
    """``"750.00 INR"`` back into its parts. Anything unreadable becomes nothing."""
    if not isinstance(value, str):
        return None, None
    parts = value.split()
    if len(parts) != 2:
        return None, None
    try:
        return Decimal(parts[0]), parts[1]
    except InvalidOperation:
        return None, None
