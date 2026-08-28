"""Ensure frozen PySide6 extension modules can load Qt DLLs from PySide6."""

import os
import sys


if sys.platform.startswith("win") and hasattr(sys, "_MEIPASS"):
    os.add_dll_directory(os.path.join(sys._MEIPASS, "PySide6"))
