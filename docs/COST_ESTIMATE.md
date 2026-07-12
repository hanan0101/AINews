# Model Cost Estimate

Generated: 2026-07-05

## Scope

This document estimates only the editorial model cost for the AI newsletter pipeline.
It does not include Exa, SearXNG hosting, TMDb, server hosting, database, or manual labor.

## Local Usage Evidence

Source files:

- `data/news/model_usage_summary.json`
- `data/news/ai_updates_run_report.json`
- `backend/config/settings.py`
- `backend/pipeline/modeling/model_client.py`

Current logged OpenAI model:

- `gpt-5.2`

Current configured provider behavior:

- `AI_UPDATES_MODEL_PROVIDER` defaults to `gemini`.
- When provider is OpenAI, `OPENAI_MODEL` defaults to `gpt-5.2`.
- When provider is Gemini, the configured model defaults to `gemini-2.5-flash`.

## Measured OpenAI Usage

The estimate uses the 6 OpenAI full-ish runs in `data/news/model_usage_summary.json` with 3+ successful model calls.
This avoids counting tiny one-card/manual replacement runs as a full newsletter run.

| Metric | Average per full-ish run |
| --- | ---: |
| Model calls | 13.17 |
| Input tokens | 73,293 |
| Output tokens | 25,813 |
| Total tokens | 99,106 |
| Estimated input tokens | 76,917 |

Notes:

- Some runs used top-up calls, which increases cost.
- Gemini calls in the current app often log actual tokens as `0`; therefore Gemini is estimated using the same token shape as OpenAI.

## Pricing Assumptions

Official pricing pages checked:

- OpenAI API pricing: https://openai.com/api/pricing/
- Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing

OpenAI note:

- The local logs show `gpt-5.2`.
- The current public pricing page may list newer/current OpenAI model names instead of `gpt-5.2`.
- For budgeting, this document uses a comparable current OpenAI standard model rate and also shows an upper-bound OpenAI rate.

| Provider / model assumption | Input per 1M tokens | Output per 1M tokens |
| --- | ---: | ---: |
| OpenAI comparable current standard model | $1.25 | $7.50 |
| OpenAI upper-bound standard model | $2.50 | $15.00 |
| Gemini 2.5 Flash standard | $0.30 | $2.50 |
| Gemini 2.5 Flash batch/flex | $0.15 | $1.25 |
| Gemini 2.5 Flash-Lite standard | $0.10 | $0.40 |

## Run Volume Assumptions

| Scenario | Run equivalents per year |
| --- | ---: |
| Production only: 4 generations per week | 208 |
| Production + tests: 4 generations + 1 test per week | 260 |
| Recommended budget: production + tests + 30% contingency | 338 |
| High safety: production + tests + 50% contingency | 390 |

## Estimated Cost Per Run

| Provider / model assumption | Estimated cost per full run |
| --- | ---: |
| OpenAI comparable current standard model | $0.285 |
| OpenAI upper-bound standard model | $0.570 |
| Gemini 2.5 Flash standard | $0.087 |
| Gemini 2.5 Flash batch/flex | $0.043 |
| Gemini 2.5 Flash-Lite standard | $0.018 |

## Annual Cost Estimate

| Provider / model assumption | Production only | Production + tests | Recommended budget | High safety |
| --- | ---: | ---: | ---: | ---: |
| OpenAI comparable current standard model | $59.32/year | $74.15/year | $96.40/year | $111.23/year |
| OpenAI upper-bound standard model | $118.65/year | $148.31/year | $192.80/year | $222.46/year |
| Gemini 2.5 Flash standard | $18.00/year | $22.50/year | $29.24/year | $33.74/year |
| Gemini 2.5 Flash batch/flex | $9.00/year | $11.25/year | $14.62/year | $16.87/year |
| Gemini 2.5 Flash-Lite standard | $3.67/year | $4.59/year | $5.97/year | $6.89/year |

## Recommended Budget

For the current pipeline shape, use this annual budget:

| Option | Recommended annual budget |
| --- | ---: |
| OpenAI normal budget | About $100/year |
| OpenAI conservative budget | About $200/year |
| Gemini 2.5 Flash normal budget | About $30/year |
| Gemini 2.5 Flash conservative budget | About $35/year |

## Important Caveats

- The estimate assumes the current prompt size and top-up behavior stay similar.
- If the pipeline repeatedly fails selection and retries many times, cost can rise.
- If the shortlist is reduced or top-up calls are reduced, cost drops.
- If Gemini actual token accounting becomes available in logs, replace the estimated Gemini calculation with actual usage.
- Embedding costs are not included here because this document focuses on the editorial generation model. If semantic memory with OpenAI embeddings is enabled heavily, add a separate embedding budget.

