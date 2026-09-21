# Scripted answers for the fake provider

`LLM_MODE=fake` (the default) routes every task to
`ros/llm/providers/fake.py`, which never opens a socket. It answers in one of two
ways:

1. **a fixture from this directory**, if `<task>.json` exists and one of its entries
   matches the request;
2. **otherwise a generated answer** (`ros/llm/providers/synthetic.py`) built from
   whatever was sent — signals quoting the words that were actually in the prompt,
   proposals citing refs that really appear in the input, a chat reply that mentions
   what the person just said.

Use a fixture when a test or a demo needs one *exact* answer. Use the generated path
for everything else; it is what keeps the fake useful as new schemas are added.

## File name

One file per task, named exactly as the task is in `config/model_routing.yaml`:

```
tests/fixtures/llm/chat.reply.json
tests/fixtures/llm/extract.signals.json
tests/fixtures/llm/interpret.recognize.json
```

## Format

A file is either a single reply object, a list of them, or `{"replies": [...]}`.
Entries are tried in order and **the first match wins**, so put the specific ones
first and an entry with no `match` last as a catch-all.

| key | type | meaning |
|---|---|---|
| `match` | string, optional | Case-insensitive substring. The entry is used only if the text sent to the model contains it. Omit to always match. |
| `text` | string | What the model "said". For a structured task this is ignored if `parsed` is set. |
| `parsed` | object, optional | The structured answer, as JSON. It is validated against the task's schema in `ros/schemas/llm_io.py`, so a typo here fails the test loudly instead of quietly. |
| `stop_reason` | string, optional | Defaults to `end_turn`. |
| `status` | string, optional | `ok` (default), `refused`, `truncated` or `error` — see below. |

### A chat example

`chat.reply.json`:

```json
{
  "replies": [
    {
      "match": "dentist",
      "text": "You've mentioned the dentist before. What keeps getting in the way?"
    },
    {
      "text": "Thanks for telling me that. What was that like for you?"
    }
  ]
}
```

### A structured example

`extract.signals.json`:

```json
[
  {
    "match": "dentist",
    "parsed": {
      "signals": [
        {
          "message_ref": "M1",
          "kind": "behavior",
          "subject": "self",
          "topic": "health.care",
          "content": "The user has postponed a dentist appointment again.",
          "quote_text": "I kept putting off the dentist again this week",
          "polarity": -1,
          "strength": 1.0,
          "sensitive_category": null,
          "context_tags": ["health"]
        }
      ],
      "memory_candidates": [],
      "skipped_reason": null
    }
  }
]
```

**`quote_text` must be a verbatim substring of the message it came from.**
`ros/engine/signals.py` checks `message.content[start:end] == quote_text` before it
will store anything, and drops the signal if it does not match. A fixture with an
invented quote produces a demo with no evidence behind the cards.

### Scripting a failure

The engine has to survive a refusal and a truncation, so the fake can produce them
on demand:

```json
[
  {"match": "self-harm", "status": "refused"},
  {"match": "enormous", "status": "truncated"}
]
```

`refused` raises `RefusalError` (never retried), `truncated` raises `TruncatedError`
(retried once at lower effort), `error` raises a retryable `ProviderError`.

## Determinism

With no fixture the answer is still stable: the fake seeds its randomness from the
task name and the request text, so the same input gives the same output in this
process and the next. Tests can assert on generated answers without recording them.

Streaming chunks the text six words at a time. The pause between chunks is
`FakeProvider(delay=...)` — `0.0` everywhere in tests, around `0.02` for a demo where
an instant wall of text looks broken.
