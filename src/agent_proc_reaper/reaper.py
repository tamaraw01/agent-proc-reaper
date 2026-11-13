"""Safe process reaping and termination engine for agent-proc-reaper."""

from __future__ import annotations

import os
import signal
import time
from typing import Any

from agent_proc_reaper.proctree import (
    ProcessInfo,
    find_session_process_tree,
    flatten_tree_pids,
    is_process_alive,
    scan_system_processes,
)
from agent_proc_reaper.session import update_command_status


def reap_session(
    session_data: dict[str, Any],
    force: bool = False,
    grace_period: float = 1.0,
    all_procs: dict[int, ProcessInfo] | None = None,
    session_dir: str | None = None,
) -> dict[str, Any]:
    """Audit or terminate all processes belonging to a given session."""
    session_id = session_data.get("session_id", "unknown")
    if all_procs is None:
        all_procs = scan_system_processes()

    roots = find_session_process_tree(session_data, all_procs)
    target_pids = flatten_tree_pids(roots)

    # Protect against self-termination or system processes
    protected = {0, 1, os.getpid(), os.getppid()}
    target_pids = [p for p in target_pids if p not in protected]

    # Collect tracked PGIDs from session records, ignoring own process group
    ignored_pgids = {0, 1}
    if hasattr(os, "getpgrp"):
        try:
            ignored_pgids.add(os.getpgrp())
        except OSError:
            pass

    tracked_pgids = {
        cmd.get("pgid")
        for cmd in session_data.get("commands", [])
        if isinstance(cmd.get("pgid"), int) and cmd.get("pgid") not in ignored_pgids
    }

    report: dict[str, Any] = {
        "session_id": session_id,
        "dry_run": not force,
        "target_pids": target_pids,
        "killed_pids": [],
        "survivors": [],
        "errors": [],
    }

    if not force:
        # Dry run: return target inventory without sending signals
        return report

    if not target_pids:
        return report

    # Phase 1: Send SIGTERM to tracked process groups
    for pgid in tracked_pgids:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    # Phase 2: Send SIGTERM to individual target PIDs (children first)
    for pid in target_pids:
        if is_process_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                report["errors"].append(f"Permission denied sending SIGTERM to PID {pid}")
            except OSError as e:
                report["errors"].append(f"Error signalling PID {pid}: {e}")

    # Phase 3: Wait up to grace_period for processes to exit cleanly
    deadline = time.time() + grace_period
    while time.time() < deadline:
        alive = [p for p in target_pids if is_process_alive(p)]
        if not alive:
            break
        time.sleep(0.05)

    # Phase 4: Escalate to SIGKILL for any stubborn processes
    remaining = [p for p in target_pids if is_process_alive(p)]
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            report["errors"].append(f"Permission denied sending SIGKILL to PID {pid}")
        except OSError as e:
            report["errors"].append(f"Error killing PID {pid}: {e}")

    # Brief settle delay
    if remaining:
        time.sleep(0.1)

    # Final tally
    for pid in target_pids:
        if is_process_alive(pid):
            report["survivors"].append(pid)
        else:
            report["killed_pids"].append(pid)

    # Update session registry
    for cmd in session_data.get("commands", []):
        cpid = cmd.get("pid")
        if cpid in report["killed_pids"]:
            update_command_status(session_id, cpid, "killed", session_dir=session_dir)

    return report
