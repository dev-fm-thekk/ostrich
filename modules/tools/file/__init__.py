from modules.tools.file.base import (
    FileNavigator,
    get_file_navigator,
    list_files,
)

try:
    from modules.tools.file.windows import WindowsFileNavigator
except ImportError:
    WindowsFileNavigator = None  # type: ignore

try:
    from modules.tools.file.linux import LinuxFileNavigator
except ImportError:
    LinuxFileNavigator = None  # type: ignore

__all__ = [
    "FileNavigator",
    "WindowsFileNavigator",
    "LinuxFileNavigator",
    "get_file_navigator",
    "list_files",
]
