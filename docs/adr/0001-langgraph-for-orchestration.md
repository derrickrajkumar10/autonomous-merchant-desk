# LangGraph for agent orchestration

The Desk moves money, so the orchestration layer needs durable state, checkpointing,
interrupts and retries as first-class concepts rather than bolt-ons. We chose LangGraph
over LlamaIndex (a retrieval layer, not an orchestrator) and over off-the-shelf agent
runtimes, because explicit, inspectable state is also far easier to defend in a panel
interview when someone asks "where exactly does it decide?"

## Consequences

Ties `desk/` to Python. Graph state must stay serialisable, since checkpointing is the
reason we picked it.
