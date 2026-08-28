"""The sequence is monotonic under concurrent writes.

User story 10: ordering must be unambiguous when timestamps collide. Under load,
several threads write at once; the sequence they land on must still be a single
gapless run, and the chain they build must still verify.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from desk.audit import AuditTrail, EventType

WRITERS = 8
ENTRIES_EACH = 12


def test_the_sequence_is_monotonic_under_concurrent_writes(trail: AuditTrail) -> None:
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
        awarded = [seq for seqs in executor.map(write, range(WRITERS)) for seq in seqs]

    assert sorted(awarded) == list(range(1, WRITERS * ENTRIES_EACH + 1))


def test_a_concurrently_built_chain_still_verifies(trail: AuditTrail) -> None:
    def write(writer: int) -> None:
        for n in range(ENTRIES_EACH):
            trail.record(
                actor=f"agent-{writer}",
                event_type=EventType.REQUEST_RECEIVED,
                subject_id=f"agent-{writer}",
                payload={"n": n},
            )

    with ThreadPoolExecutor(max_workers=WRITERS) as executor:
        list(executor.map(write, range(WRITERS)))

    report = trail.verify()

    assert report.ok
    assert report.entries_checked == WRITERS * ENTRIES_EACH


def test_each_writer_reads_back_its_own_entries_in_order(trail: AuditTrail) -> None:
    def write(writer: int) -> None:
        for n in range(ENTRIES_EACH):
            trail.record(
                actor=f"agent-{writer}",
                event_type=EventType.REQUEST_RECEIVED,
                subject_id=f"agent-{writer}",
                payload={"n": n},
            )

    with ThreadPoolExecutor(max_workers=WRITERS) as executor:
        list(executor.map(write, range(WRITERS)))

    for writer in range(WRITERS):
        entries = trail.query(subject_id=f"agent-{writer}")
        assert [entry.payload["n"] for entry in entries] == list(range(ENTRIES_EACH))
        assert [entry.seq for entry in entries] == sorted(entry.seq for entry in entries)
