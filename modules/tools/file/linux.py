"""
Linux File Navigator
====================
Implementation of FileNavigator for Linux.
"""

from __future__ import annotations

import os

try:
    from modules.tools.file.base import FileNavigator
except ImportError:
    from modules.tools.file.base import FileNavigator


class LinuxFileNavigator(FileNavigator):
    """Linux implementation of FileNavigator."""

    def list_files(self, path: str) -> dict:
        try:
            files = os.listdir(path)
            return {"success": True, "files": files}
        except Exception as e:
            return {"success": False, "message": str(e), "files": []}
