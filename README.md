# Build a scheduled automation that can tell the truth

A practical lesson for solo operators and small teams using GitHub Actions for daily reports, syncs, alerts, or content jobs.

**Outcome:** in about 25 minutes, turn a fragile cron workflow into a job that:

- prevents overlapping runs;
- gives every business interval a stable identity;
- makes retries reuse the same side-effect key; and
- leaves an inspectable terminal record.

This is not an “exactly once” recipe. It is a small system that makes duplicate work less likely and ambiguous outcomes visible.

## The scenario

Suppose a workflow builds and sends one customer-health digest each day. The first version is tempting:

```yaml
on:
  schedule:
    - cron: "0 6 * * *"

jobs:
  send:
    runs-on: ubuntu-latest
    steps:
      - run: python send_digest.py
```

It has four unanswered questions:

1. What happens if yesterday's run is still active?
2. What does a manual retry mean: a new digest or a replay of the old one?
3. What happens if delivery succeeds and the process crashes before reporting success?
4. Where can an operator see that a date was completed, skipped, or left uncertain?

These are ordinary conditions, not edge cases. GitHub says scheduled workflows can be delayed at high-load times, especially at the start of an hour, and sufficiently loaded queued jobs may be dropped.[1] It also allows separate workflow runs to execute concurrently by default.[2]

The fix is not “retry harder.” Give the job a contract.

## The four-control contract

### 1. Concurrency controls overlap

Add one concurrency group for one logical job:

```yaml
concurrency:
  group: daily-bounded-automation
  cancel-in-progress: false
```

This stops two copies of this workflow from running at the same time. It protects the ledger from concurrent writers. It does **not** prove a side effect happened once, and it is not a durable queue.

GitHub's concurrency behavior limits runs within a group; its documentation also warns that concurrent copies otherwise perform the same steps.[2]

### 2. A stable slot controls identity

A run ID answers “which execution was this?” A slot answers “which piece of business work was this?”

For one daily digest, use a date such as `2026-09-10`. A manual retry must accept the same date explicitly:

```bash
python3 run.py --slot 2026-09-10
```

Do not use a fresh UUID as the business identity. A fresh value makes every retry look new. Derive downstream idempotency keys from the stable slot:

```text
sha256("daily-digest:" + slot)
```

Keep sensitive values out of the key. Stripe's API documentation is a useful concrete model: a client-supplied idempotency key lets a retry return the saved result rather than perform the operation twice, and reused keys are checked against the original parameters.[4]

### 3. A terminal ledger controls memory

Before the side effect, write a `started` record. After it, replace that record with `completed`.

```json
{
  "status": "completed",
  "slot": "2026-09-10",
  "started_at": "2026-09-10T06:17:04Z",
  "completed_at": "2026-09-10T06:17:05Z",
  "idempotency_key": "...",
  "delivery": "delivered"
}
```

The included example stores one file per slot under `state/slots/`. The demonstration workflow commits those records to Git because that is transparent and adequate for one low-volume job. For many writers or high frequency, use a database with a unique constraint on `(job_name, slot)`.

The workflow loads the current default branch after acquiring its concurrency
slot, and attempts to persist state even when the job exits with an error.
Otherwise a new runner could start from an old checkout or lose the previous
runner's recovery record. A killed runner, failed push, or repository write-policy
failure can still prevent persistence: Git at the end of a run is not a durable
transaction around an external action. Real delivery needs destination-side
idempotency or an appropriate durable delivery system. The local outbox below is
a teaching simulation, not a production email/payment sender.

The useful states are:

| State | Meaning | Next action |
|---|---|---|
| no record | Not attempted, or the scheduler never started it | Decide whether to replay the slot |
| `started` | Work began but no terminal outcome was recorded | Retry with the same slot and key; inspect the provider receipt |
| `completed` | The slot reached its declared terminal condition | Skip a duplicate run |
| `failed` | A known failure was recorded | Fix the cause, then retry the same slot if safe |

A missing record is deliberately different from a failed record. Scheduler non-arrival cannot be diagnosed from job code that never ran.

### 4. Monitoring controls what you may claim

GitHub exposes each run's status and logs, and failed runs can be searched, downloaded, and rerun.[3] Those logs establish what GitHub executed. Your slot ledger establishes what the job believes happened. The external provider's receipt establishes whether the side effect happened.

Use all three when the outcome matters:

```text
scheduler/run log  -> did the process run?
slot ledger        -> which business interval and terminal state?
provider receipt   -> did the external effect happen?
```

Do not turn “workflow succeeded” into “customer received the message” unless the delivery system supplies that evidence.

## The worked implementation

This repository contains:

- [`run.py`](run.py): a standard-library job with atomic ledger writes;
- [`test_run.py`](test_run.py): duplicate and crash/retry drills;
- [`examples/daily.yml`](examples/daily.yml): a copyable schedule, manual replay, concurrency, and durable state commit.

The example workflow is intentionally outside `.github/workflows/`, so cloning this teaching repository does not start a live daily job. Copy it to `.github/workflows/daily.yml` in the repository where you want it to run.

`deliver_once()` is a local outbox standing in for an external API. Replace it with your provider call, but pass `key_for(slot)` through the provider's idempotency mechanism when it has one. Keep the same key on every replay of that slot.

### Run it locally

```bash
python3 -m unittest -v
python3 run.py --slot 2026-09-10 --state-dir .tmp-state
python3 run.py --slot 2026-09-10 --state-dir .tmp-state
```

The first run completes. The second prints:

```json
{
  "status": "skipped",
  "reason": "slot_already_completed",
  "slot": "2026-09-10"
}
```

### Run the failure drill

Simulate the difficult boundary: delivery succeeds, then the process crashes before it writes `completed`.

```bash
rm -rf .tmp-state
python3 run.py --slot 2026-09-10 --state-dir .tmp-state --fail-after-delivery || true
python3 run.py --slot 2026-09-10 --state-dir .tmp-state
find .tmp-state/outbox -type f
```

Expected result:

- the first command exits nonzero after creating one delivery receipt;
- the retry uses the same key and reports `"delivery": "replayed"`;
- the outbox still contains one receipt; and
- the slot ends as `completed`.

The local outbox can guarantee this because it owns an atomic create operation. Your real guarantee is only as strong as the destination API. If it has no idempotency facility, add a durable outbox and a separate sender, or accept and document the duplicate-risk window.

## Put it into a repository

1. Copy `run.py`, its tests, and the workflow.
2. Change `daily-digest` in `key_for()` to a stable name for your job.
3. Replace the local `deliver_once()` with one narrow provider operation.
4. Add any secret through repository or environment secrets, never in the slot record.
5. Choose an off-peak minute. The example uses `06:17 UTC` rather than the top of the hour because GitHub documents higher schedule load there.[1]
6. In repository settings, allow GitHub Actions to read and write repository contents if you keep the Git-backed ledger.
7. Run `workflow_dispatch` with a harmless test slot and inspect the commit and provider receipt.

This example deliberately runs code and state from the current default branch,
including manual replays. Use a separate test repository for changes. Its slot
input must be a valid `YYYY-MM-DD` date; it is passed as data, not interpolated
into shell source. Never put real customer payloads or secrets in this public
example's Git-backed ledger.

Scheduled workflows run from the latest commit on the default branch, and public repositories can have scheduled workflows disabled after 60 days without repository activity.[1] If missing a run matters, add a separate heartbeat monitor outside the workflow. A workflow cannot alert you that it never started.

## Fifteen-minute adoption path

If the full pattern is too much for today:

**Minutes 0–3:** move the cron minute away from `0` and add a concurrency group.

**Minutes 3–7:** define the slot in one sentence, for example: “one UTC calendar date of the customer-health digest.”

**Minutes 7–11:** send that slot-derived key to the one external write that matters most.

**Minutes 11–15:** persist `started` and `completed`, then rehearse one retry with the same slot.

That sequence improves the failure boundary without pretending the whole system is solved.

## Review checklist

Before trusting a scheduled automation, answer these without opening the code:

- [ ] What is the stable business slot?
- [ ] Can an operator replay that exact slot manually?
- [ ] Can two copies overlap?
- [ ] Which write carries the idempotency key?
- [ ] Where is `started` persisted before the write?
- [ ] Where is the terminal result persisted?
- [ ] What evidence comes from the provider rather than the workflow?
- [ ] How will someone notice a scheduler run that never started?
- [ ] What is the retention period for logs, ledger entries, and provider receipts?
- [ ] Has the crash-after-delivery drill been run?

## Limits and upgrades

This compact design is appropriate for one low-frequency workflow and a small team. Upgrade it when:

- multiple jobs write the same state: use transactional storage and unique slot constraints;
- ordering matters: use a real queue rather than concurrency cancellation behavior;
- delivery lacks idempotency: use a transactional outbox and reconcile receipts;
- a date is too coarse: define slots from domain windows, not execution timestamps;
- a missed schedule has material impact: monitor expected slots from an independent system;
- records contain customer data: store references and hashes, not sensitive payloads, and set retention rules.

The goal is not a green dashboard. It is a job whose operator can distinguish completed, safely replayable, failed, and unknown.

## Sources

[1] [Events that trigger workflows: schedule - GitHub Docs](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
[2] [Concurrency - GitHub Docs](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency)
[3] [Using workflow run logs - GitHub Docs](https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs)
[4] [Idempotent requests - Stripe API Reference](https://docs.stripe.com/api/idempotent_requests)
