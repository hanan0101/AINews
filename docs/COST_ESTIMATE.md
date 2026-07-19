# Model Cost Estimate

This document covers editorial-model and embedding usage only. It excludes
hosting, Exa, TMDb, database, storage, and staff costs.

## Active Model Roles

| Stage | Default model |
| --- | --- |
| News selection | `gemini-flash-lite-latest` |
| News rewrite | `gemini-flash-latest` |
| Course and movie selection | `gemini-flash-latest` |
| Semantic embeddings | `gemini-embedding-001` |

Environment variables can override these defaults. See
[ENVIRONMENT_GUIDE.md](../backend/config/ENVIRONMENT_GUIDE.md).

## Measured Reference Run

Reference: `full-20260712T013103Z-0f3762d5` from
`backend/logs/ai_updates_run.jsonl`.

| Stage | Calls | Input tokens | Output tokens |
| --- | ---: | ---: | ---: |
| News selection | 6 | 80,675 | 15,650 |
| News rewrite | 6 | 25,744 | 5,700 |
| Course selection | 1 | 6,304 | 2,633 |
| Movie selection | 1 | 1,229 | 734 |

The reference run cost was approximately **$0.175** using the pricing snapshot
recorded on 2026-07-13. Embedding usage was estimated at approximately 1,530
input tokens and contributed less than one cent.

## Budget Reference

| Scenario | Runs per year | Estimated annual cost |
| --- | ---: | ---: |
| Weekly production run | 52 | $9.12 |
| Weekly production and test runs | 104 | $18.24 |
| Production, tests, and 30% reserve | 135 | $23.68 |

A practical budget for the measured configuration is approximately **$24 per
year**, or **$2 per month**.

## Calculation

For each model stage:

```text
(input tokens / 1,000,000 * input price)
+ (output tokens / 1,000,000 * output price)
```

Sum the stages, multiply by the expected number of runs, and add a reserve for
tests and retries.

## Limitations

- Model pricing and alias resolution can change. Verify Google's current
  pricing before approving a budget.
- Cost varies with candidate volume and the number of top-up rounds.
- Recalculate after changing model assignments, shortlist size, or output
  limits.
- `data/news/runtime/model_usage_summary.json` is the operational usage record;
  this document is only a planning reference.
