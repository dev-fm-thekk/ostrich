"""
Windows File Navigator
======================
Implementation of FileNavigator for Windows.
"""

from __future__ import annotations

import os

from modules.tools.file.base import FileNavigator


class WindowsFileNavigator(FileNavigator):
    """Windows implementation of FileNavigator."""

    def list_files(self, path: str = ".") -> dict:
        try:
            files = os.listdir(path)
            return {"success": True, "files": files}
        except Exception as e:
            return {"success": False, "message": str(e), "files": []}
