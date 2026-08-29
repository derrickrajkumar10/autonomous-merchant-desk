"""The freshness policy: what is configurable, and what a bad setting does.

No database here. These are the three numbers and the arithmetic between them, and the
one behaviour worth insisting on is that a setting the Desk cannot read stops it rather
than being silently replaced by a default.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from desk.freshness import (
    AUDIENCE_VARIABLE,
    CLOCK_SKEW_VARIABLE,
    DEFAULT_AUDIENCE,
    DEFAULT_CLOCK_SKEW_SECONDS,
    DEFAULT_WINDOW_SECONDS,
    FRESHNESS_WINDOW_VARIABLE,
    FreshnessPolicy,
    Misconfigured,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def test_an_unconfigured_desk_gets_the_documented_defaults() -> None:
    """Running with nothing set is a supported way to run, and it is short by default."""
    policy = FreshnessPolicy.from_environment({})

    assert policy.window == timedelta(seconds=DEFAULT_WINDOW_SECONDS)
    assert policy.clock_skew == timedelta(seconds=DEFAULT_CLOCK_SKEW_SECONDS)
    assert policy.audience == DEFAULT_AUDIENCE


def test_each_setting_is_read_from_its_own_variable() -> None:
    policy = FreshnessPolicy.from_environment(
        {
            FRESHNESS_WINDOW_VARIABLE: "45",
            CLOCK_SKEW_VARIABLE: "5",
            AUDIENCE_VARIABLE: "desk.example.com",
        }
    )

    assert policy.window == timedelta(seconds=45)
    assert policy.clock_skew == timedelta(seconds=5)
    assert policy.audience == "desk.example.com"
    assert policy.describe() == {
        "window_seconds": 45,
        "clock_skew_seconds": 5,
        "audience": "desk.example.com",
    }


def test_a_setting_the_desk_cannot_read_stops_it_rather_than_defaulting() -> None:
    """A typo that silently reverts to the default is worse than one that raises.

    An operator who widened the window and got 120 seconds anyway would believe a
    setting that is not in force, and would only find out from a refusal they could not
    explain.
    """
    with pytest.raises(Misconfigured, match=FRESHNESS_WINDOW_VARIABLE):
        FreshnessPolicy.from_environment({FRESHNESS_WINDOW_VARIABLE: "two minutes"})


def test_a_setting_left_blank_is_a_typo_rather_than_a_way_to_ask_for_the_default() -> None:
    """Unset means the default. Set-to-empty means somebody meant to write something.

    Read as unset, a blank ``STITCHAI_DESK_AUDIENCE`` would put the Desk back on the
    shipped name and refuse every honest agent that had been told the real one -- with a
    refusal reason about freshness, which is a true sentence about the wrong thing.
    """
    for variable in (FRESHNESS_WINDOW_VARIABLE, CLOCK_SKEW_VARIABLE, AUDIENCE_VARIABLE):
        with pytest.raises(Misconfigured, match=variable):
            FreshnessPolicy.from_environment({variable: ""})


def test_a_window_that_accepts_nothing_is_refused_at_construction() -> None:
    """Zero is not a very strict Desk; it is a Desk that refuses every honest agent."""
    with pytest.raises(Misconfigured, match=FRESHNESS_WINDOW_VARIABLE):
        FreshnessPolicy(window=timedelta(0), clock_skew=timedelta(0), audience="desk")
    with pytest.raises(Misconfigured, match=CLOCK_SKEW_VARIABLE):
        FreshnessPolicy(window=timedelta(seconds=60), clock_skew=-timedelta(1), audience="desk")
    with pytest.raises(Misconfigured, match=AUDIENCE_VARIABLE):
        FreshnessPolicy(window=timedelta(seconds=60), clock_skew=timedelta(0), audience="  ")


def test_the_window_is_bounded_at_both_ends_and_skew_widens_both() -> None:
    """Too old is the replay; too far ahead is a clock that cannot be reconciled.

    The skew allowance applies in both directions because a counterparty clock that
    runs slow makes an honest proof look old, and one that runs fast makes it look
    future-dated. Neither is a replay.
    """
    policy = FreshnessPolicy(
        window=timedelta(seconds=60), clock_skew=timedelta(seconds=10), audience="desk"
    )

    assert policy.covers(NOW, now=NOW)
    assert policy.covers(NOW - timedelta(seconds=69), now=NOW)
    assert not policy.covers(NOW - timedelta(seconds=71), now=NOW)
    assert policy.covers(NOW + timedelta(seconds=9), now=NOW)
    assert not policy.covers(NOW + timedelta(seconds=11), now=NOW)


def test_the_retention_horizon_is_the_far_edge_of_the_window() -> None:
    """One method for both, because a nonce is worth keeping exactly while it is needed."""
    policy = FreshnessPolicy(
        window=timedelta(seconds=60), clock_skew=timedelta(seconds=10), audience="desk"
    )

    assert policy.stale_before(NOW) == NOW - timedelta(seconds=70)
    assert not policy.covers(policy.stale_before(NOW) - timedelta(seconds=1), now=NOW)
