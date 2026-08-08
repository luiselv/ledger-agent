# ledger-agent

An LLM agent that reads a vendor invoice and posts a balanced double-entry journal
entry — with the evaluation harness and the experiment loop around it.

The agent is the small part. The interesting part is the machinery that tells you
whether it actually works, and which design decisions are the ones carrying the result.

> **Scope, stated plainly.** ~1,600 lines, synthetic data, built as a portfolio
> artifact. It is a deliberate miniature of a pattern I run in production, not a
> production system. Everything it claims is measured by code in this repo, and the
> numbers below were produced by `uv run python -m eval.experiment`.

---

## The result

20 labeled invoices × 4 configurations, temperature 0:

| config | posted | 1st-try post | exact match | macro F1 | mean iters | tokens |
|---|---|---|---|---|---|---|
| haiku, no validator | 100% | 100% | 95% | 0.972 | 2.00 | 79,309 |
| haiku, with validator | 100% | 100% | 95% | 0.972 | 2.95 | 151,248 |
| sonnet, no validator | 100% | 100% | 90% | 0.944 | 2.00 | 78,873 |
| sonnet, with validator | 100% | 100% | 95% | 0.972 | 2.05 | 100,828 |

**I built the validation tool expecting it to be the thing that made this work. The
evaluation says it did nothing.**

Across all 80 runs, not one post attempt was ever rejected — `1st-try post` is 100%
everywhere. The validator never had an error to catch, because `post_journal_entry`
*already* refuses an unbalanced entry. I had put the enforcement in the terminal tool
and then built a second tool to enforce the same invariant earlier. On Haiku that
redundancy cost **1.9× the tokens** (79k → 151k) and bought nothing.

This is the finding I would have missed by reasoning about the design instead of
measuring it. The architecture *looked* right — a validate-then-post loop is the
obvious shape — and the obvious shape was one tool too many. The correct lesson is
narrower than "validators don't help": put the invariant at the boundary that cannot
be bypassed, then check whether anything upstream is still earning its cost.

Two more things the numbers say:

**The bigger model was not better.** Sonnet matched Haiku at best and was worse
without the validator, at higher cost per token. There is nothing here that a
frontier model solves and a small one doesn't.

**The one consistent failure is a judgment call, not a mechanical error.** Every
configuration fails the same case — an invoice with $1,240 of monitors and $95 of
cables, where the cables belong in Office Supplies below the capitalization
threshold. All four runs fold the cables into Computer Equipment with the monitors.
That is a threshold the chart of accounts describes in prose and the model does not
reliably apply; the fix is a better-specified boundary, not a better model.

Sonnet-without-validator's extra miss (booking a quarterly software licence as a
prepaid asset) is a *single case*, and the validator only checks arithmetic — it
cannot plausibly influence account choice. I am not claiming that difference is real.
With n=20, one case is one case.

Both runs of the full matrix produced identical exact-match and macro-F1 figures, so
the numbers are at least reproducible. Raw per-case data:
[`results/latest.json`](results/latest.json). Full report with per-account
precision/recall/F1: [`results/latest.md`](results/latest.md).

---

## How it works

```
invoice text ──▶ agent loop (Claude + 3 tools) ──▶ posted journal entry
                       │
                       ├── search_accounts        read the chart of accounts
                       ├── validate_journal_entry arithmetic + referential checks
                       └── post_journal_entry     terminal; rejects invalid entries
                       │
                       └── same 3 tools also served over MCP (stdio)

eval/ ──▶ 20 labeled invoices ──▶ per-account P/R/F1 + end-to-end rates ──▶ results/
```

The model supplies judgment — reading the invoice, deciding that a laptop is capital
equipment and a coffee order is not. The tools supply what a computer is exact at:
lookup, arithmetic, and validation. No handler in `tools.py` calls an LLM.

### Three decisions worth explaining

**The chart of accounts is a schema `enum`, not a prompt instruction.**
`account_code` in the tool schema carries an enum generated from
[`chart_of_accounts.py`](src/ledger_agent/chart_of_accounts.py). An invented account
code is rejected by the provider's own schema validation before it reaches any code I
wrote. Constraining the vocabulary at the schema level removes a class of failure
rather than detecting it afterwards — and it means the chart and the model's
vocabulary cannot drift, because there is only one of them.

**A rejection is a successful tool call.**
When `post_journal_entry` refuses an entry, it returns *text the model can act on*:

```
REJECTED — the entry was not posted.
INVALID: fix the issues below and call this tool again.

- [UNBALANCED] The entry does not balance: debits total 1335.00, credits total
  1448.48, so credits exceed the other side by 113.48. A common cause is posting
  the net amount while the invoice total includes tax, or omitting the tax line
  entirely.
```

It does not raise. Bad arguments are the model's mistake and the model is the only
party who can fix them, so they go back through the channel the model reads. Errors
that are *ours* — a transport failure, a crash — are a different channel entirely.
Collapsing the two is how an agent that could have self-corrected ends up as a stack
trace instead.

(In this dataset the model never triggered a rejection, per the results above. The
path is exercised by [tests](tests/test_tools.py) rather than by the eval — which is
the honest reason to keep the tests.)

**Money is `Decimal`, never `float`.**
Binary floating point cannot represent `0.10`, so entries drift by a cent. In
double-entry bookkeeping "off by 0.01" is not a rounding nuisance, it is an entry the
ledger rejects. Rounding is `ROUND_HALF_UP`, the convention accountants expect, not
Python's default banker's rounding. There is
[a test](tests/test_tools.py) for the exact case `float` would silently pass.

### What the evaluation measures

Twenty hand-labeled synthetic invoices in [`eval/dataset/`](eval/dataset). They are
built to require real judgment, not pattern matching: an annual prepaid SaaS
subscription that is a *prepaid asset* rather than a subscription expense; one invoice
that splits across capital equipment, consumables, tax and payables; two invoices from
the same vendor where one charges tax and one does not.

Two metric families, because an agent is not a classifier:

- **Classification** — per-account precision, recall and F1 from confusion-matrix
  counts. Macro-averaged, not micro: a rare account should count as much as a common
  one, since rare classes are the ones a model quietly gives up on. Plain accuracy
  would hide that entirely.
- **End-to-end** — did it post at all, did the entry balance, did it reach *exactly*
  the expected set of accounts. A model can classify every line correctly and still
  fail to emit a valid entry.

A case that never posts contributes false negatives for every account it should have
hit. That is the honest reading: the accounts were not classified.

---

## Run it

```bash
uv sync --extra dev
```

Offline — no API key, this is what CI runs:

```bash
uv run pytest -q
```

The `pytest` suite covers validation logic, the metrics math, and the integrity of the
dataset itself: that every invoice's arithmetic closes, that no label references a
non-existent account, that the tax label matches the tax line. If the ground truth is
wrong, every number downstream is measuring the dataset's bugs instead of the agent's.

With an API key — one invoice, showing the agent's work:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

```bash
uv run python -m ledger_agent.cli eval/dataset/case_013_mixed_equipment_and_supplies.txt
```

Score one configuration, or reproduce the whole matrix:

```bash
uv run python -m eval.harness --limit 5
```

```bash
uv run python -m eval.experiment
```

### As an MCP server

The same three tools, same schemas, over stdio:

```bash
uv run python -m ledger_agent.mcp_server
```

[`mcp_server.py`](src/ledger_agent/mcp_server.py) defines no schemas of its own — it
iterates `tools.ALL_TOOLS` and hands MCP the same definitions the agent loop uses. One
source of truth, two transports, no drift.

---

## Layout

| path | what's in it |
|---|---|
| [`src/ledger_agent/chart_of_accounts.py`](src/ledger_agent/chart_of_accounts.py) | The accounts, and the enum the model is limited to |
| [`src/ledger_agent/schemas.py`](src/ledger_agent/schemas.py) | Pydantic models; `Decimal` money |
| [`src/ledger_agent/tools.py`](src/ledger_agent/tools.py) | Three tools: schema + deterministic handler |
| [`src/ledger_agent/agent.py`](src/ledger_agent/agent.py) | The tool-calling loop |
| [`src/ledger_agent/mcp_server.py`](src/ledger_agent/mcp_server.py) | The same tools over MCP |
| [`eval/metrics.py`](eval/metrics.py) | Confusion matrices, macro F1, end-to-end rates |
| [`eval/harness.py`](eval/harness.py) | Score one configuration |
| [`eval/experiment.py`](eval/experiment.py) | Run the matrix, emit the comparison |

Deliberately absent: web UI, database, auth, Docker, RAG. A small repo that does one
thing completely is easier to trust than a half-built product.

---

## Honest limitations

- Twenty cases is enough to see a large effect and not enough to resolve a small one.
  Differences of a few percentage points in the table below are noise.
- The invoices are synthetic and clean. Real invoice text arrives as OCR output from a
  scanned PDF, with broken columns and misread digits — extraction difficulty this
  dataset does not model at all.
- One chart of accounts, one currency, one entry shape (unpaid vendor invoice). No
  multi-currency, no partial payments, no credit notes, no accruals.
- Labels are my own judgment on cases where a real accountant might reasonably book it
  differently — the prepaid-versus-expense boundary especially.

---

MIT licensed. Built by [Luis Evangelista](https://github.com/luiselv).
