# Detect and classify a missing scheduled GitHub Action

A 10-minute watchdog lesson for solo operators and small technical teams that depend on a daily GitHub Actions job.

**Outcome:** produce a machine-checkable classification of four conditions without treating a green run as proof of delivery:

1. a recent successful run;
2. a run that started and failed;
3. a run that is still queued or running; and
4. no scheduled run inside the expected window.

This is a companion to [Build a scheduled automation that can tell the truth](README.md). That lesson records what a run did. This one detects when no run arrived to write a record.

## Why the workflow cannot watch itself

Code inside a workflow can report a failure only after GitHub starts it. GitHub documents that scheduled events can be delayed during high load and that some queued jobs may be dropped. Public-repository schedules are also disabled after 60 days without repository activity.[2]

A heartbeat step inside the same workflow is still useful, but silence is ambiguous: the workflow may not have started, the heartbeat write may have failed, or the observer may be broken. Put the arrival check in a different scheduler or monitoring service when a missed run matters.

## Define the promise before the monitor

Write one sentence:

> `daily.yml` should create one scheduled run every 24 hours; alert when the newest scheduled run is more than 26 hours old.

The two-hour margin is a policy choice, not a GitHub guarantee. Pick a margin that tolerates ordinary delay while still leaving time to replay the business slot.

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

Keep watchdog errors separate from workflow alerts. A rate limit, DNS failure, invalid argument, unknown API state, or invalid workflow name says the observer is unhealthy, not that the scheduled job failed.

For a newly enabled workflow, do not schedule this check until after the first run is expected. Before that point, `missing` means “no run yet,” not “a promised run was missed.”

## Schedule it outside the target workflow

On an existing always-on host, run the check every 30 minutes:

```cron
*/30 * * * * cd /opt/reliable-scheduled-automation && python3 watch_latest_run.py --repo OWNER/REPO --workflow daily.yml --max-age-hours 26 >> watchdog.jsonl 2>&1
```

That command records evidence but does not notify anyone. This lesson ends at reliable detection and classification. Connect exit codes `1` and `2` to the alert path your team already operates, then test that path by temporarily setting `--max-age-hours 0` before restoring the real threshold.

Do not call another GitHub Actions workflow fully independent monitoring. A separate repository reduces coupling to the target workflow file, but it still shares GitHub's scheduler and Actions control plane.

## Diagnose before replaying

When the watchdog alerts, use this order:

1. **`error`:** repair the observer or its configuration. You do not yet know the target state.
2. **recent failed run:** inspect the run log and slot ledger. Determine whether the external effect happened before retrying.
3. **`overdue` or `missing`:** inspect the workflow page and repository activity. Confirm the workflow still exists on the default branch and is enabled.
4. **replay:** if the target workflow exposes the `slot` input used by this repository's example, run `gh workflow run daily.yml -f slot=YYYY-MM-DD` with the exact missed business date. If your input has another name, adapt the flag explicitly. Do not invent a new slot from the replay time.
5. **verify:** check the workflow run, terminal ledger, and provider receipt separately.

The watchdog proves run arrival and the latest GitHub conclusion. It does not prove a report was received, a sync was applied, or a payment was accepted.

## Drill

1. Run the unit tests:

   ```bash
   python3 -m unittest -v
   ```

2. Query a real low-risk scheduled workflow with its normal threshold.
3. Repeat with `--max-age-hours 0`; expect exit `2` and `overdue` unless a run was created at that instant.
4. Use an invalid workflow file name; expect exit `1` and `error`.
5. Restore the real command and confirm your scheduler records the JSON output.

You are done when another process can tell the difference between target silence and observer failure, and an operator can replay the original slot without guessing.

## Sources

[1] https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2022-11-28 — REST API endpoints for workflow runs
[2] https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows — Events that trigger workflows
