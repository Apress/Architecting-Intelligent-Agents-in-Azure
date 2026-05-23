import sys
import os

# Ensure the thain package root is first on sys.path so 'memory', 'config', etc. resolve correctly.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
