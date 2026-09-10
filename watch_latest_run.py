#!/usr/bin/env python3
"""Check whether a GitHub Actions workflow has a recent successful run."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen


def workflow_runs_url(repo: str, workflow: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("repo must be exactly OWNER/REPO")
    owner, name = repo.split("/", 1)
    return (
        f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(name, safe='')}/actions/workflows/"
        f"{quote(workflow, safe='')}/runs?event=schedule&per_page=1"
    )


def fetch_runs(repo: str, workflow: str, opener=urlopen) -> list[dict]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "scheduled-automation-watchdog",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    request = Request(workflow_runs_url(repo, workflow), headers=headers)
    with opener(request, timeout=15) as response:
        payload = json.load(response)
    if not isinstance(payload.get("workflow_runs"), list):
        raise ValueError("GitHub response has no workflow_runs list")
    return payload["workflow_runs"]


def parse_github_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assess_latest_run(runs: list[dict], now: datetime, max_age_hours: float) -> dict:
    if not math.isfinite(max_age_hours) or max_age_hours < 0:
        raise ValueError("max_age_hours must be finite and non-negative")
    if not runs:
        return {
            "status": "missing",
            "exit_code": 2,
            "reason": "no_workflow_runs_found",
        }
    latest = runs[0]
    age_seconds = (now - parse_github_time(latest["created_at"])).total_seconds()
    if age_seconds < -300:
        raise ValueError("latest run timestamp is materially in the future")
    age_hours_exact = max(0.0, age_seconds / 3600)
    age_hours = round(age_hours_exact, 2)
    known_statuses = {"completed", "in_progress", "queued", "requested", "waiting", "pending"}
    if latest.get("status") not in known_statuses:
        raise ValueError(f"unknown workflow status: {latest.get('status')!r}")
    if age_hours_exact > max_age_hours:
        status = "overdue"
    elif latest.get("status") == "completed" and latest.get("conclusion") != "success":
        status = "failed"
    elif latest.get("status") != "completed":
        status = latest.get("status", "unknown")
    else:
        status = "healthy"
    summary = {
        key: latest[key]
        for key in ("html_url", "created_at", "status", "conclusion")
        if key in latest
    }
    return {
        "status": status,
        "exit_code": 0 if status in {"healthy", "in_progress", "queued", "requested", "waiting", "pending"} else 2,
        "age_hours": age_hours,
        "latest_run": summary,
    }


class RaisingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def cli(argv: list[str], fetcher=fetch_runs, current_time: datetime | None = None) -> dict:
    parser = RaisingArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    parser.add_argument("--workflow", required=True, help="Workflow file name, for example daily.yml")
    parser.add_argument("--max-age-hours", required=True, type=float)
    args = parser.parse_args(argv)
    runs = fetcher(args.repo, args.workflow)
    return assess_latest_run(
        runs,
        current_time or datetime.now(timezone.utc),
        args.max_age_hours,
    )


def main() -> int:
    try:
        result = cli(sys.argv[1:])
    except Exception as exc:
        result = {"status": "error", "exit_code": 1, "error": str(exc)}
    print(json.dumps(result, separators=(",", ":")))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
