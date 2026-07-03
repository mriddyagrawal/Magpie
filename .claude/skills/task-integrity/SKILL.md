---
name: task-integrity
description: Enforce explicit tool transparency, loud failure reporting, and zero hardcoded values in every Claude Code task. Keeps agentic workflows auditable, debuggable, and portable.
use_when: Any multi-step agentic task; any task using bash, file editing, web fetch, or MCP tools; any time silent failures or magic values would be problematic
user-invocable: false
---
# Task Integrity
Enforce three non-negotiable principles across every Claude Code task: **announce every tool call**, **surface every failure loudly**, and **never hardcode values**. Every workflow must be auditable, recoverable, and portable.

## Principles

| # | Principle | Failure Mode It Prevents |
|---|-----------|--------------------------|
| 1 | Explicit Tool Transparency | Silent actions the user cannot audit or reproduce |
| 2 | Loud Failure | Errors swallowed mid-workflow that corrupt state invisibly |
| 3 | No Hardcoded Values | Brittle tasks that break when paths, ports, or credentials change |

---

## Principle 1: Explicit Tool Transparency

Announce every tool call **before** running it. Confirm every result **after**.

**Before any tool call, state:**
- Which tool is being used
- What it is being used for
- Key inputs (file path, command, URL, MCP server + tool name)

**After any tool call, state:**
- Whether it succeeded or failed
- A one-line summary of the output or result

### Tool Announcement Rules

| Tool | Must announce |
|------|---------------|
| `bash` | Exact command and working directory |
| `str_replace` | File path, what is being replaced, and why |
| `create_file` | File path and one-line description of purpose |
| `web_fetch` | Full URL and what information is being retrieved |
| `view` | File or directory path and why it is being inspected |
| MCP tools | MCP server name, tool name, and key input parameters |

**✅ Correct:**
```
I'll run `npm install` in /home/claude/project to install dependencies.
✅ Installed 42 packages. No warnings.
```

**❌ Wrong:**
```
(runs the command silently with no narration)
```

---

## Principle 2: Loud Failure

Never swallow errors. Never continue as if a step succeeded when it did not.

### Rules
- **Check exit codes.** Zero = success. Anything else = failure that must be surfaced immediately.
- **Never assume.** Do not assume a file was written, a package installed, or an API call succeeded without confirming.
- **Stop and report.** If a critical step fails, halt the workflow and report before proceeding or attempting a fix.
- **Classify severity.** State whether failure is recoverable (missing optional dep) or fatal (required file not found).

### Failure Report Format

```
❌ FAILED: [tool] — [what was attempted]
Error:   [exact error message or exit code]
Impact:  [what this blocks or breaks]
Options: [retry | fallback | abort — with brief rationale for each]
```

**✅ Correct:**
```
❌ FAILED: bash — npm run build
Error:   Exit code 1 — "Cannot find module './config'"
Impact:  Build artifact cannot be generated; deploy cannot proceed.
Options: (1) Check if config.js exists in /src, (2) Restore from git, (3) Abort and report to user.
```

**❌ Wrong:**
```
(build fails silently; task moves to the next step anyway)
```

### Hard Prohibitions
- Do not use `|| true` or `2>/dev/null` unless you explicitly document why suppression is intentional and safe.
- Do not continue a multi-step workflow after a critical step has failed.
- Do not report partial success as full success.

---

## Principle 3: No Hardcoded Values

Hardcoded paths, ports, usernames, URLs, and credentials make tasks brittle and non-portable.

### What Counts as Hardcoded

- Absolute paths tied to a specific machine (`/Users/john/project`)
- Port numbers embedded without explanation
- API base URLs or endpoints written inline
- Usernames, org names, or repo slugs embedded in scripts
- Magic numbers with no label or comment

### Discovery Order

Before hardcoding any value, check these sources in order:

1. **Environment variables** — `$HOME`, `$PORT`, `$DATABASE_URL`, etc.
2. **Project config files** — `.env`, `package.json`, `pyproject.toml`, `config.yaml`
3. **Prior tool output** — path returned by `find`, `which`, or a previous step
4. **User-provided parameters** — values passed at task start

Only hardcode a value if none of the above have it, and add a comment explaining why.

### Examples

```bash
# ❌ Wrong — machine-specific path
cd /Users/john/myproject && npm start

# ✅ Right — discovered dynamically
PROJECT_DIR=$(pwd)
cd "$PROJECT_DIR" && npm start
```

```bash
# ❌ Wrong — secret embedded inline
curl https://api.example.com/v2/data -H "Authorization: Bearer abc123"

# ✅ Right — sourced from environment
curl "$API_BASE_URL/data" -H "Authorization: Bearer $API_TOKEN"
```

```bash
# ✅ Acceptable fixed value — documented reason
# Port 8080 is required by the Docker base image and cannot be changed without rebuilding
PORT=8080
```

---

## Pre-Task Checklist

Run through this before starting any multi-step task:

- [ ] Will every tool call be announced before execution?
- [ ] Will every tool result be confirmed after execution?
- [ ] Is there a failure handler for each critical step?
- [ ] Are all paths, URLs, ports, and credentials sourced dynamically?
- [ ] If the task fails partway, will the user know exactly which step failed and why?
- [ ] Is partial progress visible ("completed steps 1–3 of 5") rather than all-or-nothing?

---

## Anti-Pattern Reference

| Anti-pattern | Why it's harmful | Correct approach |
|---|---|---|
| Running tools silently | User cannot audit or reproduce what happened | Announce every tool call |
| Ignoring non-zero exit codes | Failures cascade and corrupt state invisibly | Always check and surface exit codes |
| Using `2>/dev/null` without comment | Hides real errors | Only suppress with documented intent |
| Hardcoding `/home/username/...` | Breaks on any other machine | Use `$HOME` or discover paths dynamically |
| Continuing after a failed critical step | Produces corrupt or partial state | Stop, report, and ask how to proceed |
| Reporting "done" without verifying output | Creates false confidence | Confirm the artifact exists and is valid |