"""Render/repo-root entry so `uvicorn main:app` works without a rootDir."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PACKAGE = Path(__file__).resolve().parent / "finmentor"
if str(_PACKAGE) not in sys.path:
    sys.path.insert(0, str(_PACKAGE))

_spec = importlib.util.spec_from_file_location("finmentor_main", _PACKAGE / "main.py")
if _spec is None or _spec.loader is None:
    raise ImportError("Could not load finmentor/main.py")
_module = importlib.util.module_from_spec(_spec)
sys.modules["finmentor_main"] = _module
_spec.loader.exec_module(_module)
app = _module.app
