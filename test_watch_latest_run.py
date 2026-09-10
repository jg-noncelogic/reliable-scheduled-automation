import io
import json
import unittest
from datetime import datetime, timezone

from watch_latest_run import assess_latest_run, cli, fetch_runs, workflow_runs_url


NOW = datetime(2026, 9, 10, 13, 0, tzinfo=timezone.utc)


class LatestRunAssessmentTest(unittest.TestCase):
    def test_cli_assesses_requested_workflow(self):
        seen = {}

        def fetcher(repo, workflow):
            seen.update(repo=repo, workflow=workflow)
            return [{
                "created_at": "2026-09-10T12:30:00Z",
                "status": "completed",
                "conclusion": "success",
            }]

        result = cli(
            ["--repo", "acme/example", "--workflow", "daily.yml", "--max-age-hours", "26"],
            fetcher=fetcher,
            current_time=NOW,
        )
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(seen, {"repo": "acme/example", "workflow": "daily.yml"})

    def test_workflow_url_filters_to_scheduled_runs(self):
        self.assertEqual(
            workflow_runs_url("acme/example", "daily.yml"),
            "https://api.github.com/repos/acme/example/actions/workflows/daily.yml/runs?event=schedule&per_page=1",
        )

    def test_fetch_returns_workflow_runs(self):
        seen = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        def opener(request, timeout):
            seen["request"] = request
            seen["timeout"] = timeout
            return Response(json.dumps({"workflow_runs": [{"id": 7}]}).encode())

        runs = fetch_runs("acme/example", "daily.yml", opener=opener)
        self.assertEqual(runs, [{"id": 7}])
        self.assertEqual(seen["timeout"], 15)
        self.assertIsNone(seen["request"].get_header("Authorization"))

    def test_invalid_repository_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "OWNER/REPO"):
            workflow_runs_url("acme/example#fragment", "daily.yml")

    def test_malformed_api_response_is_rejected(self):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        def opener(request, timeout):
            return Response(b'{"message":"not workflow runs"}')

        with self.assertRaisesRegex(ValueError, "workflow_runs"):
            fetch_runs("acme/example", "daily.yml", opener=opener)

    def test_recent_success_is_healthy(self):
        runs = [{
            "html_url": "https://github.com/acme/example/actions/runs/1",
            "created_at": "2026-09-10T12:30:00Z",
            "status": "completed",
            "conclusion": "success",
            "repository": {"name": "large-payload"},
        }]
        result = assess_latest_run(runs, NOW, max_age_hours=26)
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["age_hours"], 0.5)
        self.assertEqual(result["latest_run"], {
            "html_url": "https://github.com/acme/example/actions/runs/1",
            "created_at": "2026-09-10T12:30:00Z",
            "status": "completed",
            "conclusion": "success",
        })

    def test_recent_failed_run_is_unhealthy(self):
        runs = [{
            "html_url": "https://github.com/acme/example/actions/runs/2",
            "created_at": "2026-09-10T12:30:00Z",
            "status": "completed",
            "conclusion": "failure",
        }]
        result = assess_latest_run(runs, NOW, max_age_hours=26)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 2)

    def test_recent_running_run_is_in_progress(self):
        runs = [{
            "html_url": "https://github.com/acme/example/actions/runs/3",
            "created_at": "2026-09-10T12:30:00Z",
            "status": "in_progress",
            "conclusion": None,
        }]
        result = assess_latest_run(runs, NOW, max_age_hours=26)
        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(result["exit_code"], 0)

    def test_unknown_run_status_is_observer_error(self):
        runs = [{"created_at": "2026-09-10T12:30:00Z", "status": "new_state", "conclusion": None}]
        with self.assertRaisesRegex(ValueError, "unknown workflow status"):
            assess_latest_run(runs, NOW, max_age_hours=26)

    def test_non_finite_threshold_is_rejected(self):
        runs = [{"created_at": "2026-09-10T12:30:00Z", "status": "completed", "conclusion": "success"}]
        with self.assertRaisesRegex(ValueError, "finite"):
            assess_latest_run(runs, NOW, max_age_hours=float("nan"))

    def test_future_timestamp_is_rejected(self):
        runs = [{"created_at": "2026-09-10T13:06:00Z", "status": "completed", "conclusion": "success"}]
        with self.assertRaisesRegex(ValueError, "future"):
            assess_latest_run(runs, NOW, max_age_hours=26)

    def test_age_comparison_does_not_use_rounded_value(self):
        runs = [{"created_at": "2026-09-09T10:59:46Z", "status": "completed", "conclusion": "success"}]
        result = assess_latest_run(runs, NOW, max_age_hours=26)
        self.assertEqual(result["status"], "overdue")

    def test_old_success_is_overdue(self):
        runs = [{
            "html_url": "https://github.com/acme/example/actions/runs/1",
            "created_at": "2026-09-09T06:00:00Z",
            "status": "completed",
            "conclusion": "success",
        }]
        result = assess_latest_run(runs, NOW, max_age_hours=26)
        self.assertEqual(result["status"], "overdue")
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["age_hours"], 31.0)

    def test_no_runs_is_missing(self):
        result = assess_latest_run([], NOW, max_age_hours=26)
        self.assertEqual(result, {
            "status": "missing",
            "exit_code": 2,
            "reason": "no_workflow_runs_found",
        })


if __name__ == "__main__":
    unittest.main()
