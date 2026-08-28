# Check 5 is one-directional: it can refuse, never grant

The check-5 inspector reads attacker-authored text in order to decide whether that text is
information or an instruction aimed at the Desk. The component whose job is catching prompt
injection is therefore the component most exposed to it, and RT-2's adaptive attacker will
find that immediately.

We constrain it so that a fully compromised inspector is still harmless. Checks 1–4 are the
only things that can grant authority. **Check 5 may only lower a trust score or refuse a
request; it has no path to approve one.** An attacker who completely owns the inspector can,
at most, get themselves refused.

Three supporting properties: the inspector is a classifier with **no tools** and cannot act;
its output is pinned by structured outputs to a verdict enum plus a reason string, leaving no
free-form channel to hijack; and untrusted text arrives in a `user` message under an explicit
delimiter, never in the system prompt.

## Consequences

Do not "fix" this later by letting a confident check-5 pass raise a ceiling or skip a
deterministic check. The asymmetry is the security property, and it is invisible in the code
unless you know it was deliberate.

A false refusal is an acceptable failure mode here; a false approval is not. Bias thresholds
accordingly — the same rule §5.9a applies to matches.
