# Voice activation: key and mode

**Default: double-tap Right Option.** Tap it twice to start listening, speak for
as long as you like, tap twice again to stop.

Holding a key for the length of a request is uncomfortable past a sentence and
competes with typing on a laptop, so the toggle is the default. Classic
push-to-talk is still available:

```yaml
voice_activation: hold      # hold the key while speaking
```

A toggle has one failure mode push-to-talk does not: **it can be left on.**
Push-to-talk ends when you let go; a toggle ends only when you remember it. So a
session stops itself after `voice_max_session_seconds` (default 120) rather than
recording until something breaks.

Two taps count as a double-tap when they land within
`voice_tap_window_seconds` (default 0.4). A lone tap does nothing, so a stray
press cannot open the microphone. Tapping three times still works — the
detector rearms on each tap rather than discarding the pair.

## Choosing the key

The original default was `ctrl`, which was a bad choice made before there was
anything to test it against: Ctrl is a modifier you press constantly for
ordinary shortcuts, so every `Ctrl-C` would open a voice turn. The 0.3s
minimum-utterance floor filters accidental taps, but not a held Ctrl.

## What the field does

Surveying macOS dictation tools (August 2026), the recommendations cluster on:

- **Fn** — the most common default. Wispr Flow ships it, with `Ctrl+Opt` as a
  fallback. macOS's own dictation uses double-tap Fn.
- **Right Option** — "easy to reach, rarely conflicts with app shortcuts"
- **Caps Lock** — "underused key that is easy to reach"
- **F5 / a function key** — dedicated and memorable

## Why we do not use Fn

**`pynput` does not expose it.** `keyboard.Key` has no `fn` member: on macOS the
Fn key is handled below the level userspace event taps see, so it never arrives
as a normal keycode. The single most popular choice in this category is simply
not implementable on our stack, and no amount of config makes it work.

Adopting it would mean replacing `pynput` with a native `CGEventTap` reading
`NSEventModifierFlagFunction`. That is a real option if the key matters enough,
but it is a dependency change, not a setting.

## Why the other candidates lost

Checked against `pynput`'s actual key table **and** MacBook hardware, since
that is the target:

| candidate | on a MacBook | `pynput` sees it | verdict |
|---|---|---|---|
| `fn` | yes | **no** | not detectable |
| `ctrl_r` | **no** | yes | MacBooks have no right Ctrl |
| `f13`–`f16` | **no** | yes | full-size keyboards only |
| `caps_lock` | yes | yes | toggles state; macOS adds an activation delay, so holding it turns caps on |
| `cmd_r` | yes | yes | workable, but Cmd is heavily used |
| **`alt_r`** | **yes** | **yes** | ✅ chosen |

Right Option is the only candidate that is present on the hardware, visible to
the input library, and not already carrying shortcut duty.

## Changing it

In `~/.glimmer-assistant/config.yaml`:

```yaml
voice_hotkey: cmd_r
```

It must name a key `pynput` knows. An unknown name raises at startup with the
valid list rather than failing silently — a hotkey that quietly never fires is
the worst outcome for a push-to-talk app.

Valid modifier-ish choices: `alt`, `alt_r`, `alt_gr`, `cmd`, `cmd_r`, `ctrl`,
`ctrl_r`, `shift`, `shift_r`, `caps_lock`, `f1`–`f20`.

If you have a full-size keyboard, **`f13`** is arguably better than the default:
it is a dedicated key that no application claims.

## It will not work without Input Monitoring

`pynput` reads global key events, which macOS gates behind **Input Monitoring**
(and often **Accessibility**). Without the grant the key does nothing at all —
no error, no indication, the app simply appears dead while running perfectly.

`assistant/capabilities.py` reports this on launch precisely because it is
invisible otherwise.

## Sources

- [Wispr Flow — supported hotkeys](https://docs.wisprflow.ai/articles/2612050838-supported-unsupported-keyboard-hotkey-shortcuts)
- [Voibe — Mac dictation shortcuts, conflicts and fixes](https://www.getvoibe.com/resources/mac-dictation-keyboard-shortcuts-guide/)
- [Parakeety — voice typing on Mac, and a better key](https://www.parakeety.com/resources/voice-typing-mac)
- [Scryb — voice typing keyboard shortcuts for macOS](https://scrybapp.com/blog/voice-typing-keyboard-shortcuts-macos)
