"""
File Tools - Base Interface
===========================
Abstract base class defining file and filesystem interaction interfaces.
"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod

# Optional needle integration
try:
    import needle
    _HAS_NEEDLE = True
except ImportError:
    _HAS_NEEDLE = False


class FileNavigator(ABC):
    """Abstract base class defining file interaction interfaces."""

    @abstractmethod
    def list_files(self, path: str = ".") -> dict:
        """List files in directory."""
        pass


try:
    from modules.tools.file.windows import WindowsFileNavigator
except ImportError:
    WindowsFileNavigator = None  # type: ignore

try:
    from modules.tools.file.linux import LinuxFileNavigator
except ImportError:
    LinuxFileNavigator = None  # type: ignore


_file_navigator_instance: FileNavigator | None = None


def get_file_navigator() -> FileNavigator:
    """Return the FileNavigator instance appropriate for the current OS."""
    global _file_navigator_instance
    if _file_navigator_instance is None:
        if platform.system().lower() == "windows":
            if WindowsFileNavigator is None:
                raise NotImplementedError("Windows File navigator is not available.")
            _file_navigator_instance = WindowsFileNavigator()
        else:
            if LinuxFileNavigator is None:
                raise NotImplementedError("Linux File navigator is not available.")
            _file_navigator_instance = LinuxFileNavigator()
    return _file_navigator_instance


def list_files(path: str = ".") -> dict:
    """List files in a given directory path."""
    return get_file_navigator().list_files(path)


if _HAS_NEEDLE:
    list_files = needle.tool(list_files)
