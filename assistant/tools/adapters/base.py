from abc import ABC, abstractmethod


class PlatformAdapter(ABC):
    """The cross-platform surface from docs/spec.md SS7.

    run_shell is deliberately absent: it lives in assistant/tools/shell.py
    because it must be wrapped in the sandbox profile (SS8.1), and routing it
    through here would put a security boundary behind a plain method call.
    """

    @abstractmethod
    def launch_app(self, name: str) -> str: ...

    @abstractmethod
    def open_path(self, path: str) -> str: ...

    @abstractmethod
    def quit_app(self, name: str) -> str: ...

    @abstractmethod
    def list_windows(self) -> str: ...

    @abstractmethod
    def focus_window(self, name: str) -> str: ...

    @abstractmethod
    def set_volume(self, level: int) -> str: ...

    @abstractmethod
    def screenshot(self, path: str) -> str: ...
