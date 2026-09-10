"""Exercise the published workflow's recovery contract with local Git runners."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / "examples/daily.yml"


def command(cwd, *args, check=True):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_NAME": "Recovery Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Recovery Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=check)


class WorkflowRecoveryTest(unittest.TestCase):
    def test_persist_step_runs_after_job_failure(self):
        text = WORKFLOW.read_text()
        match = re.search(r"      - name: Persist[^\n]*\n(.*?)(?=      - |\Z)", text, re.S)
        self.assertIsNotNone(match, "Published workflow needs a persistence step")
        condition = re.search(r"^        if:\s*(.+)$", match.group(1), re.M)
        self.assertIsNotNone(condition, "Without an explicit status condition, a failed job skips persistence")
        self.assertIn("always()", condition.group(1), "Failure recovery state must survive a failed run step")

    def test_fresh_runner_loads_previous_failed_attempt_receipt(self):
        text = WORKFLOW.read_text()
        checkout = re.search(r"      - uses: actions/checkout@[^\n]+\n(.*?)(?=      - |\Z)", text, re.S)
        self.assertIsNotNone(checkout)
        ref = re.search(r"^          ref:\s*(.+)$", checkout.group(1), re.M)
        # checkout's default is the immutable triggering event SHA, even when a
        # queued preceding run has since committed recovery state to the branch.
        branch_checkout = (
            ref is not None
            and any(symbol in ref.group(1) for symbol in (
                "github.ref", "github.event.repository.default_branch",
            ))
            and "github.sha" not in ref.group(1)
        )
        with tempfile.TemporaryDirectory(prefix="workflow-recovery-") as tmp:
            base = Path(tmp)
            origin = base / "origin.git"
            first = base / "first"
            fresh = base / "fresh"
            command(base, "git", "init", "--bare", "--initial-branch=main", str(origin))
            command(base, "git", "clone", str(origin), str(first))
            shutil.copy2(ROOT / "run.py", first / "run.py")
            command(first, "git", "add", "run.py")
            command(first, "git", "commit", "-m", "initial event")
            command(first, "git", "push", "origin", "main")
            event_sha = command(first, "git", "rev-parse", "HEAD").stdout.strip()
            failed = command(first, sys.executable, "run.py", "--slot", "2026-09-10", "--fail-after-delivery", check=False)
            self.assertEqual(failed.returncode, 1)
            receipt = next((first / "state/outbox").glob("*.json"))
            receipt_bytes = receipt.read_bytes()
            command(first, "git", "add", "state")
            command(first, "git", "commit", "-m", "persist failed attempt")
            command(first, "git", "push", "origin", "main")
            command(base, "git", "clone", str(origin), str(fresh))
            command(fresh, "git", "checkout", "main" if branch_checkout else event_sha)
            replay = command(fresh, sys.executable, "run.py", "--slot", "2026-09-10")
            result = json.loads(replay.stdout)
            self.assertEqual(result["delivery"], "replayed", "A fresh runner must read the latest branch receipt, not repeat delivery from its stale event SHA")
            self.assertEqual((fresh / "state/outbox" / receipt.name).read_bytes(), receipt_bytes)
            self.assertEqual(len(list((fresh / "state/outbox").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
