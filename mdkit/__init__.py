"""mdhub — unified Markdown conversion toolkit.

A single CLI (`mdhub` / `python -m mdkit`) that exposes several independent
conversion modules. Each module is self-contained and can be used, upgraded,
or disabled on its own; the CLI router (``cli.py``) only dispatches.
"""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
