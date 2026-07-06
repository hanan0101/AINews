from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

# This diagnostic should not spend embedding/model quota unless explicitly enabled.
os.environ.setdefault("AI_UPDATES_SEMANTIC_MEMORY_ENABLED", "0")

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config.settings import safe_write_json, utc_now  # noqa: E402
from backend.pipeline.fetching.courses import fetch_course_candidates  # noqa: E402
from backend.pipeline.filtering.courses import filter_supporting_candidates, supporting_reject_reason  # noqa: E402
from backend.pipeline.news.fetching import fetch_news_candidates  # noqa: E402
from backend.pipeline.news.filtering import filter_news_candidates  # noqa: E402

OUTPUT_DIR = PROJECT_DIR / "data" / "news"


def compact_item(item: dict) -> dict:
    return {
        "title": item.get("title") or "",
        "url": item.get("url") or item.get("source_url") or "",
        "source": item.get("source") or item.get("provider") or item.get("platform") or "",
        "published": item.get("published") or item.get("published_date") or item.get("date") or "",
        "fetch_source": item.get("fetch_source") or item.get("discovery_source") or "",
        "level": item.get("level") or item.get("news_level") or "",
        "company": item.get("company") or "",
        "tool_name": item.get("tool_name") or "",
        "text_preview": str(item.get("text") or item.get("summary") or item.get("content") or "")[:500],
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["title", "url", "source", "published", "fetch_source", "level", "company", "tool_name", "text_preview"]
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def save_section(prefix: str, raw: list[dict], filtered: list[dict], diagnostics: dict | None = None) -> dict:
    raw_compact = [compact_item(item) for item in raw or []]
    filtered_compact = [compact_item(item) for item in filtered or []]
    safe_write_json(OUTPUT_DIR / f"debug_{prefix}_raw.json", {"count": len(raw or []), "items": raw})
    safe_write_json(OUTPUT_DIR / f"debug_{prefix}_filtered.json", {"count": len(filtered or []), "items": filtered})
    write_csv(OUTPUT_DIR / f"debug_{prefix}_raw.csv", raw_compact)
    write_csv(OUTPUT_DIR / f"debug_{prefix}_filtered.csv", filtered_compact)
    return {
        "raw_count": len(raw or []),
        "filtered_count": len(filtered or []),
        "raw_sample": raw_compact[:8],
        "filtered_sample": filtered_compact[:8],
        "diagnostics": diagnostics or {},
    }


def course_preview_diagnostics(raw: list[dict], filtered: list[dict]) -> dict:
    rejected = Counter()
    for item in raw or []:
        reason = supporting_reject_reason(item, "course")
        if reason:
            rejected[reason] += 1
    return {
        "raw_course_count": len(raw or []),
        "filtered_course_count": len(filtered or []),
        "top_rejection_reasons": dict(rejected.most_common(8)),
        "final_selected_course_count": len(filtered or []),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and filter preview for news/courses without generating the newsletter.")
    parser.add_argument("--section", choices=["all", "news", "courses"], default="all")
    parser.add_argument("--news-target", default="", help="Optional news target hint/sector.")
    parser.add_argument("--course-results", type=int, default=24)
    parser.add_argument("--course-limit", type=int, default=12)
    parser.add_argument("--single-news", action="store_true", help="Use single-card news fetch/filter mode.")
    parser.add_argument("--enable-semantic", action="store_true", help="Allow semantic memory checks. May spend embedding quota.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.enable_semantic:
        os.environ["AI_UPDATES_SEMANTIC_MEMORY_ENABLED"] = "1"

    report = {
        "generated_at": utc_now().isoformat(),
        "semantic_memory_enabled_for_preview": bool(args.enable_semantic),
        "outputs": {},
    }

    if args.section in {"all", "news"}:
        news_raw, news_diagnostics = fetch_news_candidates(target_hint=args.news_target, single=args.single_news)
        news_filtered = filter_news_candidates(news_raw, news_diagnostics, single=args.single_news)
        report["outputs"]["news"] = save_section("news", news_raw, news_filtered, news_diagnostics)

    if args.section in {"all", "courses"}:
        course_raw = fetch_course_candidates(max_results=max(1, args.course_results))
        course_filtered = filter_supporting_candidates(course_raw, "course", max(1, args.course_limit))
        report["outputs"]["courses"] = save_section(
            "courses",
            course_raw,
            course_filtered,
            course_preview_diagnostics(course_raw, course_filtered),
        )

    safe_write_json(OUTPUT_DIR / "debug_fetch_filter_preview_report.json", report)
    print(json.dumps({
        "report": str(OUTPUT_DIR / "debug_fetch_filter_preview_report.json"),
        "sections": {
            key: {
                "raw": value.get("raw_count"),
                "filtered": value.get("filtered_count"),
            }
            for key, value in report["outputs"].items()
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
