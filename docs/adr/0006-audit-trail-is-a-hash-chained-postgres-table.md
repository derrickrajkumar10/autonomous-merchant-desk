# The audit trail is a hash-chained append-only Postgres table

Build step 1. Every other component reads from this, and FR-10.2 requires it be queryable
rather than a log file, so it is a Postgres table and not a file on disk:

`(seq, ts, actor, event_type, subject_id, reason_code, payload jsonb, prev_hash, hash)`

with views per consumer (control room, metrics, per-agent detail panels).

Two properties beyond "it's a table":

**Hash chained.** Each row hashes its own contents plus the previous row's hash. Principle 5
is "evidence over assertion", and §7a extends that to not believing our own bank — a trail
that we could silently edit would make both claims hollow. The chain costs about an hour and
answers "could you have doctored this?" in the panel round.

**`reason_code` is a closed enum**, shared by code, control room and metrics. §9 requires
refusals broken down by check, and free-text reasons do not aggregate. Initial members, to be
extended only deliberately: `agent_signature_invalid`, `mandate_signature_invalid`,
`mandate_expired`, `agent_mandate_mismatch`, `exceeds_remaining_balance`,
`category_not_authorised`, `outside_validity_window`, `nonce_replayed`, `request_stale`,
`prompt_injection_detected`, `escalation_pattern_detected`, `below_margin_floor`,
`agent_blocked`, `ceiling_exceeded_for_tier`, `treasury_buffer_insufficient`,
`bank_line_unmatched`, `bank_line_ambiguous`.

## Consequences

Adding a refusal path means adding an enum member, which is the point — it makes new refusal
reasons visible in review instead of appearing as a novel string in production.

Append-only means corrections are new rows, never updates. Nothing in the system may
`UPDATE` or `DELETE` from this table.
