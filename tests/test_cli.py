"""Tests for the command-line interface of agent-proc-reaper."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from agent_proc_reaper.cli import main
from agent_proc_reaper.session import list_sessions, load_session, save_session


class TestCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.sdir = Path(self.tmp.name) / "sessions"
        self.sdir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cli_help(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("agent-proc-reaper", buf.getvalue())

    def test_cli_doctor(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--session-dir", str(self.sdir), "doctor"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("Python:", out)
        self.assertIn("Platform:", out)

    def test_cli_list_empty(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--session-dir", str(self.sdir), "list"])
        self.assertEqual(code, 0)
        self.assertIn("No active or recorded agent sessions found", buf.getvalue())

    def test_cli_list_json(self) -> None:
        save_session({"session_id": "ses_test", "commands": []}, self.sdir)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--session-dir", str(self.sdir), "list", "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("sessions", payload)
        self.assertEqual(len(payload["sessions"]), 1)
        self.assertEqual(payload["sessions"][0]["session_id"], "ses_test")

    def test_cli_tree_output(self) -> None:
        save_session({"session_id": "ses_tree", "commands": []}, self.sdir)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--session-dir", str(self.sdir), "tree", "--session", "ses_tree"])
        self.assertEqual(code, 0)
        self.assertIn("Session ses_tree:", buf.getvalue())

    def test_cli_kill_dry_run_flag(self) -> None:
        save_session({"session_id": "ses_target", "commands": []}, self.sdir)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--session-dir", str(self.sdir), "kill", "--session", "ses_target"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("DRY RUN", out)

    def test_cli_run_command(self) -> None:
        sid = "ses_run_test"
        code = main([
            "--session-dir",
            str(self.sdir),
            "run",
            "--session",
            sid,
            sys.executable,
            "-c",
            "print('hello from child')",
        ])
        self.assertEqual(code, 0)
        sess = load_session(sid, self.sdir)
        self.assertIsNotNone(sess)
        self.assertEqual(len(sess["commands"]), 1)
        self.assertEqual(sess["commands"][0]["status"], "completed")
        self.assertEqual(sess["commands"][0]["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
