# Model Cost Estimate

Generated: 2026-07-05
Updated: 2026-07-12 — refreshed with real measured Gemini usage from the first fully successful automated run (18/18 news items, 6 courses, 5 movies).

## Scope

This document estimates only the editorial model cost for the AI newsletter pipeline (news selection, news rewrite, courses/movies selection, semantic-memory embeddings). It does not include Exa, SearXNG hosting, TMDb, server hosting, database, or manual labor.

## Current Configuration

- `AI_UPDATES_MODEL_PROVIDER=gemini` — Gemini is the active provider.
- `GEMINI_SELECTION_MODEL=gemini-flash-lite-latest` — news/course/movie candidate selection (mechanical filtering, highest call volume).
- `GEMINI_REWRITE_MODEL=gemini-flash-latest` — Arabic rewrite (the one stage most sensitive to language quality, so it gets the stronger of the two Flash tiers).
- `GEMINI_EMBEDDING_MODEL=gemini-embedding-001` — semantic-memory deduplication.
- `gemini-pro-latest` requires Cloud Billing to be enabled on this project. See the note at the end of this document if billing gets enabled later.

## Measured Gemini Usage (real run, not estimated)

Source: `backend/logs/ai_updates_run.jsonl`, `run_id: full-20260712T013103Z-0f3762d5`, 2026-07-12. This is the first run after the Exa content-fix (see `UPDATES.md` §16) to complete fully automated end-to-end and hit the 18-item target with 6 courses and 5 movies saved.

| Stage | Model | Calls | Input tokens | Output tokens |
| --- | --- | ---: | ---: | ---: |
| News selection (primary + 3 top-up rounds) | `gemini-flash-lite-latest` | 6 | 80,675 | 15,650 |
| News rewrite (primary + 3 top-up rounds) | `gemini-flash-latest` | 6 | 25,744 | 5,700 |
| **News subtotal (measured)** | | **12** | **106,419** | **21,350** |

Courses and movies also called Gemini in this run (`courses_gpt_seconds: 73.6`, `movies_gpt_seconds: 19.22`, both via `supporting_prompt_gpt`) but are not yet emitting the same per-call token log as news selection — a logging gap, not a cost-free operation. Their share is estimated below by scaling the measured news cost by the share of total model time they took (92.8s of 349.3s total model time this run, ≈27%):

| Component | Basis | Estimated cost |
| --- | --- | ---: |
| News (selection + rewrite) | Measured directly | $0.1336 |
| Courses + movies selection | Estimated from time-share (not token-logged yet) | ≈$0.0480 |
| Embeddings (semantic memory) | Measured separately (see below) | ≈$0.0002 |
| **Total, this run** | | **≈$0.182** |

Embedding usage: 18 items × ~85 tokens average ≈ 1,530 input tokens at $0.15/1M ≈ $0.0002/run.

**Caveat:** this run needed 3 top-up rounds to reach 18/18 — more top-ups than a run that hits the target on the first pass. Cost per run will vary; treat $0.182 as a realistic upper-typical figure, not a fixed number. A lighter run (fewer top-ups) measured earlier this session came in around $0.09.

## Gemini Pricing (sourced from ai.google.dev/gemini-api/docs/pricing, checked 2026-07-12)

| Model | Input $/1M tokens | Output $/1M tokens |
| --- | ---: | ---: |
| `gemini-flash-latest` (Gemini 3.5 Flash) | $1.50 | $9.00 |
| `gemini-flash-lite-latest` (Gemini 3.1 Flash-Lite) | $0.25 | $1.50 |
| `gemini-pro-latest` (Gemini 3.1 Pro Preview, ≤200k context) — requires Cloud Billing | $2.00 | $12.00 |
| `gemini-embedding-001` | $0.15 | — |

## Run Volume Assumptions (testing + reserve margin)

| Scenario | Runs/year | Runs/month |
| --- | ---: | ---: |
| Production only: 1 generation/week | 52 | 4.33 |
| Production + weekly test run | 104 | 8.67 |
| Recommended budget: production + tests + 30% contingency | 135 | 11.25 |
| High safety: production + tests + 50% contingency | 156 | 13.00 |

## Estimated Cost — Monthly and Annual

Using the measured/estimated $0.182 per full run (Gemini, current model split):

| Scenario | Monthly | Annual |
| --- | ---: | ---: |
| Production only | $0.79 | $9.46 |
| Production + tests | $1.58 | $18.93 |
| **Recommended budget (+30% contingency)** | **$2.05** | **$24.61** |
| High safety (+50% contingency) | $2.37 | $28.39 |

## Recommended Budget

| Option | Recommended budget |
| --- | ---: |
| Gemini Flash (current setup) | ~$25/year (~$2.10/month) |
| Gemini Flash, conservative (with margin for growth in candidate volume) | ~$35/year (~$3/month) |

### Future: Upgrading to Gemini Pro

If Cloud Billing is enabled later and `gemini-pro-latest` replaces `gemini-flash-latest` for the rewrite stage, expect roughly +$0.02–0.03/run based on the token volumes measured above. This would increase the annual budget to approximately **$28–33/year**, still well under $40/year.

## Important Caveats

- Courses/movies cost above is an estimate extrapolated from model call duration, not directly token-logged. If `backend/pipeline/enrichment/supporting.py`'s model call path adds the same `model.token_usage` event news selection already emits, replace this estimate with a measured figure.
- Cost per run varies with how many top-up rounds are needed to reach the 18-item target; the figure here reflects a real run that needed 3 top-ups, so it leans toward the higher end of normal.
- If the shortlist size or top-up ceiling changes, re-measure rather than reusing this document's numbers as-is.
- Embedding cost is negligible at current volume and was not a material factor in this estimate.