import json
import tempfile
import unittest
from pathlib import Path

from run import key_for, run


class ScheduledJobTest(unittest.TestCase):
    def test_slot_is_a_canonical_date_not_a_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            for slot in ('../outside', '2026-99-10', '20260910'):
                with self.subTest(slot=slot), self.assertRaises(ValueError):
                    run(slot, Path(tmp))

    def test_same_slot_is_completed_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            first = run("2026-09-10", state)
            second = run("2026-09-10", state)
            self.assertEqual(first["status"], "completed")
            self.assertEqual(second["status"], "skipped")
            self.assertEqual(len(list((state / "outbox").glob("*.json"))), 1)

    def test_crash_after_delivery_is_safe_to_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            with self.assertRaises(RuntimeError):
                run("2026-09-10", state, fail_after_delivery=True)
            result = run("2026-09-10", state)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["delivery"], "replayed")
            self.assertEqual(len(list((state / "outbox").glob("*.json"))), 1)

    def test_receipt_and_ledger_share_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            run("2026-09-10", state)
            ledger = json.loads((state / "slots" / "2026-09-10.json").read_text())
            receipt = json.loads((state / "outbox" / f"{key_for('2026-09-10')}.json").read_text())
            self.assertEqual(ledger["idempotency_key"], receipt["idempotency_key"])


if __name__ == "__main__":
    unittest.main()
