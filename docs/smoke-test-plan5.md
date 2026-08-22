# Plan 5 live smoke test

**Date:** 2026-08-22 · **Host:** M3 Max, macOS 26.6.2, **AC power / `powermode 0`**
**Model:** `qwen3.8:27b` · **Confirmations:** auto-declined throughout

Unit tests use fakes and the new tools were verified standalone. Neither shows
whether the *model* can select and drive them from a spoken-style request,
which is the only thing a user experiences. This drives the real loop against
the real model and real macOS.

## Results — 4/4

| # | Request | Tool | Outcome |
|---|---|---|---|
| 1 | "which applications have windows open right now?" | `list_windows` | ✅ 38.3s — enumerated and summarized |
| 2 | "take a screenshot and save it to `/…/glimmer_smoke.png`" | `screenshot` | ✅ 34.6s — **3.9 MB PNG written** |
| 3 | "set the system volume to 55 percent" | `set_volume` | ✅ 20.3s — volume moved 81 → 56 |
| 4 | "quit the Calculator app" | `quit_app` | ✅ 26.3s — **blocked at the gate** |

**Case 4 is the important one.** `quit_app` is CONFIRM tier; the harness
declined, the tool never executed, and the model reported it accurately
("You've declined to quit Calculator, so I've stopped that step") rather than
claiming success. Confirmation list: `['quit_app']` — and nothing else asked,
which is correct for three Tier-0/1 tools.

Two behaviours worth recording as expected, not defects:

- **Case 2:** the model noted the path "resolves to `/private/var/...`, which is
  the same location on macOS". That is `resolve_safe` canonicalizing through the
  `/var` symlink; the model explained it rather than treating it as an error.
- **Case 3:** asked for 55, got 56. macOS quantizes output volume to 1/16
  steps. Not a rounding bug in `set_volume`.

State was restored afterwards (volume back to 81, screenshot deleted).

## What the fakes missed

Every new tool passed its unit tests before any of this ran. Live execution
still found **three** real defects:

1. **`list_windows` → AppleScript −1700**, "can't make 0 into type specifier".
   The whole-list coercion form breaks as soon as a visible process has no
   front window — which is the common case.
2. **`list_windows` → AppleScript −1719**, "invalid index", after fixing (1).
   Iterating `every application process whose visible is true` re-queries the
   live collection, so it shifts mid-loop. Fixed by snapshotting names to
   plain strings first.
3. **`screenshot` reported Screen Recording denial as "could not create image
   from display"** — opaque. Now mapped to a hint naming the exact System
   Settings pane, matching the existing `-1743` Automation handling.

A fourth apparent failure — `fill_form_field` timing out on DuckDuckGo — was
**not** a defect: DDG's search box is a `textarea[name=q]`, not an `input`. It
was diagnosed by dumping the page's real inputs and confirming the wrapper
navigated, before touching any code.

This is the third time in this project that a fully green unit suite hid a
real-API failure. The pattern is consistent enough to state plainly: **for
anything that crosses into AppleScript, Playwright, or a vendor API, a passing
test suite is not evidence the feature works.**

## Related

- `docs/spec-coverage.md` — every spec clause, built or not
- `docs/latency.md` — §9 voice gate, 2.59s vs 2.5s
- `docs/model-ab.md` — model selection and the throttling correction
