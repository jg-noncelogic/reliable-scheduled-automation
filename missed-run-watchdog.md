# Detect and classify a missing scheduled GitHub Action

A 10-minute watchdog lesson for solo operators and small technical teams that depend on a daily GitHub Actions job.

**Outcome:** produce a machine-checkable classification of six conditions without treating a green run as proof of delivery:

1. a recent successful run;
2. a recent run that started and failed;
3. a recent run that is still queued, running, or otherwise nonterminal;
4. a run that exists but is older than the expected window;
5. no scheduled run for the named workflow; and
6. an observer or configuration error.

This is a companion to [Build a scheduled automation that can tell the truth](README.md). That lesson records what a run did. This one detects when no run arrived to write a record.

## Why the workflow cannot watch itself

Code inside a workflow can report a failure only after GitHub starts it. GitHub documents that scheduled events can be delayed during high load and that some queued jobs may be dropped. Public-repository schedules are also disabled after 60 days without repository activity.[2]

A heartbeat step inside the same workflow is still useful, but silence is ambiguous: the workflow may not have started, the heartbeat write may have failed, or the observer may be broken. Put the arrival check in a different scheduler or monitoring service when a missed run matters.

## Define the promise before the monitor

Write one sentence:

> `daily.yml` should create one scheduled run every 24 hours; alert when the newest scheduled run is more than 26 hours old.

The two-hour margin is a policy choice, not a GitHub guarantee. Before using it, confirm the alert will still leave enough time to recover.

**Timing caveat:** `--max-age-hours` measures from the newest run, not from the expected slot. If yesterday's 06:17 run arrived at 08:17 and today's run is missing, a 26-hour threshold cannot report `overdue` until just after 10:17, and detection occurs on the next successful monitor check. A late run arriving before that check can also erase evidence that the slot missed its deadline. If either case could miss your recovery deadline, use a slot-based alert that includes the polling interval and recovery time. [Audit a missed-run alert threshold](https://github.com/jg-noncelogic/scheduled-job-alert-budget) walks through that calculation.

Monitor the named workflow and the `schedule` event. Manual replays should not reset the missed-schedule clock. GitHub's workflow-runs API accepts a workflow file name and filters including event, status, and creation time.[1]

## Run the included public-repository watchdog

```bash
python3 watch_latest_run.py \
  --repo OWNER/REPO \
  --workflow daily.yml \
  --max-age-hours 26
```

The compact script deliberately supports public repositories only. Private-repository authentication adds credential storage and redirect handling that belong in the monitoring system you already trust, not in a copy-paste teaching helper.

The script requests only the newest run triggered by `schedule`. It prints JSON and exits:

| Exit | Status | Meaning |
|---|---|---|
| `0` | `healthy` | newest scheduled run completed successfully inside the window |
| `0` | `queued`, `in_progress`, or another nonterminal state | a recent run exists, but its outcome is not yet known |
| `2` | `failed` | newest scheduled run completed unsuccessfully |
| `2` | `overdue` | newest scheduled run is older than the declared window |
| `2` | `missing` | the API returned no scheduled runs for that workflow |
| `1` | `error` | the watchdog itself could not query or interpret GitHub |

Freshness takes precedence over run outcome. Any newest run older than the threshold is classified `overdue`; inspect `latest_run.status` and `latest_run.conclusion` to see whether that old run also failed or remains nonterminal.

Keep watchdog errors separate from workflow alerts. A rate limit, DNS failure, invalid argument, unknown API state, or invalid workflow name says the observer is unhealthy, not that the scheduled job failed.

Arm this watchdog after the first scheduled run has appeared. If inaugural-run monitoring matters, use a separate activation deadline equal to the first scheduled time plus your delay margin; `--max-age-hours` cannot age a run that does not exist.

## Schedule it outside the target workflow

On an existing always-on host, replace `/path/to/reliable-scheduled-automation`, `OWNER/REPO`, and `daily.yml` with your checkout, public repository, and workflow file, then run the check every 30 minutes:

```cron
*/30 * * * * cd /path/to/reliable-scheduled-automation && python3 watch_latest_run.py --repo OWNER/REPO --workflow daily.yml --max-age-hours 26 >> watchdog.jsonl 2>&1
```

That command records evidence but does not notify anyone. This lesson ends at reliable detection and classification. Connect exit codes `1` and `2` to the alert path your team already operates, then test that path by temporarily setting `--max-age-hours 0` before restoring the real threshold.

Do not call another GitHub Actions workflow fully independent monitoring. A separate repository reduces coupling to the target workflow file, but it still shares GitHub's scheduler and Actions control plane.

## Diagnose before replaying

When the watchdog alerts, use this order:

1. **`error`:** repair the observer or its configuration. You do not yet know the target state.
2. **recent failed run:** inspect the run log, slot ledger, and provider receipt. Determine whether the external effect happened before retrying.
3. **`overdue`:** inspect `latest_run.status` and `latest_run.conclusion` first. If it failed, follow the same run-log, ledger, and receipt check as step 2. If it is nonterminal, do not replay until you have resolved or cancelled the existing execution and confirmed it can no longer produce the effect. If it succeeded, investigate why no newer run arrived. Then inspect the workflow page and repository activity; confirm the workflow still exists on the default branch and is enabled.
4. **`missing`:** inspect the workflow page and repository activity. Confirm the workflow exists on the default branch, is enabled, and has passed its inaugural-run activation deadline.
5. **replay:** only after reconciling any existing execution and external receipt, if the target workflow exposes the retry-safe `slot` input used by this repository's example, run `gh workflow run daily.yml --repo OWNER/REPO -f slot=YYYY-MM-DD` with the exact missed business date. Replace `OWNER/REPO` with the repository monitored above. If your input has another name, adapt the flag explicitly. Do not invent a new slot from the replay time.
6. **verify:** check the workflow run, terminal ledger, and provider receipt separately.

The watchdog proves run arrival and the latest GitHub conclusion. It does not prove a report was received, a sync was applied, or a payment was accepted.

## Drill

1. Run the unit tests:

   ```bash
   python3 -m unittest -v
   ```

2. Query a real low-risk scheduled workflow with its normal threshold.
3. Repeat with `--max-age-hours 0`; expect exit `2` and `overdue` if an older scheduled run exists. A run created at that instant or within the script's five-minute future-clock-skew allowance can retain its normal status; if no scheduled run exists yet, expect exit `2` and `missing` instead.
4. Use an invalid workflow file name; expect exit `1` and `error`.
5. Restore the real command and confirm your scheduler records the JSON output.

You are done when another process can tell the difference between target silence and observer failure, and an operator can replay the original slot without guessing.

## Sources

[1] https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2022-11-28 — REST API endpoints for workflow runs
[2] https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows — Events that trigger workflows
