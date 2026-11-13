"""Tests for reaper logic and dry-run safety."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest

from agent_proc_reaper.proctree import ProcessInfo
from agent_proc_reaper.reaper import reap_session


class TestReaper(unittest.TestCase):
    def test_reap_dry_run_default(self) -> None:
        procs = {
            500: ProcessInfo(pid=500, ppid=1, pgid=500, cmdline="test_proc"),
            501: ProcessInfo(pid=501, ppid=500, pgid=500, cmdline="test_child"),
        }
        session_data = {
            "session_id": "ses_dry",
            "commands": [{"pid": 500, "pgid": 500, "cmd": ["test_proc"]}],
        }

        # Dry run should NOT send any signals
        rep = reap_session(session_data, force=False, all_procs=procs)
        self.assertTrue(rep["dry_run"])
        self.assertEqual(len(rep["killed_pids"]), 0)
        self.assertEqual(set(rep["target_pids"]), {500, 501})

    def test_protection_guards(self) -> None:
        procs = {
            1: ProcessInfo(pid=1, ppid=0, pgid=1, cmdline="init"),
            os.getpid(): ProcessInfo(pid=os.getpid(), ppid=os.getppid(), pgid=os.getpid(), cmdline="python3"),
        }
        session_data = {
            "session_id": "ses_unsafe",
            "commands": [{"pid": 1, "pgid": 1, "cmd": ["init"]}, {"pid": os.getpid(), "pgid": os.getpid(), "cmd": ["self"]}],
        }

        rep = reap_session(session_data, force=True, all_procs=procs)
        self.assertNotIn(1, rep["target_pids"])
        self.assertNotIn(os.getpid(), rep["target_pids"])

    def test_real_subprocess_termination(self) -> None:
        # Spawn an actual background sleeper
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        pid = proc.pid
        pgid = os.getpgid(pid) if hasattr(os, "getpgid") else pid

        session_data = {
            "session_id": "ses_live",
            "commands": [{"pid": pid, "pgid": pgid, "cmd": ["python", "sleep"]}],
        }

        try:
            # Force reap
            rep = reap_session(session_data, force=True, grace_period=0.5)
            self.assertFalse(rep["dry_run"])
            self.assertIn(pid, rep["killed_pids"])
            self.assertNotIn(pid, rep["survivors"])
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    unittest.main()
