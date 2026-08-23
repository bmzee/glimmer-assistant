# Packaging: giving the assistant its own permissions

## The problem

macOS attributes Automation, Microphone and Screen Recording consent to the
**responsible process** — whatever launched the code, not the code itself.

Run `python -m assistant` from a terminal and every grant attaches to *that
terminal*. During development this meant the assistant was operating on
permissions granted to Claude Code. Two things are wrong with that:

1. **It doesn't work in production.** Ship the assistant and it has no
   permissions of its own; it inherits whatever launched it, or nothing.
2. **The user cannot reason about it.** They can't grant, review, or revoke
   permissions for "Glimmer Assistant" because macOS has never seen such a
   thing. The entry in System Settings says *Claude* — or *Terminal* — which
   is misleading about what is actually reading their mail.

## The fix

A `.app` bundle with its own `CFBundleIdentifier`. Launched via `open`, macOS
hands the process to **launchd**, giving it an identity independent of whatever
ran the build.

```bash
python -m appbundle.build_app --python "$(pwd)/.venv/bin/python"
open "dist/Glimmer Assistant.app"
```

Then grant permissions under **System Settings → Privacy & Security**:
Microphone, Automation (per target app), and Screen Recording if you want
`screenshot` to work.

## Verified, not assumed

Bundle layout and `Info.plist` keys are unit-tested (11 tests), but no unit
test can prove TCC attribution. That was checked live:

| Check | Result |
|---|---|
| Code identity | `Identifier=com.glimmer.assistant` |
| Signature | ad-hoc, `codesign --verify --strict` passes |
| Bundle type | `com.apple.application-bundle` |
| **Process parent after `open`** | **`ppid=1` — launchd, not the shell** |

That last row is the one that matters. A launchd-parented, signed bundle is
what macOS binds grants to. Verified by launching the *same* generated launcher
with a long-lived, side-effect-free payload, because the real bundle either
exits instantly (text mode has no stdin under `LSUIElement`) or raises a
microphone dialog (voice mode).

## Design notes

- **`exec` in the launcher.** The shell script `exec`s the interpreter rather
  than spawning it. A child process would hand the TCC identity back to the
  shell, defeating the entire exercise.
- **Ad-hoc signing.** Unsigned bundles have their grants invalidated whenever
  the executable changes, which surfaces as permissions mysteriously needing
  to be re-granted. Ad-hoc is sufficient locally; distribution would need a
  Developer ID signature.
- **`LSUIElement: true`.** A push-to-talk assistant should not own a Dock icon
  or steal focus at launch.
- **Usage strings say *why*.** They are shown verbatim in the consent dialog
  and are the only context the user gets. A test enforces they are longer than
  40 characters, because "Needs microphone access" is not informed consent.
- **Module named `appbundle`, not `packaging`.** `packaging` is a real PyPI
  distribution already installed as a pytest/setuptools dependency; a local
  module of that name would shadow it.

## Two builders

`appbundle/build_app.py` writes a **launcher** — a shell script that `exec`s
your dev venv. Fast to build, but it stops working the moment that venv moves,
and it is not something you can hand to anyone. Useful during development.

`appbundle/build_dist.py` writes a **self-contained app**: embedded Python and
every dependency, ~1.24 GB, draggable to `/Applications` and runnable on a
machine that has never seen this repo.

```bash
python -m appbundle.build_dist --dmg
```

Produces `dist/Glimmer Assistant.app` and a **0.31 GB `.dmg`** with a
drag-to-Applications symlink.

### What is still not bundled, and why

- **Ollama and its model.** The model alone is ~18 GB and Ollama is its own
  app. No bundler solves that. `assistant/preflight.py` detects it and says so.
- **Voice models (~1 GB)** — downloaded to `~/.cache` on first use, by design.
- **Playwright's Chromium (~150 MB)** — lives in `~/Library/Caches`.

### Two failures worth recording

**`--options runtime` makes the app unlaunchable.** Hardened runtime enables
library validation; a PyInstaller bundle loads an embedded `Python.framework`
signed separately, and two independently ad-hoc-signed binaries share no Team
ID to match on:

```
Failed to load Python shared library ... Contents/Frameworks/Python
... (non-platform) have different Team IDs
```

The app exits 255 before running a line of Python. Hardened runtime is only a
*notarization* requirement, and notarization needs a Developer ID an ad-hoc
build does not have — so the flag bought nothing and broke everything. A test
guards against re-adding it.

**`language_tags` and `segments` must be collected explicitly.** They are
data-only transitive deps of `phonemizer`. Without them the frozen app raises a
`FileNotFoundError` naming *neither* package — it reads like an espeak failure
and sends you hunting the wrong dylib. The symptom was three packages away from
the cause.

## Startup, when nothing can be printed

`LSUIElement` means no Dock icon and a bundle has no terminal, so every
`print()` goes nowhere: a missing Ollama, an unpulled model and a crash all
look identical — the app appears to do nothing.

`assistant/preflight.py` turns each into a named problem with a remedy, shown
in a dialog via `osascript`. Blocking problems (no Ollama, no model) stop
startup; warnings (voice models that will download themselves) do not. Crashes
and tracebacks go to `~/.glimmer-assistant/app.log`.

## Known limitations

- **Not notarized.** Ad-hoc signing works on the machine that built it. Handing
  the `.dmg` to someone else triggers a Gatekeeper warning; clearing that needs
  a Developer ID certificate ($99/yr Apple Developer account) plus
  `notarytool` submission. Only then should `--options runtime` be re-added.
- **Single architecture.** Built arm64-only, matching the host.
- **Screen Recording has no `Info.plist` key.** Unlike Microphone and Apple
  Events, it is granted only on first use. `screenshot` maps the resulting
  opaque `could not create image from display` error to a hint naming the
  right settings pane.
