"""Tests for session management in agent-proc-reaper."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from agent_proc_reaper.session import (
    delete_session,
    generate_session_id,
    get_session_dir,
    list_sessions,
    load_session,
    prune_stale_sessions,
    record_command,
    save_session,
    update_command_status,
)


class TestSessionRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.session_dir = Path(self.tmp.name) / "sessions"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_session_dir_creation(self) -> None:
        p = get_session_dir(self.session_dir)
        self.assertTrue(p.is_dir())

    def test_generate_session_id(self) -> None:
        sid1 = generate_session_id()
        sid2 = generate_session_id()
        self.assertTrue(sid1.startswith("ses_"))
        self.assertNotEqual(sid1, sid2)

    def test_save_and_load_session(self) -> None:
        sid = "ses_test1"
        data = {
            "session_id": sid,
            "created_at": time.time(),
            "commands": [],
        }
        fpath = save_session(data, self.session_dir)
        self.assertTrue(fpath.is_file())

        loaded = load_session(sid, self.session_dir)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["session_id"], sid)
        self.assertIn("updated_at", loaded)

    def test_record_and_update_command(self) -> None:
        sid = "ses_cmd_test"
        entry = record_command(
            session_id=sid,
            pid=12345,
            pgid=12345,
            cmd=["python3", "worker.py"],
            session_dir=self.session_dir,
        )
        self.assertEqual(entry["pid"], 12345)
        self.assertEqual(entry["status"], "running")

        # Update status
        ok = update_command_status(
            session_id=sid,
            pid=12345,
            status="completed",
            exit_code=0,
            session_dir=self.session_dir,
        )
        self.assertTrue(ok)

        sess = load_session(sid, self.session_dir)
        self.assertIsNotNone(sess)
        self.assertEqual(len(sess["commands"]), 1)
        self.assertEqual(sess["commands"][0]["status"], "completed")
        self.assertEqual(sess["commands"][0]["exit_code"], 0)

    def test_list_and_delete_session(self) -> None:
        save_session({"session_id": "ses_a"}, self.session_dir)
        save_session({"session_id": "ses_b"}, self.session_dir)

        all_sess = list_sessions(self.session_dir)
        sids = [s["session_id"] for s in all_sess]
        self.assertIn("ses_a", sids)
        self.assertIn("ses_b", sids)

        deleted = delete_session("ses_a", self.session_dir)
        self.assertTrue(deleted)
        remaining = list_sessions(self.session_dir)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["session_id"], "ses_b")

    def test_prune_stale_sessions(self) -> None:
        old_time = time.time() - 10000.0
        data_old = {"session_id": "ses_old", "created_at": old_time, "updated_at": old_time}
        data_new = {"session_id": "ses_new", "created_at": time.time(), "updated_at": time.time()}

        save_session(data_old, self.session_dir)
        # overwrite updated_at to ensure it tests old timestamp
        old_file = self.session_dir / "ses_old.json"
        import json

        data_old["updated_at"] = old_time
        old_file.write_text(json.dumps(data_old))

        save_session(data_new, self.session_dir)

        pruned = prune_stale_sessions(max_age_seconds=3600, session_dir=self.session_dir)
        self.assertIn("ses_old", pruned)
        self.assertNotIn("ses_new", pruned)


if __name__ == "__main__":
    unittest.main()
