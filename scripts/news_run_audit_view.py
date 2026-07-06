"""Build a readable audit report for the latest AI-news generation run."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEWS_DIR = ROOT / "data" / "news"
DEFAULT_OUTPUT = NEWS_DIR / "news_run_audit_view.md"


def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def one_line(value: str = "", limit: int = 180) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def domain_from_url(url: str = "") -> str:
    try:
        from urllib.parse import urlparse

        return urlparse(str(url or "")).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def sample_items(row: dict) -> list[dict]:
    for key in ("accepted_samples", "results", "sample", "items"):
        values = row.get(key)
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict)]
    return []


def write_query_section(lines: list[str], title: str, rows: list[dict]) -> None:
    lines.append(f"## {title}")
    lines.append("")
    raw_total = sum(int(row.get("raw_count") or 0) for row in rows)
    accepted_total = sum(int(row.get("accepted_count") or 0) for row in rows)
    rejected_total = sum(int(row.get("rejected_count") or 0) for row in rows)
    nonzero = [row for row in rows if int(row.get("raw_count") or 0) > 0 or int(row.get("accepted_count") or 0) > 0]
    lines.append(f"- queries: {len(rows)}")
    lines.append(f"- raw: {raw_total}")
    lines.append(f"- accepted: {accepted_total}")
    lines.append(f"- rejected: {rejected_total}")
    lines.append(f"- nonzero queries: {len(nonzero)}")
    lines.append("")
    for index, row in enumerate(rows, 1):
        raw = int(row.get("raw_count") or 0)
        accepted = int(row.get("accepted_count") or 0)
        rejected = int(row.get("rejected_count") or 0)
        if raw == 0 and accepted == 0 and rejected == 0:
            continue
        lines.append(f"### {index}. raw={raw} accepted={accepted} rejected={rejected}")
        lines.append("")
        lines.append(f"`{one_line(row.get('query') or '', 500)}`")
        executed = row.get("executed_query")
        if executed and executed != row.get("query"):
            lines.append("")
            lines.append(f"executed: `{one_line(executed, 500)}`")
        error = row.get("error")
        if error:
            lines.append("")
            lines.append(f"error: `{one_line(error, 500)}`")
        samples = sample_items(row)
        if samples:
            lines.append("")
            for item in samples[:8]:
                title_text = one_line(item.get("title") or "")
                url = item.get("url") or ""
                reason = item.get("reason") or item.get("reject_reason") or ""
                suffix = f" | reason={one_line(reason, 120)}" if reason else ""
                lines.append(f"- {title_text} | {domain_from_url(url)} | {url}{suffix}")
        lines.append("")


def build_report() -> str:
    run_report = load_json(NEWS_DIR / "ai_updates_run_report.json", {})
    query_report = load_json(NEWS_DIR / "ai_updates_query_results.json", {})
    candidate_audit = load_json(NEWS_DIR / "ai_updates_candidate_audit.json", {})
    news_json = load_json(NEWS_DIR / "news.json", {})

    lines: list[str] = []
    lines.append("# News Run Audit View")
    lines.append("")
    lines.append("## Files")
    lines.append("")
    lines.append(f"- run report: `data/news/ai_updates_run_report.json`")
    lines.append(f"- query results: `data/news/ai_updates_query_results.json`")
    lines.append(f"- candidate audit: `data/news/ai_updates_candidate_audit.json`")
    lines.append(f"- saved newsletter: `data/news/news.json`")
    lines.append("")

    performance = run_report.get("performance") if isinstance(run_report.get("performance"), dict) else {}
    lines.append("## Run Summary")
    lines.append("")
    for key in (
        "total_seconds",
        "raw_candidates",
        "valid_candidates",
        "selected_count",
        "saved_count",
        "queries",
        "exa_queries",
        "searxng_queries",
        "exa_raw",
        "searxng_raw",
        "gpt_shortlist_count",
    ):
        if key in performance:
            lines.append(f"- {key}: {performance.get(key)}")
    lines.append(f"- query report raw_results: {query_report.get('raw_results')}")
    lines.append(f"- query report unique_results: {query_report.get('unique_results')}")
    lines.append(f"- candidates sent to model: {candidate_audit.get('total_candidates_sent_to_model')}")
    lines.append(f"- selected in audit: {candidate_audit.get('selected_count')}")
    lines.append("")

    selected_news = run_report.get("latest_updates") or []
    lines.append("## Final Selected News")
    lines.append("")
    for index, item in enumerate(selected_news, 1):
        title = one_line(item.get("title") or "")
        url = item.get("official_url") or item.get("url") or ""
        level = item.get("level") or item.get("impact_level") or ""
        lines.append(f"{index}. **{title}**")
        lines.append(f"   - level: `{level}`")
        lines.append(f"   - url: {url}")
    lines.append("")

    candidates = candidate_audit.get("candidates") or []
    status_counts = Counter(str(item.get("status") or "unknown") for item in candidates if isinstance(item, dict))
    domain_counts = Counter(domain_from_url(item.get("url") or "") for item in candidates if isinstance(item, dict))
    lines.append("## Candidates Sent To Model")
    lines.append("")
    lines.append(f"- total: {len(candidates)}")
    lines.append(f"- status counts: {dict(status_counts)}")
    lines.append(f"- top domains: {dict(domain_counts.most_common(20))}")
    lines.append("")
    for index, item in enumerate(candidates, 1):
        if not isinstance(item, dict):
            continue
        mark = "SELECTED" if str(item.get("status") or "").lower() == "selected" else "rejected"
        lines.append(
            f"{index}. [{mark}] {one_line(item.get('title') or '')} | "
            f"{domain_from_url(item.get('url') or '')} | {item.get('url') or ''}"
        )
        reason = item.get("reason")
        if reason:
            lines.append(f"   - reason: {one_line(reason, 200)}")
        query = item.get("query")
        if query:
            lines.append(f"   - query: `{one_line(query, 300)}`")
    lines.append("")

    query_rows = [row for row in (query_report.get("queries") or []) if isinstance(row, dict)]
    by_source = {}
    for row in query_rows:
        by_source.setdefault(str(row.get("source") or "unknown"), []).append(row)
    write_query_section(lines, "Exa Queries", by_source.get("exa", []))
    write_query_section(lines, "SearXNG Queries", by_source.get("searxng", []))

    other_sources = sorted(set(by_source) - {"exa", "searxng"})
    for source in other_sources:
        write_query_section(lines, f"{source} Queries", by_source.get(source, []))

    courses = news_json.get("courses") or []
    lines.append("## Saved Courses Snapshot")
    lines.append("")
    for index, item in enumerate(courses, 1):
        lines.append(
            f"{index}. {one_line(item.get('title') or '')} | "
            f"level={item.get('level') or ''} | platform={item.get('platform') or item.get('source') or ''} | "
            f"{item.get('url') or ''}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a readable audit report for the latest news run.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output markdown path.")
    args = parser.parse_args()

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(), encoding="utf-8")
    print(str(output))


if __name__ == "__main__":
    main()
