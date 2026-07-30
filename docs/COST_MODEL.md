# Gemini Cost Model

The reviewed workbook is:

`outputs/codex_cost_audit_20260730/Gemini_Cost_Calculator_v5_11_final.xlsx`

It models Gemini API usage only. It does not include Exa, SearXNG hosting,
Docker/servers, databases, storage, networking, or developer labor.

## Current workbook totals

| Metric | Value |
| --- | ---: |
| Weekly recurring cost, including 20% buffer | $2.85 |
| Monthly recurring cost, including buffer | $12.36 |
| Annual recurring cost, including buffer | $148.34 |
| First-year budget with 10 verification tests | $166.24 |

The workbook contains 24 formulas and no spreadsheet formula errors. The
review did not alter numeric inputs or formulas.

## Important interpretation

The weekly call counts are a conservative planning scenario. They assume one
normal full generation plus one single-item recovery and one full rerun every
week. The code confirms that these paths exist, but code alone cannot prove
how often editors use them. Therefore the totals may be higher than steady
operation, but there is not enough current runtime evidence to replace them
with lower figures.

The prompts changed on 2026-07-30 and the current runtime usage log is not
available in the working tree. After the next successful full generation,
record actual calls and tokens for selection, rewriting, and embeddings before
changing any workbook assumption. Do not infer replacement token averages from
prompt length or source code.

Newsletter scheduling is not part of this cost model or the current product.
The “weekly” unit is a budgeting period only.
