#!/usr/bin/env python3
"""Compatibility entry point for modeld_v2.

Patch only the PKL unpickler before importing modeld.py. This keeps the known-good
model runtime while allowing PKLs serialized by an adjacent tinygrad ABI to load.
"""

import os
import runpy

import openpilot.selfdrive.modeld.helpers as stock_model_helpers
from openpilot.sunnypilot.modeld_v2.helpers import load_oob as compat_load_oob

stock_model_helpers.load_oob = compat_load_oob

if __name__ == "__main__":
  runpy.run_path(os.path.join(os.path.dirname(__file__), "modeld.py"), run_name="__main__")
