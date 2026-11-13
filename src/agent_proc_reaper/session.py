"""Session registry and process ownership tracking for agent-proc-reaper."""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

ENV_SESSION_ID = "AGENT_SESSION_ID"
ENV_SESSION_DIR = "AGENT_PROC_REAPER_DIR"
DEFAULT_SUBDIR = ".agent-proc-reaper/sessions"


def get_session_dir(custom_path: str | Path | None = None) -> Path:
    """Return the absolute Path to the session metadata directory."""
    if custom_path is not None:
        p = Path(custom_path).expanduser().resolve()
    elif os.environ.get(ENV_SESSION_DIR):
        p = Path(os.environ[ENV_SESSION_DIR]).expanduser().resolve()
    else:
        p = Path.home() / DEFAULT_SUBDIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def generate_session_id(prefix: str = "ses_") -> str:
    """Generate a clean random session identifier."""
    token = secrets.token_hex(6)
    return f"{prefix}{token}"


def get_current_session_id() -> str | None:
    """Return the active session id from environment if set."""
    val = os.environ.get(ENV_SESSION_ID, "").strip()
    return val if val else None


def _session_file(session_id: str, session_dir: Path) -> Path:
    safe_name = "".join(c for c in session_id if c.isalnum() or c in ("-", "_"))
    return session_dir / f"{safe_name}.json"


def load_session(session_id: str, session_dir: str | Path | None = None) -> dict[str, Any] | None:
    """Load session data by identifier."""
    sdir = get_session_dir(session_dir)
    file_path = _session_file(session_id, sdir)
    if not file_path.is_file():
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        return None
    return None


def save_session(session_data: dict[str, Any], session_dir: str | Path | None = None) -> Path:
    """Persist session data atomically to disk."""
    session_id = str(session_data.get("session_id", "")).strip()
    if not session_id:
        raise ValueError("session_data must contain a non-empty 'session_id'")

    sdir = get_session_dir(session_dir)
    file_path = _session_file(session_id, sdir)
    tmp_path = file_path.with_suffix(".tmp")

    session_data["updated_at"] = time.time()
    payload = json.dumps(session_data, indent=2, sort_keys=True)
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(file_path)
    return file_path


def list_sessions(session_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Return all valid sessions found in the session storage directory."""
    sdir = get_session_dir(session_dir)
    results: list[dict[str, Any]] = []
    for file_path in sorted(sdir.glob("*.json")):
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "session_id" in data:
                results.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return results


def record_command(
    session_id: str,
    pid: int,
    pgid: int,
    cmd: list[str] | str,
    cwd: str | None = None,
    session_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Register a spawned command under the given session."""
    sdir = get_session_dir(session_dir)
    data = load_session(session_id, sdir)
    now = time.time()
    if data is None:
        data = {
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
            "commands": [],
        }

    cmd_list = cmd if isinstance(cmd, list) else [cmd]
    entry = {
        "pid": int(pid),
        "pgid": int(pgid),
        "cmd": cmd_list,
        "cwd": cwd or os.getcwd(),
        "start_time": now,
        "status": "running",
        "exit_code": None,
    }
    data.setdefault("commands", []).append(entry)
    save_session(data, sdir)
    return entry


def update_command_status(
    session_id: str,
    pid: int,
    status: str,
    exit_code: int | None = None,
    session_dir: str | Path | None = None,
) -> bool:
    """Update status and exit code for a recorded command."""
    sdir = get_session_dir(session_dir)
    data = load_session(session_id, sdir)
    if data is None:
        return False

    updated = False
    for cmd in data.get("commands", []):
        if cmd.get("pid") == pid:
            cmd["status"] = status
            if exit_code is not None:
                cmd["exit_code"] = exit_code
            updated = True
            break

    if updated:
        save_session(data, sdir)
    return updated


def delete_session(session_id: str, session_dir: str | Path | None = None) -> bool:
    """Remove a session record file."""
    sdir = get_session_dir(session_dir)
    file_path = _session_file(session_id, sdir)
    if file_path.exists():
        try:
            file_path.unlink()
            return True
        except OSError:
            return False
    return False


def prune_stale_sessions(
    max_age_seconds: float = 86400.0,
    session_dir: str | Path | None = None,
) -> list[str]:
    """Remove session records older than max_age_seconds."""
    sdir = get_session_dir(session_dir)
    now = time.time()
    pruned: list[str] = []
    for sess in list_sessions(sdir):
        updated = sess.get("updated_at", sess.get("created_at", 0))
        if now - updated > max_age_seconds:
            sid = sess["session_id"]
            if delete_session(sid, sdir):
                pruned.append(sid)
    return pruned
