"""What the Inspector is allowed to say back: one finding, and a reason for it.

The Inspector reads attacker-authored text. The single most dangerous thing it could
have is a free-form output channel, because a model that has just been talked into
something writes that something into a free-form field. So its answer is pinned to
this shape and nothing else: a member of a two-value enum, and a sentence saying why.

``read_verdict`` is the gate. Anything that is not exactly this shape -- a missing
field, an unknown finding, a reason that is empty or absurdly long, a JSON object with
extra keys -- is not a verdict, and it raises rather than being coerced into one. The
caller in ``inspect.py`` turns that raise into a refusal, because a message the
Inspector could not return a clean verdict on is a message the Desk has not cleared.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

#: The longest reason the Desk will store. A reason is one sentence for a human and for
#: the trail; a model returning a page of it is either confused or being steered, and
#: either way the Desk does not want the page in an audit entry.
MAX_REASON = 600


class Finding(StrEnum):
    """The Inspector's verdict on a piece of text. Two values, and the set is closed.

    There is no ``suspicious`` or ``uncertain`` in here on purpose. The Inspector's
    output is consumed as *refuse* or *do not refuse*, so a third value would have to
    collapse to one of those anyway -- and collapsing it here, in a named member,
    is clearer than collapsing it in a branch three modules away.
    """

    #: The text is information -- a question, a note, a preamble. Nothing in it is
    #: addressed to the Desk as an instruction.
    CLEAR = "clear"
    #: The text contains an instruction aimed at the Desk: an attempt to change how it
    #: behaves, drop a constraint, or ignore its own rules.
    PROMPT_INJECTION = "prompt_injection"


class MalformedVerdict(ValueError):
    """The Inspector returned something that is not a verdict.

    Not a finding of its own -- it is the absence of one. ``inspect.py`` treats it the
    way it treats an Inspector that could not be reached at all: fail closed, refuse
    the message, and record that the Inspector's answer was unreadable.
    """


@dataclass(frozen=True)
class Verdict:
    """One finding and the reason for it. The whole of what an Inspector may return."""

    finding: Finding
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.finding, Finding):
            raise MalformedVerdict(
                f"a verdict's finding is one of {[f.value for f in Finding]}, "
                f"not {self.finding!r}"
            )
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise MalformedVerdict("a verdict carries a reason, and this one has none")
        if len(self.reason) > MAX_REASON:
            raise MalformedVerdict(
                f"the verdict's reason is {len(self.reason)} characters; the Desk stores "
                f"at most {MAX_REASON}, and a reason past that is not one sentence about "
                f"one message"
            )

    @property
    def is_injection(self) -> bool:
        return self.finding is Finding.PROMPT_INJECTION


def read_verdict(value: Any) -> Verdict:
    """A ``Verdict`` from whatever the Inspector returned, or ``MalformedVerdict``.

    Accepts a ``Verdict`` unchanged and a plain mapping with exactly ``finding`` and
    ``reason``. Everything else -- extra keys, a finding outside the enum, a
    non-mapping -- is refused here rather than downstream, because the point of pinning
    the output is lost the moment something off-shape is allowed through.
    """
    if isinstance(value, Verdict):
        return value
    if not isinstance(value, Mapping):
        raise MalformedVerdict(f"a verdict is an object with a finding and a reason, not {value!r}")

    keys = set(value.keys())
    if keys != {"finding", "reason"}:
        raise MalformedVerdict(
            f"a verdict has exactly the keys 'finding' and 'reason'; this one has {sorted(keys)}"
        )
    try:
        finding = Finding(value["finding"])
    except ValueError:
        raise MalformedVerdict(
            f"{value['finding']!r} is not a finding; the set is {[f.value for f in Finding]}"
        ) from None
    return Verdict(finding=finding, reason=value["reason"])
