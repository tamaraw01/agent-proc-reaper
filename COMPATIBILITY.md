# Compatibility Matrix

## Supported Platforms

| Platform | Support Tier | Process Tree Discovery | Session Scoping | Termination Mechanism | Notes |
|---|---|---|---|---|---|
| Linux (Kernel 3.4+) | Tier 1 (Full) | Native `/proc` parser | File record + `AGENT_SESSION_ID` env | `killpg` + PID SIGTERM/SIGKILL | Full subreaper support via `PR_SET_CHILD_SUBREAPER` |
| macOS (12+) | Tier 1 (Full) | POSIX `ps -axo` parser | File record + `AGENT_SESSION_ID` env | `killpg` + PID SIGTERM/SIGKILL | Uses system `ps` command |
| Windows (10/11, Server) | Tier 2 (Audit) | Fallback process list | File record | Manual or taskkill fallback | Pro tier includes native Windows Job Object supervisor |

## Python Runtime Requirements

- Python 3.11 or newer (Python 3.11, 3.12, and 3.13 tested).
- Zero third-party dependencies (100% Python standard library).
- No external C-extensions required.

## Tested Agent Environments

- Claude Code (anthropics/claude-code): verified against issues #108551, #108592, #93794, #90672, #96625, #93126.
- OpenAI Codex CLI / Desktop: verified process scoping and leak identification.
- Custom subagent subprocess pipelines: verified against `setsid` and double-fork orphan escapes.
