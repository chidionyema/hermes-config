#!/usr/bin/env python3
"""
Post-correction reflection runner.
Appends root-cause analysis to the daily reflection.
Called automatically after every user correction.
"""
import sys
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from reflect_on_correction import main  # noqa
