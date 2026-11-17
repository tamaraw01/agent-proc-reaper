# agent-proc-reaper

Session-scoped process tree supervisor and reaper for AI agent environments.

Zero dependencies. Requires Python 3.11 or newer.

## Packaged Releases

- Packaged ZIP release ($0+ MIT): [Download agent-proc-reaper on Gumroad](https://aditama1.gumroad.com/l/agent-proc-reaper)
- Full automation kit, hooks, Windows supervisor, and CI leak gates: [Agent Process Hygiene Kit ($29 / $59 / $129)](https://aditama1.gumroad.com/l/agent-proc-kit) (use code `REAP20` for 20% off Pro `$59` or Team `$129`)

| Tier | Price | What Is Included |
|---|---:|---|
| **[agent-proc-reaper](https://aditama1.gumroad.com/l/agent-proc-reaper)** | **$0+** | This MIT CLI (`list`, `tree`, `kill`, `run`, `doctor`) as a standalone tool |
| **[Starter](https://aditama1.gumroad.com/l/agent-proc-kit)** | **$29** | Bundled CLI, Claude Code PostToolUse/Stop hooks, tree-kill timeout runner with Linux subreaper, troubleshooting guide |
| **[Pro (Recommended)](https://aditama1.gumroad.com/l/agent-proc-kit)** | **$59** | Everything in Starter plus Windows Job Object supervisor, MCP leak watcher, port release checker ($47.20 with `REAP20`) |
| **[Team & CI](https://aditama1.gumroad.com/l/agent-proc-kit)** | **$129** | Everything in Pro plus CI leak detection step (GitHub Actions / GitLab CI), Linux cgroup v2 container reaper, 5-seat license ($103.20 with `REAP20`) |

Every paid tier includes a 14-day refund policy.

## Why this exists

AI coding agents (Claude Code, OpenAI Codex, subagent pipelines) frequently execute shell commands. Standard terminal timeouts signal only the direct parent shell. When a tool call times out or stops, background jobs, `setsid` sessions, and double-forked worker processes often continue running in the background.

Common scripts run `pkill -f` or kill arbitrary `PPID=1` processes, which risks killing unrelated developer tasks. `agent-proc-reaper` solves this by tracking explicit session ownership:

1. Commands are registered with their PID, PGID, and session identifier in `~/.agent-proc-reaper/sessions/<session_id>.json`.
2. The tree walker inspects Linux `/proc` or POSIX `ps` to find all active child and grandchild processes belonging to that session.
3. The kill command defaults to a safe dry run. When confirmed with `--force`, it signals the tracked process groups and child PIDs (SIGTERM, grace period, then SIGKILL).
4. System processes, init (PID 1), and the runner itself are protected by guard checks.

## Quick Start

### Install

Install from source or copy into your environment:

```bash
pip install .
```

Or run directly without installation:

```bash
PYTHONPATH=src python3 -m agent_proc_reaper.cli --help
```

### 1. Run a command under session tracking

```bash
agent-proc-reaper run --session dev-task-1 -- bash -c 'sleep 300 & python worker.py'
```

### 2. Audit running commands in this session

Answers claude-code issue #108592: read-only list of active processes owned by the session.

```bash
agent-proc-reaper list --session dev-task-1
```

For JSON output:

```bash
agent-proc-reaper list --format json
```

### 3. View the process hierarchy tree

```bash
agent-proc-reaper tree --session dev-task-1
```

Example output:

```text
Session dev-task-1:
  |-- 81024 (ppid=81010, pgid=81024) bash -c sleep 300 & python worker.py
      |-- 81025 (ppid=81024, pgid=81024) sleep 300
      `-- 81026 (ppid=81024, pgid=81024, 24MB RSS) python worker.py
```

### 4. Reaping leftover processes

By default, `kill` runs in safe dry-run mode and prints what would be terminated:

```bash
agent-proc-reaper kill --session dev-task-1
```

To execute termination:

```bash
agent-proc-reaper kill --session dev-task-1 --force
```

### 5. Check environment diagnostics

```bash
agent-proc-reaper doctor
```

## Anti-Slop Guarantee

- Zero external pip dependencies (standard library Python 3.11+).
- Zero pattern matching by arbitrary process names.
- Zero termination of processes outside the tracked session tree.
- Safe dry run by default on all reap commands.
