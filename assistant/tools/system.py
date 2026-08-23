from __future__ import annotations

from pathlib import Path

from assistant.security.paths import PathNotAllowedError, resolve_safe
from assistant.tools.adapters.base import PlatformAdapter
from assistant.tools.registry import RiskTier, Tool


def _guard(fn):
    """Adapter faults must come back as ERROR strings, never exceptions.

    The loop turns a raised exception into a generic failure; a returned string
    is something the model can read and act on.
    """

    def wrapped(args: dict) -> str:
        try:
            return fn(args)
        except Exception as e:
            return f"ERROR: {e}"

    return wrapped


CAPTURE_SUBDIR = "Glimmer Screenshots"

# The assistant's own state directory holds the audit log and configuration.
# A screenshot steered here by injected content would overwrite the audit
# trail with PNG bytes, destroying every prior record. Denied unconditionally,
# independent of whatever capture_dir the caller wires up.
_ALWAYS_PROTECTED = (Path("~/.glimmer-assistant"),)


def make_system_tools(
    adapter: PlatformAdapter,
    allowed_roots: list[Path],
    capture_dir: Path | None = None,
    protected_paths: list[Path] | None = None,
) -> list[Tool]:
    # screenshot takes a MODEL-SUPPLIED write path, i.e. injected content can
    # steer it. Confining captures to one dedicated folder (rather than all of
    # the allowed roots) removes the arbitrary-write primitive.
    if capture_dir is None:
        capture_dir = Path(allowed_roots[0]).expanduser() / CAPTURE_SUBDIR
    capture_root = Path(capture_dir).expanduser().resolve()
    protected = [
        Path(prot).expanduser().resolve()
        for prot in (*_ALWAYS_PROTECTED, *(protected_paths or []))
    ]

    @_guard
    def quit_app(args: dict) -> str:
        return adapter.quit_app(args["name"])

    @_guard
    def list_windows(args: dict) -> str:
        return adapter.list_windows()

    @_guard
    def focus_window(args: dict) -> str:
        return adapter.focus_window(args["name"])

    @_guard
    def set_volume(args: dict) -> str:
        level = args.get("level")
        # Validate before touching the system: a model that emits 500 must not
        # reach osascript.
        if isinstance(level, bool) or not isinstance(level, (int, float)):
            return "ERROR: level must be a number between 0 and 100"
        level = int(level)
        if not 0 <= level <= 100:
            return "ERROR: level must be between 0 and 100"
        return adapter.set_volume(level)

    @_guard
    def screenshot(args: dict) -> str:
        raw = Path(args["path"]).expanduser()
        # A bare file name lands in the capture folder; a relative path cannot
        # be laundered through the process CWD.
        candidate = raw if raw.is_absolute() else capture_root / raw
        target = candidate.resolve()
        # Denylist first, so a capture aimed at the audit log is refused as
        # protected even if a misconfigured capture_dir contains it.
        for prot in protected:
            if target == prot or prot in target.parents:
                return f"ERROR: refusing to write to protected path: {target}"
        try:
            # resolve_safe resolves non-strictly, so a not-yet-existing capture
            # target is fine while still being canonicalized + confined.
            target = resolve_safe(str(target), [capture_root])
        except PathNotAllowedError:
            return (
                f"ERROR: screenshots may only be saved inside {capture_root}; "
                "pass a bare file name like 'shot.png'"
            )
        # screencapture writes PNG bytes to whatever name it is given; without
        # this check the tool doubles as a disguise-anything-as-x primitive.
        if target.suffix.lower() != ".png":
            return "ERROR: screenshot path must end in .png"
        # Never truncate an existing file: the clobber target could be a user
        # document (or, formerly, the audit log itself).
        if target.exists():
            return f"ERROR: refusing to overwrite existing file: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)
        return adapter.screenshot(str(target))

    return [
        Tool(
            name="quit_app",
            description="Quit an application by name. The app may prompt to save work.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            # CONFIRM, not UNDO: spec SS8.3's Tier-1 undo window does not exist
            # yet, and quitting an app with unsaved work is not recoverable.
            risk_tier=RiskTier.CONFIRM,
            platforms=("darwin",),
            func=quit_app,
        ),
        Tool(
            name="list_windows",
            description="List visible applications and their front window titles.",
            parameters={"type": "object", "properties": {}, "required": []},
            risk_tier=RiskTier.AUTO,
            platforms=("darwin",),
            func=list_windows,
            # Window titles are attacker-controlled: a browser's title IS the
            # page title, the same laundering vector that made open_url
            # untrusted in Plan 4. Datamark it.
            untrusted=True,
        ),
        Tool(
            name="focus_window",
            description="Bring an application to the front by name.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            risk_tier=RiskTier.UNDO,
            platforms=("darwin",),
            func=focus_window,
        ),
        Tool(
            name="set_volume",
            description="Set the system output volume, 0 to 100.",
            parameters={
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "minimum": 0, "maximum": 100}
                },
                "required": ["level"],
            },
            risk_tier=RiskTier.UNDO,
            platforms=("darwin",),
            func=set_volume,
        ),
        Tool(
            name="screenshot",
            description=(
                "Capture the screen to a new PNG file in the '"
                + CAPTURE_SUBDIR
                + "' folder. Pass a file name like 'shot.png'. Existing files "
                "are never overwritten. Returns the saved path."
            ),
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            # Tier 0 per spec SS8.3, which lists screenshot as read-only.
            risk_tier=RiskTier.AUTO,
            platforms=("darwin",),
            func=screenshot,
        ),
    ]
