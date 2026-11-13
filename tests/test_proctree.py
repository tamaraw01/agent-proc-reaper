"""Tests for process tree discovery and hierarchy rendering."""

from __future__ import annotations

import os
import unittest

from agent_proc_reaper.proctree import (
    ProcessInfo,
    _parse_proc_stat_field,
    find_session_process_tree,
    flatten_tree_pids,
    is_process_alive,
    render_ascii_tree,
)


class TestProcTree(unittest.TestCase):
    def test_parse_proc_stat_field(self) -> None:
        sample = "1234 (python3) S 1000 1234 1000 0 -1 4194304 120 0 0 0 10 5"
        parsed = _parse_proc_stat_field(sample)
        self.assertIsNotNone(parsed)
        pid, comm, ppid, pgid = parsed
        self.assertEqual(pid, 1234)
        self.assertEqual(comm, "python3")
        self.assertEqual(ppid, 1000)
        self.assertEqual(pgid, 1234)

    def test_parse_proc_stat_with_spaces_in_comm(self) -> None:
        sample = "5678 (Web Content) S 1 5678 1"
        parsed = _parse_proc_stat_field(sample)
        self.assertIsNotNone(parsed)
        pid, comm, ppid, pgid = parsed
        self.assertEqual(pid, 5678)
        self.assertEqual(comm, "Web Content")
        self.assertEqual(ppid, 1)
        self.assertEqual(pgid, 5678)

    def test_is_process_alive_current_process(self) -> None:
        self.assertTrue(is_process_alive(os.getpid()))
        self.assertFalse(is_process_alive(-999))
        self.assertFalse(is_process_alive(99999999))

    def test_find_session_process_tree_hierarchy(self) -> None:
        # Build synthetic system process table
        procs = {
            100: ProcessInfo(pid=100, ppid=1, pgid=100, cmdline="systemd"),
            200: ProcessInfo(pid=200, ppid=1, pgid=200, cmdline="bash agent_worker.sh"),
            201: ProcessInfo(pid=201, ppid=200, pgid=200, cmdline="python3 task.py"),
            202: ProcessInfo(pid=202, ppid=201, pgid=200, cmdline="sleep 10"),
            # Escapee that called setsid but has env marker
            300: ProcessInfo(pid=300, ppid=1, pgid=300, cmdline="daemon_srv", env_session_id="ses_abc"),
            301: ProcessInfo(pid=301, ppid=300, pgid=300, cmdline="daemon_child"),
            # Unrelated process
            400: ProcessInfo(pid=400, ppid=1, pgid=400, cmdline="nginx"),
        }

        session_data = {
            "session_id": "ses_abc",
            "commands": [{"pid": 200, "pgid": 200, "cmd": ["bash"]}],
        }

        roots = find_session_process_tree(session_data, procs)
        root_pids = [r.pid for r in roots]
        self.assertIn(200, root_pids)
        self.assertIn(300, root_pids)
        self.assertNotIn(100, root_pids)
        self.assertNotIn(400, root_pids)

        all_tree_pids = flatten_tree_pids(roots)
        self.assertIn(200, all_tree_pids)
        self.assertIn(201, all_tree_pids)
        self.assertIn(202, all_tree_pids)
        self.assertIn(300, all_tree_pids)
        self.assertIn(301, all_tree_pids)
        self.assertNotIn(400, all_tree_pids)

    def test_render_ascii_tree(self) -> None:
        p_child = ProcessInfo(pid=201, ppid=200, pgid=200, cmdline="python3 script.py", rss_kb=8192)
        p_root = ProcessInfo(pid=200, ppid=1, pgid=200, cmdline="bash", children=[p_child])

        lines = render_ascii_tree([p_root])
        self.assertTrue(len(lines) >= 2)
        self.assertTrue(any("200" in line for line in lines))
        self.assertTrue(any("201" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
