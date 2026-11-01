"""
File Tools - Base Interface
===========================
Abstract base class defining file and filesystem interaction interfaces.
(Placeholder / Extensible interface)
"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod


class FileNavigator(ABC):
    """Abstract base class defining file interaction interfaces."""

    @abstractmethod
    def list_files(self, path: str) -> dict:
        """List files in directory."""
        pass


try:
    from modules.tools.file.windows import WindowsFileNavigator
    from modules.tools.file.linux import LinuxFileNavigator
except ImportError:
    from modules.tools.file.windows import WindowsFileNavigator
    from modules.tools.file.linux import LinuxFileNavigator


_file_navigator_instance: FileNavigator | None = None


def get_file_navigator() -> FileNavigator:
    """Return the FileNavigator instance appropriate for the current OS."""
    global _file_navigator_instance
    if _file_navigator_instance is None:
        if platform.system().lower() == "windows":
            _file_navigator_instance = WindowsFileNavigator()
        else:
            _file_navigator_instance = LinuxFileNavigator()
    return _file_navigator_instance
