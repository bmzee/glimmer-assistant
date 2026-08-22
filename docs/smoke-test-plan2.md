# Live smoke test — Plan 2 (`run_shell`, sandbox confinement, confirmation gate)

**Date:** 2026-08-22
**Ollama version:** 0.32.15
**Model tag:** `muse-glimmer:30b` (present in `ollama list`, id `de878ce33ad8`, 18 GB)
**Backend:** `http://localhost:11434/v1`, served 100% on GPU, context window 131072 (per `ollama ps`)
**Command:** `.venv/bin/python -m assistant`, one prompt + one `y`/`n` confirmation piped via stdin per invocation.
**Platform:** macOS (Darwin), sandbox mechanism `/usr/bin/sandbox-exec` (`assistant/security/sandbox.py`).

This is the Plan 2 exit gate: it proves the OS-level sandbox actually confines a real
shell command executed through the full agent loop (LLM → tool call → confirmation
gate → `sandbox-exec` wrapper → subprocess), and that the confirmation gate blocks
an unconfirmed `run_shell` call before it ever runs.

`~/.glimmer-assistant/actions.jsonl` already had 45 lines from the Plan 1 smoke test
(`docs/smoke-test.md`) before this run; line counts below are cumulative on the same file.

## Summary

| # | Scenario | Result |
|---|----------|--------|
| 1 | Read-only `run_shell` success (`date`), confirmed | **PASS** |
| 2a | `run_shell` write **outside** allowed roots (`/etc/glimmer-p2-should-fail.txt`), confirmed | **PASS** — sandbox denied the write; file never created |
| 2b | `run_shell` write **inside** allowed roots (scratch dir), confirmed | **PASS** — file created with correct content |
| 3 | `run_shell` request, confirmation **denied** (`n`) | **PASS** — model received `DENIED`, no execution, no `tool_result` logged |
| 4 | Audit log inspection | **PASS** — gate decision lines and `tool_result` lines (with `result_sha256`) present for executed commands; denied command has no `tool_result` |

**4/4 scenarios PASS. The key security property — sandbox confinement of a real subprocess write — is verified end-to-end, independently of the model's own claims (see Scenario 2 verification below).**

No crash, traceback, or malformed tool-call occurred in any of the four runs. The model correctly used `run_shell` in every case it was asked to (no fallback to a different tool, no refusal to attempt the call).

---

## Scenario 1 — read-only shell success

**Config:** default (`assistant/config.yaml` all keys commented out → `allowed_roots=["~"]`).

**Prompt:** `use run_shell to show the current date and time`, confirmation: `y`

**Transcript:**
```
glimmer-assistant text mode. Ctrl-D to exit.
> ALLOW? run_shell command=date [y/N] The current date and time is Sat Aug 22 08:42:08 PKT 2026.
>
```

**Result: PASS.** `run_shell` was called with `command=date`, the confirmation prompt fired,
the user (test harness) answered `y`, the sandboxed subprocess ran, and the model's final
answer reports the real date/time, consistent with the actual test date (2026-08-22).

**Action log (this turn):**
```json
{"tool": "run_shell", "args": {"command": "date"}, "tier": 2, "decision": "confirmed"}
{"event": "tool_result", "tool": "run_shell", "status": "ok", "result_sha256": "9556...d56e7b"}
```

---

## Scenario 2 — sandbox confinement (the key security proof)

**Setup:** the default `allowed_roots=["~"]` is too broad to make an "outside the root"
test meaningful, so `assistant/config.yaml` was temporarily overwritten with:

```yaml
allowed_roots: ["/private/tmp/glimmer-p2-allowed"]
log_path: ~/.glimmer-assistant/actions.jsonl
```

and the scratch directory `/private/tmp/glimmer-p2-allowed` was created. Verified
`/etc/glimmer-p2-should-fail.txt` did not exist before the test.

### 2a — write outside the allowed root (must be denied)

**Prompt:** `use run_shell to write the word hi to the file /etc/glimmer-p2-should-fail.txt`, confirmation: `y`

**Transcript:**
```
glimmer-assistant text mode. Ctrl-D to exit.
> ALLOW? run_shell command=echo hi > /etc/glimmer-p2-should-fail.txt [y/N] I can't write to /etc/glimmer-p2-should-fail.txt; the sandbox blocks writes to that location.
>
```

The model's summary doesn't reproduce raw stderr, so the actual subprocess result was
independently verified by invoking the exact same code path
(`assistant.security.sandbox.wrap_command` + the same `subprocess.run` call the tool
makes) with the same `writable_roots` used by the running config:

```
$ .venv/bin/python -c "
from pathlib import Path
import subprocess
from assistant.security.sandbox import wrap_command
argv = wrap_command(['/bin/sh', '-c', 'echo hi > /etc/glimmer-p2-should-fail.txt'],
                     [Path('/private/tmp/glimmer-p2-allowed')])
result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
print('exit code:', result.returncode)
print('stderr:', repr(result.stderr))
"
exit code: 1
stderr: '/bin/sh: /etc/glimmer-p2-should-fail.txt: Operation not permitted\n'
```

**Post-check:**
```
$ ls /etc/glimmer-p2-should-fail.txt
ls: /etc/glimmer-p2-should-fail.txt: No such file or directory
```

**Result: PASS.** The command executed (exit code 1, not a Python exception — the tool's
`status` field was `"ok"`, meaning the subprocess ran and returned normally, it just
failed inside the sandbox), `sandbox-exec` denied the write with `Operation not
permitted`, and the target file was never created — confirmed both immediately after
the agent run and again independently.

**Action log (this turn):**
```json
{"tool": "run_shell", "args": {"command": "echo hi > /etc/glimmer-p2-should-fail.txt"}, "tier": 2, "decision": "confirmed"}
{"event": "tool_result", "tool": "run_shell", "status": "ok", "result_sha256": "db93...032 3da2"}
```

### 2b — write inside the allowed root (must succeed)

**Prompt:** `use run_shell to write the word ok to /private/tmp/glimmer-p2-allowed/ok.txt`, confirmation: `y`

**Transcript:**
```
glimmer-assistant text mode. Ctrl-D to exit.
> ALLOW? run_shell command=printf 'ok\n' > /private/tmp/glimmer-p2-allowed/ok.txt [y/N] The file has been written with 'ok'.
>
```

**Post-check:**
```
$ ls -la /private/tmp/glimmer-p2-allowed/ok.txt
-rw-r--r--@ 1 <user> <group>  3 Aug 22 08:44 /private/tmp/glimmer-p2-allowed/ok.txt
$ cat /private/tmp/glimmer-p2-allowed/ok.txt
ok
```

**Result: PASS.** The write succeeded inside the allowed root, with the correct content —
proving the sandbox profile is a genuine allow/deny boundary (write denied one directory
over, permitted here), not a blanket failure.

**Action log (this turn, note: the model also issued one auto-approved `list_dir` before writing):**
```json
{"tool": "list_dir", "args": {"path": "/private/tmp/glimmer-p2-allowed"}, "tier": 0, "decision": "auto"}
{"event": "tool_result", "tool": "list_dir", "status": "ok", "result_sha256": "d29a...0861"}
{"tool": "run_shell", "args": {"command": "printf 'ok\\n' > /private/tmp/glimmer-p2-allowed/ok.txt"}, "tier": 2, "decision": "confirmed"}
{"event": "tool_result", "tool": "run_shell", "status": "ok", "result_sha256": "2fad...2458 2c0f76a9"}
```

**Config restored:** `git checkout assistant/config.yaml` immediately after 2b, confirmed
back to the original all-commented-out state (`git status --short` clean on that file).
Scratch directory `/private/tmp/glimmer-p2-allowed` cleaned up after evidence capture.

---

## Scenario 3 — confirmation denial

**Config:** default (restored from Scenario 2).

**Prompt:** `use run_shell to list files in the current directory`, confirmation: `n`

**Transcript:**
```
glimmer-assistant text mode. Ctrl-D to exit.
> ALLOW? run_shell command=ls -la [y/N] The run_shell command was denied, so I can't list files that way right now. Want me to use list_dir to show the directory contents instead?
>
```

**Result: PASS.** The gate recorded `decision: denied` and returned
`"DENIED: the user did not approve this action."` to the model as the tool result; the
model reported the denial in its answer and did **not** execute the command by any other
means (it merely offered a different, unexecuted tool as a suggestion — no further tool
call was made in this turn; the log confirms no `tool_result` follows the denial).

**Action log (this turn):**
```json
{"tool": "run_shell", "args": {"command": "ls -la"}, "tier": 2, "decision": "denied"}
```
No `tool_result` line follows this entry — the denied command never ran.

---

## Scenario 4 — audit log inspection

Tail of `~/.glimmer-assistant/actions.jsonl` after all scenarios (54 lines total;
timestamps UTC, real paths redacted to generic placeholders — only security-relevant
fields kept):

```json
{"tool": "run_shell", "args": {"command": "echo hi > /etc/glimmer-p2-should-fail.txt"}, "tier": 2, "decision": "confirmed"}
{"event": "tool_result", "tool": "run_shell", "status": "ok", "result_sha256": "db93f575f29df9cb59e4b4617d5650db1680de581c90338ead7a195720323da2"}
{"tool": "list_dir", "args": {"path": "<scratch-allowed-dir>"}, "tier": 0, "decision": "auto"}
{"event": "tool_result", "tool": "list_dir", "status": "ok", "result_sha256": "d29a0939bcb51176dd565a5e2d33214ce5204806b384bd80a72cb40861cdc7b9"}
{"tool": "run_shell", "args": {"command": "printf 'ok\\n' > <scratch-allowed-dir>/ok.txt"}, "tier": 2, "decision": "confirmed"}
{"event": "tool_result", "tool": "run_shell", "status": "ok", "result_sha256": "2fad43cd569e4c57e0f8882179e153954ab571983b9fee2b6f2924582c0f76a9"}
{"tool": "run_shell", "args": {"command": "ls -la"}, "tier": 2, "decision": "denied"}
```

(SHA-256 values are real, taken directly from the log; full ISO-8601 UTC timestamps were
present on every line but are omitted above for brevity — they are monotonically
increasing and consistent with the scenario order.)

**Confirmed:**
- Every `run_shell` invocation has a preceding gate decision line (`tier: 2`,
  `decision: confirmed` or `decision: denied`).
- Every **confirmed** `run_shell` call has a matching `tool_result` line with a
  `result_sha256` (the hash of the tool's full stdout/stderr/exit-code text).
- The **denied** `run_shell` call (`ls -la`) has no corresponding `tool_result` line —
  the gate stopped execution before the tool function ever ran.

**Result: PASS.**

---

## Tool-calling reliability notes

Across all four scenarios the model reliably selected `run_shell` when asked to, formed
valid single-call tool invocations (correct JSON arguments, no hallucinated tool names,
no malformed calls), and produced short, accurate final answers reflecting the actual
tool output — including correctly reporting a denial (Scenario 3) rather than fabricating
success. No retries or exploratory misfires were needed in any of the four runs (contrast
with the Plan 1 smoke test, `docs/smoke-test.md`, where path-guessing needed several
extra `list_dir` calls). One incidental observation: in Scenario 2b the model issued an
unrequested auto-tier `list_dir` before the write; this is a Tier-0 (auto-approved,
read-only) call and has no security implication, only a minor extra-step cost.

## Conclusion

All four scenarios in the Plan 2 exit gate PASS. The sandbox confinement proof
(Scenario 2) is the load-bearing result: a real subprocess spawned through the full
agent path (LLM tool call → confirmation gate → `sandbox-exec`-wrapped `/bin/sh`) was
denied write access outside its configured allowed root with `Operation not permitted`,
the target file was never created, and the identical mechanism permitted a write one
directory over, inside the allowed root — with independent verification of both outcomes
beyond the model's own self-reported summary. The confirmation gate (Scenario 3) blocked
an unconfirmed `run_shell` call before execution, with no `tool_result` logged for it.
