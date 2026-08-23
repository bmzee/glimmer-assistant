# Adversarial hardening audit

**Date:** 2026-08-23 · **Method:** 12 independent red-teamers per control surface,
every finding then subjected to two independent refutation attempts; only findings
that survived **unanimous** refutation were acted on.

Attacker position assumed: control of web page content, email bodies, file contents,
calendar text, and MCP responses — **not** the user's typed or spoken request.

## Outcome

8 raw findings → 5 killed by refutation → **4 confirmed and fixed**, plus one
systemic finding and one documentation error.

| # | Finding | Severity | Fix | Re-attack |
|---|---|---|---|---|
| 1 | `list_dir` not `untrusted`, so filenames never taint the session | high | `untrusted=True` | ✅ holds |
| 2 | `screenshot` was an AUTO-tier arbitrary-write primitive | high | `.png` only, no overwrite, confined to a capture dir, audit log protected | ✅ holds |
| 3 | `open_path` executed code outside the sandbox at an auto-approved tier | high | CONFIRM + deny-by-default type allowlist | ⚠️ needed a second fix |
| 4 | Confirmation preview passed Unicode bidi/invisible characters | medium | NFKC + strip bidi, zero-width, separators | ✅ holds |

### 1 — `list_dir` laundered attacker-controlled filenames

`datamark()` and `note_untrusted_ingest()` run only under `if tool.untrusted:`
(`loop.py:130-133`). `list_dir` lacked the flag, so a filename encoding an
instruction entered the planning context undatamarked *and* left `SessionTrust`
clean — meaning the Rule-of-Two elevation never fired and a subsequent
`read_page` exfiltration ran unconfirmed. Delivery needs only one file under `~`
(a saved attachment, a download, a cloned repo).

The same reasoning had already been applied to window titles (`system.py:83-86`);
filenames are the identical metadata-laundering vector and were missed.

### 2 — `screenshot` could overwrite the audit log

Tiered AUTO because §8.3 lists screenshot as read-only — but it takes a
**model-supplied write path**. Default `allowed_roots=["~"]` and default
`log_path=~/.glimmer-assistant/actions.jsonl` are both under `~`, so injected
content could aim `screencapture` at the audit log and destroy every prior record,
or silently clobber a user document.

Now: `.png` suffix required, existing files never overwritten, captures confined to
a dedicated folder, and an explicit denylist protecting `~/.glimmer-assistant` —
with the configured `log_path` wired into that denylist from `build_loop`.

### 3 — `open_path`: two rounds, because the first fix was bypassable

`open_path` was Tier 1 (auto-approved, see below) and `MacAdapter.open_path` runs
`open <path>` with **no sandbox wrap** — only `run_shell` is sandboxed. macOS `open`
*executes* `.command`/`.app`/`.workflow`. A `git clone` sets no quarantine attribute,
so Gatekeeper never prompts.

The first fix promoted it to CONFIRM and added an eight-entry **blocklist** of
executing extensions. **The re-attack walked around it.** `.terminal` is an ordinary
plist with no execute bit and was not on the list; Terminal.app runs its
`CommandString` on open. The agent demonstrated real code execution through the
shipped tool, not a simulation.

The defect was structural: a blocklist permits every type nobody enumerated, and
that set (`.terminal`, `.webloc`, `.pkg`, `.inetloc`, `.url`, `.mpkg`, `.dmg`, …)
cannot be completed by hand or kept current across macOS releases.

Now inverted to **deny-by-default** — an allowlist of inert document types, matching
the posture the SBPL profile already uses. This also closed two gaps the blocklist
shape had hidden: bundle-shaped *directories* (the executable-bit check skips
directories, since `+x` there only means traversal) and extensionless files (a
Mach-O binary has no suffix).

### 4 — Confirmation previews could be visually spoofed

`sanitize_preview` stripped ANSI and C0/C1 controls; its regexes stopped at U+009F.
U+202E (RLO), U+2066–2069, U+200B–200D, U+2028/2029 passed through into the text the
user reads before approving. Since execution uses the raw args, a poisoned preview
can render a different recipient than the one that sends. This defeats both the
CONFIRM checkpoint and the Rule-of-Two ELEVATED banner, as both render through this
function.

Over-stripping is its own failure mode — an unreadable preview stops being read — so
ordinary accented, CJK, and emoji text is explicitly tested to survive.

## The systemic finding

Three of four vulnerabilities share one root cause: **the gate and quarantine are
correct, but driven entirely by per-tool flags**, and tools were under-tagged
relative to what they actually do. `list_dir` not `untrusted`; `screenshot` tiered
read-only when it writes; `open_path` tiered undoable when it executes.

The registry invariant test now asserts capability-derived rules — write-capable
tools must be ≥CONFIRM, externally-influenced results must be `untrusted`,
execution-capable tools must be ≥CONFIRM — each proven to fail against the original
code.

## A documentation error this exposed

`docs/spec-coverage.md` previously stated the Tier-1 undo gap was *"latent: no tool
is Tier 1 today."* **That was false.** `gate.py:33` prompts only on
`CONFIRM or elevated`, so Tier 1 auto-approves, and four tools sit there.

## What held under attack

Not findings — these were attacked and stopped the attacker. Listed so this document
is not mistaken for a complete failure list.

- **SBPL injection and sandbox egress** — `build_profile` rejects `"`, `\`, newline in
  roots; profile is `deny default` with no network allow; every `run_shell` command is
  wrapped.
- **Datamark forgery** — the closing tag carries an unguessable per-call nonce; the
  `source` attribute is escaped against breakout.
- **MCP registration-time injection** — server descriptions control-stripped and
  length-capped, tool names grammar-checked, MCP tools default to `untrusted` + CONFIRM.
- **Outbound classification** — every mail/calendar/web send and `fill_form_field`
  carries CONFIRM + `outbound=True`.
- **Path traversal out of roots** — `resolve_safe` resolves symlinks before the
  ancestor check.
- **NEVER tier** — hard-refused before elevation is even computed.

## Residual risk

1. **Tier 1 still auto-approves.** `open_app`, `focus_window`, `set_volume`, `open_url`
   execute with no confirmation and no undo. The dangerous tools were promoted out of
   Tier 1 rather than building the undo window the spec calls for.
2. ~~The screenshot denylist protects the audit log from `screenshot` only. Other
   write-capable tools can still address paths anywhere under `allowed_roots`.~~
   **Overstated — corrected 2026-08-23.** There is no `write_file` tool: the file
   tools are `list_dir` and `read_file` only. The sole model-reachable writers are
   `screenshot` (confined to the capture folder, with the denylist) and `run_shell`
   (CONFIRM tier, sandbox-wrapped, requires explicit approval). The gap the denylist
   was written for does not extend beyond the tool it already covers.
3. **MCP definition pinning** (§8.4) remains unimplemented — latent while no server is
   adopted.

## Usability cost introduced

- Any `list_dir` call now taints the session, so a later web tool requires confirmation
  even when the directory held only benign files. This is the intended Rule-of-Two cost.
- Screenshots save only into the capture folder, and repeated captures need fresh names.
- `open_path` refuses unrecognised file types. Extending `_SAFE_DOCUMENT_SUFFIXES` is
  the intended way to broaden it — deliberately a decision, not a default.
