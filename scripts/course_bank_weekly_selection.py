from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config.settings import SUPPORTING_COURSE_FETCH_POOL  # noqa: E402
from backend.pipeline.fetching.courses import fetch_course_candidates  # noqa: E402
from backend.pipeline.fetching.course_bank import (  # noqa: E402
    COURSE_WEEKLY_TARGET_COUNT,
    active_bank_courses,
    select_weekly_courses,
    upsert_course_bank,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update Course Bank and select the weekly 6-course rotation.")
    parser.add_argument("--discover", action="store_true", help="Run discovery before weekly selection.")
    parser.add_argument("--max-results", type=int, default=SUPPORTING_COURSE_FETCH_POOL, help="Discovery candidate count.")
    parser.add_argument("--issue-id", default="", help="Optional issue id. Defaults to ISO week.")
    parser.add_argument("--issue-date", default="", help="Optional issue date YYYY-MM-DD. Defaults to today.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.discover:
        candidates = fetch_course_candidates(max_results=max(args.max_results, COURSE_WEEKLY_TARGET_COUNT * 4))
        stats = upsert_course_bank(candidates)
        print(f"Discovery upsert: {json.dumps(stats, ensure_ascii=False)}")
    issue_date = None
    if args.issue_date:
        issue_date = datetime.fromisoformat(args.issue_date)
    selected, report = select_weekly_courses(
        target_count=COURSE_WEEKLY_TARGET_COUNT,
        issue_id=args.issue_id,
        issue_date=issue_date,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\nSelected courses:")
    for item in selected:
        print(f"- {item.get('level')} | {item.get('platform')} | {item.get('title')} | {item.get('url')}")
    print(f"\nActive bank courses: {len(active_bank_courses())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
