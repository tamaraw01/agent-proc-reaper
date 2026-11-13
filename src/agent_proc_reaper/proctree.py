"""Process tree discovery and inspection for agent-proc-reaper."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    pgid: int
    cmdline: str
    rss_kb: int = 0
    env_session_id: str | None = None
    children: list[ProcessInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "ppid": self.ppid,
            "pgid": self.pgid,
            "cmdline": self.cmdline,
            "rss_kb": self.rss_kb,
            "env_session_id": self.env_session_id,
            "children": [c.to_dict() for c in self.children],
        }


def is_process_alive(pid: int) -> bool:
    """Return True if the process exists and is actively running (not dead or zombie)."""
    if pid <= 0:
        return False

    # If this PID is a child of the current Python process, reap it if already exited
    try:
        wpid, _ = os.waitpid(pid, os.WNOHANG)
        if wpid == pid:
            return False
    except (ChildProcessError, OSError):
        pass

    try:
        os.kill(pid, 0)
    except OSError:
        return False

    # Check Linux /proc/<pid>/stat state for Zombie ('Z') or Dead ('X')
    stat_file = Path(f"/proc/{pid}/stat")
    if stat_file.is_file():
        try:
            content = stat_file.read_text(encoding="utf-8", errors="replace")
            rparen = content.rfind(")")
            if rparen != -1 and len(content) > rparen + 2:
                state = content[rparen + 2]
                if state in ("Z", "X"):
                    return False
        except OSError:
            return False

    return True


def _parse_proc_stat_field(content: str) -> tuple[int, str, int, int] | None:
    """Extract (pid, comm, ppid, pgid) from /proc/<pid>/stat line."""
    try:
        rparen = content.rfind(")")
        if rparen == -1:
            return None
        lparen = content.find("(")
        if lparen == -1:
            return None
        pid = int(content[:lparen].strip())
        comm = content[lparen + 1 : rparen]
        rest = content[rparen + 2 :].split()
        ppid = int(rest[1])
        pgid = int(rest[2])
        return pid, comm, ppid, pgid
    except (IndexError, ValueError):
        return None


def _read_proc_linux() -> dict[int, ProcessInfo]:
    """Read process table directly from Linux /proc filesystem."""
    procs: dict[int, ProcessInfo] = {}
    proc_dir = Path("/proc")
    if not proc_dir.exists():
        return procs

    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        stat_file = entry / "stat"
        if not stat_file.is_file():
            continue

        try:
            stat_text = stat_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        parsed = _parse_proc_stat_field(stat_text)
        if not parsed:
            continue
        pid_val, comm, ppid, pgid = parsed

        cmdline = comm
        cmdline_file = entry / "cmdline"
        try:
            raw_cmd = cmdline_file.read_bytes()
            if raw_cmd:
                parts = [p.decode("utf-8", errors="replace") for p in raw_cmd.split(b"\x00") if p]
                if parts:
                    cmdline = " ".join(parts)
        except OSError:
            pass

        rss_kb = 0
        statm_file = entry / "statm"
        try:
            statm_parts = statm_file.read_text().split()
            if len(statm_parts) >= 2:
                rss_kb = int(statm_parts[1]) * 4
        except (OSError, ValueError):
            pass

        env_session_id = None
        environ_file = entry / "environ"
        try:
            raw_env = environ_file.read_bytes()
            for chunk in raw_env.split(b"\x00"):
                if chunk.startswith(b"AGENT_SESSION_ID="):
                    env_session_id = chunk.decode("utf-8", errors="replace").split("=", 1)[1]
                    break
        except OSError:
            pass

        procs[pid] = ProcessInfo(
            pid=pid_val,
            ppid=ppid,
            pgid=pgid,
            cmdline=cmdline,
            rss_kb=rss_kb,
            env_session_id=env_session_id,
        )

    return procs


def _read_proc_posix_ps() -> dict[int, ProcessInfo]:
    """Read process table via ps command (macOS and BSD fallback)."""
    procs: dict[int, ProcessInfo] = {}
    try:
        cmd = ["ps", "-axo", "pid=,ppid=,pgid=,command="]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            parts = line.strip().split(None, 3)
            if len(parts) >= 3:
                pid = int(parts[0])
                ppid = int(parts[1])
                pgid = int(parts[2])
                cmdline = parts[3] if len(parts) >= 4 else ""
                procs[pid] = ProcessInfo(
                    pid=pid,
                    ppid=ppid,
                    pgid=pgid,
                    cmdline=cmdline,
                )
    except (subprocess.SubprocessError, OSError, ValueError):
        pass
    return procs


def scan_system_processes() -> dict[int, ProcessInfo]:
    """Scan and return all visible system processes mapped by PID."""
    if sys.platform.startswith("linux") and Path("/proc").exists():
        procs = _read_proc_linux()
        if procs:
            return procs
    return _read_proc_posix_ps()


def find_session_process_tree(
    session_data: dict[str, Any],
    all_procs: dict[int, ProcessInfo] | None = None,
) -> list[ProcessInfo]:
    """Find all active processes owned by or descended from a session."""
    if all_procs is None:
        all_procs = scan_system_processes()

    session_id = session_data.get("session_id", "")
    recorded_commands = session_data.get("commands", [])

    ignored_pgids = {0, 1}
    if hasattr(os, "getpgrp"):
        try:
            ignored_pgids.add(os.getpgrp())
        except OSError:
            pass

    tracked_pids: set[int] = set()
    tracked_pgids: set[int] = set()

    for cmd in recorded_commands:
        p = cmd.get("pid")
        g = cmd.get("pgid")
        if p and isinstance(p, int):
            tracked_pids.add(p)
        if g and isinstance(g, int) and g not in ignored_pgids:
            tracked_pgids.add(g)

    # Iterative discovery of descendants and session-marker escapees
    session_pids: set[int] = set()

    # Step 1: Initial membership based on root PIDs, valid PGIDs, and env markers
    for pid, proc in all_procs.items():
        if pid in tracked_pids:
            session_pids.add(pid)
        elif proc.pgid in tracked_pgids:
            session_pids.add(pid)
        elif session_id and proc.env_session_id == session_id:
            session_pids.add(pid)

    # Step 2: Propagate parent -> child relationships until convergence
    changed = True
    while changed:
        changed = False
        for pid, proc in all_procs.items():
            if pid not in session_pids:
                if proc.ppid in session_pids:
                    session_pids.add(pid)
                    changed = True
                elif proc.pgid in tracked_pgids:
                    session_pids.add(pid)
                    changed = True

    # Assemble hierarchy
    procs_in_tree = {pid: all_procs[pid] for pid in session_pids if pid in all_procs}
    roots: list[ProcessInfo] = []

    # Reset children
    for proc in procs_in_tree.values():
        proc.children = []

    for pid, proc in procs_in_tree.items():
        if proc.ppid in procs_in_tree and proc.ppid != pid:
            procs_in_tree[proc.ppid].children.append(proc)
        else:
            roots.append(proc)

    roots.sort(key=lambda p: p.pid)
    return roots


def flatten_tree_pids(roots: list[ProcessInfo]) -> list[int]:
    """Return all PIDs in the tree in depth-first order (children before parents)."""
    post_order: list[int] = []

    def _walk(node: ProcessInfo) -> None:
        for child in node.children:
            _walk(child)
        post_order.append(node.pid)

    for r in roots:
        _walk(r)
    return post_order


def render_ascii_tree(roots: list[ProcessInfo], prefix: str = "") -> list[str]:
    """Render an ASCII tree representing the process hierarchy."""
    lines: list[str] = []

    def _format_node(node: ProcessInfo) -> str:
        cmd_summary = node.cmdline[:60] + "..." if len(node.cmdline) > 60 else node.cmdline
        rss_str = f", {node.rss_kb // 1024}MB RSS" if node.rss_kb > 0 else ""
        return f"{node.pid} (ppid={node.ppid}, pgid={node.pgid}{rss_str}) {cmd_summary}"

    def _render(nodes: list[ProcessInfo], curr_prefix: str) -> None:
        count = len(nodes)
        for i, node in enumerate(nodes):
            is_last = (i == count - 1)
            connector = "`-- " if is_last else "|-- "
            lines.append(f"{curr_prefix}{connector}{_format_node(node)}")
            next_prefix = curr_prefix + ("    " if is_last else "|   ")
            if node.children:
                _render(node.children, next_prefix)

    _render(roots, prefix)
    return lines
