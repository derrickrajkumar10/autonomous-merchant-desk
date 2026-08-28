"""The sequence is monotonic under concurrent writes.

User story 10: ordering must be unambiguous when timestamps collide. Under load,
several threads write at once; the sequence they land on must be a single gapless
run, the timestamps must never contradict it, and the chain they build must verify.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from desk.audit import AuditTrail, EventType

WRITERS = 16
ENTRIES_EACH = 25
TOTAL = WRITERS * ENTRIES_EACH


def write_concurrently(trail: AuditTrail) -> list[int]:
    """Every writer appends at once. Returns the sequence numbers awarded, in no order."""

    def write(writer: int) -> list[int]:
        return [
            trail.record(
                actor=f"agent-{writer}",
                event_type=EventType.REQUEST_RECEIVED,
                subject_id=f"agent-{writer}",
                payload={"n": n},
            ).seq
            for n in range(ENTRIES_EACH)
        ]

    with ThreadPoolExecutor(max_workers=WRITERS) as executor:
        return [seq for seqs in executor.map(write, range(WRITERS)) for seq in seqs]


def test_the_sequence_is_gapless_and_awarded_once_each(trail: AuditTrail) -> None:
    awarded = write_concurrently(trail)

    assert sorted(awarded) == list(range(1, TOTAL + 1))


def test_timestamps_never_contradict_the_sequence(trail: AuditTrail) -> None:
    """The property that makes the sequence the tie-break rather than a second opinion.

    Each entry's timestamp is taken while its place in the chain is held, so a later
    entry can never carry an earlier timestamp.

    This is a race detector, and it detects in one direction only. A correct
    implementation cannot fail it, because the timestamp is sampled under the same
    lock that awards the sequence. A broken one — sampling the clock before
    serialising — fails it about five runs in six at this contention, so it is a
    guard that occasionally misses rather than one that occasionally cries wolf.
    """
    write_concurrently(trail)

    stamps = [entry.ts for entry in trail.query()]

    assert stamps == sorted(stamps)


def test_a_concurrently_built_chain_still_verifies(trail: AuditTrail) -> None:
    write_concurrently(trail)

    report = trail.verify()

    assert report.ok
    assert report.entries_checked == TOTAL


def test_each_writer_reads_back_its_own_entries_in_order(trail: AuditTrail) -> None:
    write_concurrently(trail)

    for writer in range(WRITERS):
        entries = trail.query(subject_id=f"agent-{writer}")
        assert [entry.payload["n"] for entry in entries] == list(range(ENTRIES_EACH))
        assert [entry.seq for entry in entries] == sorted(entry.seq for entry in entries)
