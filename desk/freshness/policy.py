"""How fresh is fresh enough, who a proof has to be addressed to, and where that is set.

Three numbers, and none of them is AP2's to give. The specification is explicit about
what it leaves open (``docs/research/ap2-mandate-model.md``, section 3): it is silent on
nonce length, on how long a verifier retains seen nonces, and on any clock-skew
allowance for ``iat``. So the window is our choice, and a choice a merchant will want to
make differently to us -- which is why it is read from the environment rather than
written in ``check.py`` (FR-3.4).

- **The window** is how old a proof of possession may be. Short, because its whole job
  is to make captured traffic worthless quickly.
- **The clock skew** is how far the counterparty's clock may disagree with ours before
  an honest agent starts being refused. It widens the window at *both* ends: a slow
  clock makes a proof look older than it is and a fast one makes it look future-dated,
  and neither is a replay.
- **The audience** is the name a proof has to be addressed to. Without it, a proof of
  possession an agent made for some other verifier could be handed to us, and it would
  verify -- it is a real signature by the right key over the right presentation. What
  makes it not ours is that it never said our name.

A value that is set and unreadable raises rather than falling back to the default, and
an empty value counts as unreadable. An operator who widened the window and got the
default anyway would believe a setting that is not in force, which is worse than being
told at start-up that they made a typo. Taking the default is spelled *unset*, which is
a thing an operator can mean; ``STITCHAI_DESK_AUDIENCE=`` is not.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Self

#: The three environment variables, and what the Desk uses when none is set.
FRESHNESS_WINDOW_VARIABLE = "STITCHAI_FRESHNESS_WINDOW_SECONDS"
CLOCK_SKEW_VARIABLE = "STITCHAI_CLOCK_SKEW_SECONDS"
AUDIENCE_VARIABLE = "STITCHAI_DESK_AUDIENCE"

#: Two minutes. Long enough for an agent to sign, send and be read on a slow link;
#: short enough that a captured presentation is worthless by the time it is replayed.
DEFAULT_WINDOW_SECONDS = 120

#: Thirty seconds either side, which is roughly what an unsynchronised host drifts to.
DEFAULT_CLOCK_SKEW_SECONDS = 30

#: What the Desk answers to. AP2's own example ``aud`` is the word ``"merchant"``; a
#: name rather than a role, so that two merchants are not one audience.
DEFAULT_AUDIENCE = "stitchai-desk"


class Misconfigured(ValueError):
    """A freshness setting the Desk will not guess at, naming the variable to fix."""


@dataclass(frozen=True)
class FreshnessPolicy:
    """The window, the skew and the audience check 4 evaluates against.

    One object rather than three parameters, because they are read together and
    recorded together: every check-4 entry carries the policy it was decided under, so
    a refusal read a month later says what the window was at the time rather than what
    it is now.
    """

    window: timedelta
    clock_skew: timedelta
    audience: str

    def __post_init__(self) -> None:
        if self.window <= timedelta(0):
            raise Misconfigured(
                f"the freshness window is {self.window}, which accepts nothing. Set "
                f"{FRESHNESS_WINDOW_VARIABLE} to a positive number of seconds."
            )
        if self.clock_skew < timedelta(0):
            raise Misconfigured(
                f"the clock skew allowance is {self.clock_skew}. A negative allowance "
                f"narrows the window from both ends; set {CLOCK_SKEW_VARIABLE} to zero "
                f"or more."
            )
        if not self.audience.strip():
            raise Misconfigured(
                f"the Desk has no audience name, so no proof can be addressed to it. "
                f"Set {AUDIENCE_VARIABLE}."
            )

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> Self:
        """The policy as this deployment has it set. Defaults where nothing is set."""
        source = os.environ if environment is None else environment
        return cls(
            window=timedelta(
                seconds=_seconds(source, FRESHNESS_WINDOW_VARIABLE, DEFAULT_WINDOW_SECONDS)
            ),
            clock_skew=timedelta(
                seconds=_seconds(source, CLOCK_SKEW_VARIABLE, DEFAULT_CLOCK_SKEW_SECONDS)
            ),
            audience=_text(source, AUDIENCE_VARIABLE, DEFAULT_AUDIENCE),
        )

    def covers(self, made_at: datetime, *, now: datetime) -> bool:
        """Whether something stamped ``made_at`` counts as current.

        Bounded in both directions. Too old is the replay this check exists for; too
        far in the future is a clock nobody can reconcile with ours, and accepting one
        would hand an agent a proof that stays fresh for as long as it lied by.
        """
        return self.stale_before(now) <= made_at <= now + self.clock_skew

    def stale_before(self, now: datetime) -> datetime:
        """The instant a proof stops being current, and a nonce stops being worth keeping.

        One method for both because they must be the same instant. ``NonceStore.forget``
        explains the coupling: forgetting a nonce is safe only while the presentation it
        belonged to would be refused as stale anyway.
        """
        return now - self.window - self.clock_skew

    def describe(self) -> dict[str, Any]:
        """The policy as trail evidence. Seconds rather than ``timedelta``, which is not JSON."""
        return {
            "window_seconds": int(self.window.total_seconds()),
            "clock_skew_seconds": int(self.clock_skew.total_seconds()),
            "audience": self.audience,
        }


def _seconds(environment: Mapping[str, str], variable: str, default: int) -> int:
    setting = _set_to_something(environment, variable, default)
    if setting is None:
        return default
    try:
        return int(setting)
    except ValueError:
        raise Misconfigured(
            f"{variable} is {setting!r}, which is not a number of seconds"
        ) from None


def _text(environment: Mapping[str, str], variable: str, default: str) -> str:
    setting = _set_to_something(environment, variable, default)
    return default if setting is None else setting


def _set_to_something(environment: Mapping[str, str], variable: str, default: object) -> str | None:
    """The value, ``None`` for unset, and a refusal for set-but-empty.

    The middle case is the one worth spelling out. Blank is not a quieter way of saying
    unset: nobody exports an empty window by accident and means the default, and reading
    it as one hides the typo it almost always is.
    """
    setting = environment.get(variable)
    if setting is None:
        return None
    if not setting.strip():
        raise Misconfigured(
            f"{variable} is set to an empty value. Unset it to take the default of "
            f"{default!r}; the Desk will not read blank as a setting."
        )
    return setting
