# Changelog

All notable changes to `agent-proc-reaper` are documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [1.0.0] - 2026-11-12

### Added
- Standard library Python CLI with zero external package dependencies.
- Session registry in `~/.agent-proc-reaper/sessions/` with JSON state persistence.
- `list` subcommand: read-only audit of session-spawned commands and active child processes (resolves claude-code #108592).
- `tree` subcommand: hierarchical ASCII visualization of session process trees.
- `kill` subcommand: dry-run default process termination engine with `--force` escalation (SIGTERM then grace period then SIGKILL).
- `run` subcommand: command execution wrapper that registers PID and PGID into the session file and passes `AGENT_SESSION_ID` to child environment.
- `doctor` subcommand: host diagnostic checking Python version, `/proc` availability, and Linux `PR_SET_CHILD_SUBREAPER` capabilities.
- Linux `/proc` direct inspection parser and macOS/BSD `ps` fallback parser.
- Comprehensive unit test suite with 21 tests covering session storage, process tree discovery, reaper guards, and CLI commands.
