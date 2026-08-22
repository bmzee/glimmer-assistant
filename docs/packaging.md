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

## Known limitations

- **The interpreter path is baked in at build time.** Build with the venv you
  intend to run, and rebuild if it moves — the bundle is a launcher, not a
  self-contained application. A relocated or deleted venv produces an app that
  silently fails to start.
- **Not a distributable artifact.** No embedded Python, no Developer ID
  signature, no notarization. This solves the permissions problem, not
  distribution.
- **Screen Recording has no `Info.plist` key.** Unlike Microphone and Apple
  Events, it is granted only on first use. `screenshot` maps the resulting
  opaque `could not create image from display` error to a hint naming the
  right settings pane.
