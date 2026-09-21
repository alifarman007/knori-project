# ADR-004 — A provider-neutral LLM layer, with models chosen by config

**Status:** accepted · **Date:** Phase 1 planning · **Source:** `plan.md` §6

## Context

Three requirements pulled in different directions.

1. **The owner requires that any task can be switched to OpenAI by configuration**,
   with no product-code change.
2. **The product must run with no API key at all** — for the test suite, for CI, and
   so a demo is possible before a single dollar of credit is bought.
3. **Every model call must be priced and recorded**, because the cost caps in
   `config/limits.yaml` are a hard stop, not a report.

Meanwhile the two SDKs disagree about almost everything: structured output, thinking
and effort, prompt caching, streaming, and what a refusal looks like. Writing product
code against either one directly would embed those differences in the callers.

## Decision

**All model access goes through one router. Product code never names a model.**

```python
await router.run(
    "interpret.recognize",
    prompt="interpret/recognize",
    vars={...},
    schema=InterpretationBatch,
    user_id=..., job_id=..., session=...,
)
```

Four parts:

* **Protocols** (`ros/llm/base.py`) — `LLMProvider` with `complete`, `stream`,
  `complete_structured` and `count_tokens`, plus a `Capabilities` record; and
  `EmbeddingProvider` with `model_id`, `dimensions` and `embed`. Requests and results
  are provider-neutral dataclasses. **There is no `temperature`, `top_p` or `top_k`** —
  Opus 5 and Sonnet 5 return 400 for all three.
* **Routing** (`config/model_routing.yaml`) — one row per task giving the provider,
  model, thinking mode, effort, `max_tokens`, prompt and prompt version. Any row can
  be overridden from the environment: `KNORI_ROUTE__chat_reply=openai:gpt-5.6-sol:medium`.
  The router validates at boot that every provider has credentials and supports what
  its tasks need, and refuses to start otherwise.
* **Adapters** (`ros/llm/providers/`) — the **only** modules allowed to import
  `anthropic` or `openai`. Each one owns its SDK's quirks: how structured output is
  requested, where the cache breakpoint goes, how effort maps, how a refusal is
  detected.
* **The ledger** (`ros/llm/cost.py`) — an `llm_calls` row for **every** attempt: ok,
  error, refused or truncated. Priced by the **response's** model, which can differ
  from the requested one when Anthropic's server-side refusal fallback runs.

### The fake provider

`LLM_MODE=fake` is the default. It resolves every task to
`ros/llm/providers/fake.py`, which answers either from a scripted fixture or from
`synthetic.build` — a generator that reads the request and writes a plausible,
schema-valid answer.

The rule that makes it worth having: **`quote_text` must be a verbatim substring of
the input.** The engine checks `message.content[start:end] == quote_text` before it
will store a signal, so a fake that invented quotes would produce a demo with no
evidence in it. Everything is deterministic — the only randomness is seeded from the
request itself.

This is why `./run test`, CI and a keyless local demo all work.

### Schemas that satisfy both providers

Every structured schema in `ros/schemas/` is authored to the intersection of both
vendors' strict-JSON rules: `additionalProperties: false`, optional fields nullable,
no unions of objects, at most five levels of nesting. Wire schemas carry **no numeric
or length constraints** — the APIs strip them, and a strict SDK parse would then fail
the whole batch on one bad field. Instead the code parses leniently and clamps or
drops per item, counting the drops.

## Consequences

**Good.**

* Switching `chat.reply` to GPT is one line of YAML or one environment variable.
* The whole product runs and demos with no API key.
* Cost is enforceable because every call is recorded, including the failures.
* Prompts are versioned files (`ros/prompts/<task>/v<N>.md`), immutable once merged,
  and every `llm_calls` row records the prompt name, version and hash that produced
  it. A change in behaviour can be traced to a prompt.
* When a vendor changes an SDK, exactly one file changes.

**Costs, accepted.**

* The abstraction cannot expose a feature only one vendor has. Anthropic's prompt
  caching is modelled as "cache: bool + ttl" on request blocks, and OpenAI ignores it
  because OpenAI caches prefixes automatically.
* Schemas are written to the intersection of two rule sets, which is more restrictive
  than either alone.
* The indirection is real: reading a call means reading the router, the routing file
  and the adapter.

**The open risk.** `plan.md` §6.3 is a careful specification of the Anthropic SDK —
`messages.parse` with `output_format`, `output_config={"effort": …}`,
`thinking={"type": "adaptive"|"disabled"}`, never assistant prefill, thinking tokens
counting against `max_tokens`. **None of it has been verified against a live API.**
There are no tests carrying the `live` marker. Until that is done, the adapter is a
specification rather than a measurement, and it is the first thing to check before a
live deployment ([TESTING.md](../TESTING.md)).

## When to revisit

If a vendor feature becomes important enough to be worth breaking the abstraction —
Message Batches at 50% off, for instance, which was cut from Phase 1 because it saves
under a dollar a day at beta size. The protocol method stays; the job does not.
