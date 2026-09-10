#!/usr/bin/env python3
"""A small, inspectable scheduled job with a durable slot ledger."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    os.replace(temp, path)


def key_for(slot: str) -> str:
    return hashlib.sha256(f"daily-digest:{slot}".encode()).hexdigest()[:24]


def deliver_once(outbox: Path, key: str, payload: dict) -> str:
    """Local stand-in for an API that accepts an idempotency key."""
    outbox.mkdir(parents=True, exist_ok=True)
    receipt = outbox / f"{key}.json"
    try:
        fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return "replayed"
    with os.fdopen(fd, "w") as handle:
        json.dump({"idempotency_key": key, "payload": payload, "delivered_at": now()}, handle, indent=2)
        handle.write("\n")
    return "delivered"


def run(slot: str, state_dir: Path, fail_after_delivery: bool = False) -> dict:
    if date.fromisoformat(slot).isoformat() != slot:
        raise ValueError("slot must be a UTC business date in YYYY-MM-DD form")
    state_path = state_dir / "slots" / f"{slot}.json"
    if state_path.exists():
        prior = json.loads(state_path.read_text())
        if prior.get("status") == "completed":
            return {"status": "skipped", "reason": "slot_already_completed", "slot": slot}

    key = key_for(slot)
    started = {"status": "started", "slot": slot, "started_at": now(), "idempotency_key": key}
    write_atomic(state_path, started)

    delivery = deliver_once(state_dir / "outbox", key, {"kind": "daily-digest", "slot": slot})
    if fail_after_delivery:
        raise RuntimeError("failure drill: crashed after delivery, before completion record")

    result = {**started, "status": "completed", "completed_at": now(), "delivery": delivery}
    write_atomic(state_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", required=True, help="Stable business slot, for example 2026-09-10")
    parser.add_argument("--state-dir", type=Path, default=Path("state"))
    parser.add_argument("--fail-after-delivery", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.slot, args.state_dir, args.fail_after_delivery), indent=2))
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "slot": args.slot, "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
