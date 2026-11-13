"""Command line interface for agent-proc-reaper."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from agent_proc_reaper import __version__
from agent_proc_reaper.proctree import (
    find_session_process_tree,
    render_ascii_tree,
    scan_system_processes,
)
from agent_proc_reaper.reaper import reap_session
from agent_proc_reaper.session import (
    ENV_SESSION_ID,
    delete_session,
    generate_session_id,
    get_current_session_id,
    get_session_dir,
    list_sessions,
    load_session,
    prune_stale_sessions,
    record_command,
    save_session,
    update_command_status,
)


def _cmd_list(args: argparse.Namespace) -> int:
    all_procs = scan_system_processes()
    sdir = get_session_dir(args.session_dir)

    target_sessions: list[dict[str, Any]] = []
    if args.session:
        data = load_session(args.session, sdir)
        if data:
            target_sessions.append(data)
        else:
            if args.format == "json":
                print(json.dumps({"error": f"Session {args.session} not found", "sessions": []}))
            else:
                print(f"Error: Session {args.session} not found in {sdir}")
            return 1
    else:
        active_id = get_current_session_id()
        all_stored = list_sessions(sdir)
        if not args.all and active_id:
            filtered = [s for s in all_stored if s.get("session_id") == active_id]
            target_sessions = filtered if filtered else all_stored
        else:
            target_sessions = all_stored

    results: list[dict[str, Any]] = []
    for sdata in target_sessions:
        sid = sdata.get("session_id", "unknown")
        roots = find_session_process_tree(sdata, all_procs)
        active_pids: list[int] = []

        def _collect_pids(node: Any) -> None:
            active_pids.append(node.pid)
            for ch in node.children:
                _collect_pids(ch)

        for r in roots:
            _collect_pids(r)

        results.append({
            "session_id": sid,
            "created_at": sdata.get("created_at"),
            "updated_at": sdata.get("updated_at"),
            "tracked_commands": len(sdata.get("commands", [])),
            "active_processes": len(active_pids),
            "active_pids": active_pids,
            "root_nodes": [r.to_dict() for r in roots],
        })

    if args.format == "json":
        print(json.dumps({"sessions": results}, indent=2))
        return 0

    if not results:
        print("No active or recorded agent sessions found.")
        print(f"Session directory: {sdir}")
        print("Tip: Run commands with 'agent-proc-reaper run -- <command>' to begin tracking.")
        return 0

    current = get_current_session_id()
    print(f"Agent Process Reaper (v{__version__}) - Session Audit")
    print(f"Storage: {sdir}")
    if current:
        print(f"Active Session Env ($AGENT_SESSION_ID): {current}")
    print("=" * 70)

    for item in results:
        marker = " [CURRENT]" if item["session_id"] == current else ""
        print(f"\nSession: {item['session_id']}{marker}")
        print(f"  Commands tracked: {item['tracked_commands']}")
        print(f"  Active processes alive: {item['active_processes']}")
        if item["active_pids"]:
            print(f"  PIDs: {', '.join(str(p) for p in item['active_pids'])}")

    print("\n" + "=" * 70)
    return 0


def _cmd_tree(args: argparse.Namespace) -> int:
    all_procs = scan_system_processes()
    sdir = get_session_dir(args.session_dir)

    target_sessions: list[dict[str, Any]] = []
    if args.session:
        data = load_session(args.session, sdir)
        if data:
            target_sessions.append(data)
        else:
            print(f"Error: Session {args.session} not found.")
            return 1
    else:
        active_id = get_current_session_id()
        all_stored = list_sessions(sdir)
        if active_id and not args.all:
            target_sessions = [s for s in all_stored if s.get("session_id") == active_id]
            if not target_sessions:
                target_sessions = all_stored
        else:
            target_sessions = all_stored

    if not target_sessions:
        print("No sessions found to display process tree.")
        return 0

    for sdata in target_sessions:
        sid = sdata.get("session_id", "unknown")
        roots = find_session_process_tree(sdata, all_procs)
        print(f"Session {sid}:")
        if not roots:
            print("  (no active processes running)")
        else:
            lines = render_ascii_tree(roots, prefix="  ")
            for line in lines:
                print(line)
        print()
    return 0


def _cmd_kill(args: argparse.Namespace) -> int:
    all_procs = scan_system_processes()
    sdir = get_session_dir(args.session_dir)

    target_sessions: list[dict[str, Any]] = []
    if args.session:
        data = load_session(args.session, sdir)
        if data:
            target_sessions.append(data)
        else:
            if args.format == "json":
                print(json.dumps({"error": f"Session {args.session} not found"}))
            else:
                print(f"Error: Session {args.session} not found.")
            return 1
    elif args.all:
        target_sessions = list_sessions(sdir)
    else:
        active_id = get_current_session_id()
        if active_id:
            data = load_session(active_id, sdir)
            if data:
                target_sessions.append(data)
        if not target_sessions:
            # Fall back to all sessions if only one exists
            all_s = list_sessions(sdir)
            if len(all_s) == 1:
                target_sessions = all_s

    if not target_sessions:
        if args.format == "json":
            print(json.dumps({"error": "No target session specified. Use --session <id> or --all."}))
        else:
            print("Error: Specify a session via --session <id> or use --all.")
        return 1

    reports: list[dict[str, Any]] = []
    for sdata in target_sessions:
        rep = reap_session(
            session_data=sdata,
            force=args.force,
            grace_period=args.grace,
            all_procs=all_procs,
            session_dir=args.session_dir,
        )
        reports.append(rep)

    if args.format == "json":
        print(json.dumps({"results": reports}, indent=2))
        return 0

    mode_label = "EXECUTION (FORCE)" if args.force else "DRY RUN (Simulated, no signals sent)"
    print(f"Agent Process Reaper - Kill Mode: {mode_label}")
    print("=" * 70)

    for rep in reports:
        sid = rep["session_id"]
        print(f"\nSession {sid}:")
        targets = rep["target_pids"]
        print(f"  Target PIDs found: {len(targets)} {targets}")
        if rep["dry_run"]:
            print("  Dry run active: pass --force (-f) to terminate these processes.")
        else:
            print(f"  Terminated: {len(rep['killed_pids'])} {rep['killed_pids']}")
            if rep["survivors"]:
                print(f"  Survivors remaining: {len(rep['survivors'])} {rep['survivors']}")
            if rep["errors"]:
                print(f"  Errors: {rep['errors']}")

    print("\n" + "=" * 70)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    if not args.cmd:
        print("Error: No command specified to run. Usage: agent-proc-reaper run -- <command>")
        return 1

    sdir = get_session_dir(args.session_dir)
    sid = args.session or get_current_session_id() or generate_session_id()

    # Ensure session exists
    sdata = load_session(sid, sdir)
    if sdata is None:
        sdata = {
            "session_id": sid,
            "created_at": time.time(),
            "updated_at": time.time(),
            "commands": [],
        }
        save_session(sdata, sdir)

    env = os.environ.copy()
    env[ENV_SESSION_ID] = sid

    # Start child in its own process group where possible
    kwargs: dict[str, Any] = {"env": env}
    if hasattr(os, "setsid"):
        kwargs["preexec_fn"] = os.setsid

    proc = subprocess.Popen(args.cmd, **kwargs)
    pgid = proc.pid
    if hasattr(os, "getpgid"):
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            pgid = proc.pid

    record_command(
        session_id=sid,
        pid=proc.pid,
        pgid=pgid,
        cmd=args.cmd,
        cwd=os.getcwd(),
        session_dir=sdir,
    )

    try:
        exit_code = proc.wait()
    except KeyboardInterrupt:
        # User interrupted: reap child process tree
        print("\nInterrupted: reaping session process tree...")
        sdata = load_session(sid, sdir)
        if sdata:
            reap_session(sdata, force=True, grace_period=0.5, session_dir=sdir)
        return 130

    update_command_status(sid, proc.pid, "completed", exit_code=exit_code, session_dir=sdir)
    return exit_code


def _cmd_doctor(args: argparse.Namespace) -> int:
    sdir = get_session_dir(args.session_dir)
    sessions = list_sessions(sdir)

    print(f"Agent Process Reaper (v{__version__}) - System Diagnostic")
    print("=" * 60)
    print(f"Python:       {sys.version.split()[0]} ({platform.python_implementation()})")
    print(f"Platform:     {sys.platform} ({platform.platform()})")
    print(f"Storage dir:  {sdir}")
    print(f"Sessions:     {len(sessions)} recorded in store")

    # Check Linux /proc
    proc_ok = Path("/proc").is_dir()
    print(f"Procfs:       {'Available (/proc)' if proc_ok else 'Not available (using ps fallback)'}")

    # Check PR_SET_CHILD_SUBREAPER support on Linux
    subreaper_support = False
    if sys.platform.startswith("linux"):
        try:
            libc = ctypes.CDLL(None)
            if hasattr(libc, "prctl"):
                # PR_GET_CHILD_SUBREAPER = 37
                val = ctypes.c_int()
                res = libc.prctl(37, ctypes.byref(val), 0, 0, 0)
                if res == 0:
                    subreaper_support = True
        except Exception:
            subreaper_support = False

    print(f"Subreaper:    {'Supported (PR_SET_CHILD_SUBREAPER)' if subreaper_support else 'Not supported'}")
    print("=" * 60)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-proc-reaper",
        description="Session-scoped process tree supervisor and reaper for AI agent environments.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--session-dir", default=None, help="Custom directory for session records.")

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # list
    p_list = subparsers.add_parser("list", help="List tracked sessions and running processes.")
    p_list.add_argument("--session", "-s", default=None, help="Target specific session id.")
    p_list.add_argument("--all", "-a", action="store_true", help="List all sessions ignoring current env.")
    p_list.add_argument("--format", choices=["text", "json"], default="text", help="Output format.")

    # tree
    p_tree = subparsers.add_parser("tree", help="Display ASCII process hierarchy tree for session(s).")
    p_tree.add_argument("--session", "-s", default=None, help="Target specific session id.")
    p_tree.add_argument("--all", "-a", action="store_true", help="Display trees for all sessions.")

    # kill
    p_kill = subparsers.add_parser("kill", help="Audit or kill session process tree. Dry-run by default.")
    p_kill.add_argument("--session", "-s", default=None, help="Target specific session id.")
    p_kill.add_argument("--all", "-a", action="store_true", help="Kill processes across all recorded sessions.")
    p_kill.add_argument("--force", "-f", action="store_true", help="Actually send signals (SIGTERM then SIGKILL).")
    p_kill.add_argument("--grace", type=float, default=1.0, help="Grace period seconds between TERM and KILL.")
    p_kill.add_argument("--format", choices=["text", "json"], default="text", help="Output format.")

    # run
    p_run = subparsers.add_parser("run", help="Run a command under session tracking.")
    p_run.add_argument("--session", "-s", default=None, help="Explicit session id to bind to.")
    p_run.add_argument("cmd", nargs=argparse.REMAINDER, help="Command and arguments to execute.")

    # doctor
    subparsers.add_parser("doctor", help="Inspect platform capabilities and environment health.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    if args.subcommand == "list":
        return _cmd_list(args)
    elif args.subcommand == "tree":
        return _cmd_tree(args)
    elif args.subcommand == "kill":
        return _cmd_kill(args)
    elif args.subcommand == "run":
        return _cmd_run(args)
    elif args.subcommand == "doctor":
        return _cmd_doctor(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
