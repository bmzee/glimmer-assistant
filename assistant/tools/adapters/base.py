from abc import ABC, abstractmethod


class PlatformAdapter(ABC):
    @abstractmethod
    def launch_app(self, name: str) -> str: ...

    @abstractmethod
    def open_path(self, path: str) -> str: ...
