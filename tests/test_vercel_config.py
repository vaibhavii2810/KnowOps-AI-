"""
tests/test_vercel_config.py  –  Phase 14 (D-054)
Guards vercel.json's reindex schedule: migrated from the Cron Jobs `crons` array to the Schedules
`schedules` object (Vercel docs: https://vercel.com/docs/schedules/migrate-from-cron-jobs, 2026-11-08).
Pure config checks, no network — this would not catch Vercel rejecting the file, only a local regression
(e.g. someone reverting to `crons`, dropping `requestMethod`, or changing the path/schedule by accident).
"""

import json
from pathlib import Path

CONFIG = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text())


def test_the_reindex_schedule_exists_with_the_right_path_and_cron_expression():
    assert "reindex" in CONFIG.get("schedules", {}), "schedules.reindex is missing"
    reindex = CONFIG["schedules"]["reindex"]
    assert reindex["path"] == "/cron/reindex"
    assert reindex["schedule"] == "0 3 * * *"  # daily at 03:00 UTC (Phase 9.3)


def test_the_reindex_schedule_requests_get_because_the_route_only_accepts_get():
    # Schedules default to POST; /cron/reindex is a plain @app.get(...) (app/main.py), so this must be
    # explicit or Vercel's schedule invocation won't match the route.
    assert CONFIG["schedules"]["reindex"]["requestMethod"] == "GET"


def test_the_old_crons_array_is_gone_so_the_route_cannot_run_twice():
    # Vercel's migration docs: keeping both `crons` and `schedules` for the same path runs it twice
    # per occurrence.
    assert "crons" not in CONFIG


def test_the_schema_reference_and_rewrite_are_unaffected_by_the_migration():
    assert CONFIG["$schema"] == "https://openapi.vercel.sh/vercel.json"
    assert CONFIG["rewrites"] == [{"source": "/(.*)", "destination": "/api/index"}]
