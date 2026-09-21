"""Recognition quality evals (plan.md §10).

Four modules, each with one job:

``corpus``
    the personas and their labels — what should be noticed, and what must not be.
``runner``
    replays one persona through the real pipeline into a rolled-back transaction.
``judges``
    the two model calls that read meaning, and an offline stand-in for them.
``metrics``
    pure scoring functions, from grounding to neutrality.

Run it with ``./run eval``. Offline it is free and deterministic; with
``LLM_MODE=live`` it spends real money and refuses to start without ``--yes``.
Reports land in ``evals/reports/`` and are not committed.
"""
