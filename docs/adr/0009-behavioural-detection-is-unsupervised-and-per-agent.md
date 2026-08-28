# Behavioural detection scores deviation from an agent's own history, not similarity to known attacks

The behavioural half of check 5 (FR-3.2) is unsupervised and per-agent. It scores each request
against that agent's own rolling baseline — amount versus own mean and max, inter-request
interval, category churn, refusal rate, time-to-escalation — rather than classifying it against
a taxonomy of known attacks.

A supervised classifier is tempting because labels look free: we generate the swarm, so we know
which agents are adversarial. But those labels are ours, so the detector would learn to detect
attacks we authored. That collides with principle 4 ("general defences, not a rule per attack")
and with RT-3, whose held-out classes exist precisely to expose that failure. A supervised
detector over our own attack taxonomy is a rule per attack wearing a neural network.

The unsupervised framing also matches what FR-4.5 actually asks for. Trust farming is defined
self-relatively — disproportionate *relative to what this agent has done before* — so the signal
is deviation from own history by construction.

## Consequences

This contradicts CONTEXT.md §8's original line that deep learning belongs in behavioural fraud
detection. §8 was wrong: this is sequence anomaly detection, not classification. If a learned
model earns its place here it is a sequence model over request histories, still trained without
attack labels.

Do not add attack labels later to "improve accuracy" on the development attack set. Accuracy
there is not the metric; RT-3's held-out classes are.
