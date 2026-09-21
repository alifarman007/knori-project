# ADR-005 — Exact cosine search, no HNSW index

**Status:** accepted · **Date:** Phase 1 planning · **Source:** `plan.md` §2.3, §4.1

## Context

Five things in KnoRI need vector similarity:

1. retrieving memory items and past messages for the chat context;
2. finding the neighbourhood of signals to give the interpreter;
3. deciding whether two open interpretations are duplicates;
4. deciding whether a claim is the same as something the user already said or denied;
5. widening the rescoring cascade after a correction.

pgvector offers approximate indexes — HNSW and IVFFlat — that make nearest-neighbour
search sublinear. The reflex is to add one.

There are two reasons not to.

**Correctness.** Every query here is filtered by `user_id`. An approximate index
answers by walking its graph and then discarding rows that fail the filter. If a
user's rows are a small fraction of the table, the walk can return *k* neighbours that
are almost all other people's, leave three of that user's, and report those three as
the top three when they are not. The index does not know it was wrong, and neither
does the caller. Postgres has planner heuristics that sometimes avoid this and
sometimes do not. "Sometimes the right answer" is a bad property for the component
that decides whether a user's rejection still applies.

**Size.** A beta user has thousands of vectors, not millions. A sequential scan of a
few thousand 1536-dimension vectors is milliseconds. An index would be solving a
problem that does not exist yet, and would have to be tuned (`m`, `ef_construction`,
`ef_search`) without data to tune against.

## Decision

**Exact cosine over the user's own rows. No HNSW, no IVFFlat.**

* `vector(1536)` columns, alongside an `embedding_model` column on every table that
  has one.
* A **btree on `user_id`** does the only filtering that matters. Postgres uses it, then
  scans that user's rows exactly.
* Every query starts from `WHERE user_id = :user_id`.
* The score handed back is `1 - (a <=> b)` — cosine similarity, never a raw pgvector
  distance — so callers compare similarities and a different retriever can answer the
  same way.
* **Every similarity lookup in the system goes through the `Retriever` protocol**
  (`ros/memory/protocols.py`), implemented by `ros/persistence/pg_memory.py`.
* **Cutoffs are keyed by embedding model** in `config/thresholds.yaml`
  (`similarity.text-embedding-3-small.{dedup, deny_same, deny_different, memory,
  retrieval, cascade}`). A cutoff is a property of the model that produced the
  vectors, not a universal constant.

## Consequences

**Good.**

* Results are correct under a per-user filter, always. There is no case where the
  engine silently sees the wrong neighbours.
* Nothing to tune, and no index build or rebuild during a migration.
* An embedding failure degrades cleanly: the row is still written, without a vector,
  and `embed_pending` fills it in later. There is no index to keep consistent.
* Swapping embedding models is a documented, bounded operation: re-embed, add a new
  cutoff block, re-run the calibration pairs.

**Costs, accepted.**

* Search is linear in one user's vectors. Fine at thousands; not at millions.
* Cross-user search is not possible. Nothing in Phase 1 wants it, and the data rules
  forbid it.
* The comparison is done in SQL rather than in an index, so a very chatty user pays
  slightly more on every chat turn than a quiet one.

## When to revisit

The trigger is measurable, not a feeling: **when a single user's vector count makes
retrieval a visible part of chat latency.** Roughly 100k vectors per user is where
this starts to be worth looking at.

If that happens, the change is contained by design. Every lookup already goes through
`Retriever`, so a new implementation is a new class, not a rewrite — which is also
the Phase 5 promise about being retrieval-agnostic. The safe order would be: a partial
HNSW index per user, or a two-stage search (approximate over a generous *k*, then an
exact re-rank of that user's hits), with the correctness property re-verified rather
than assumed.
