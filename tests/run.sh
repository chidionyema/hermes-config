#!/bin/bash
# Hermes critical-script test suite runner (Item 4 receipt). Exit code = pytest's.
exec python3 -m pytest "$(dirname "$0")" -q
