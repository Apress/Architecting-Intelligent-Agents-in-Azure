"""
pytest configuration — ensures environment is safe for unit-test collection.

Tests that import from main.py (e.g. test_tracing, test_policy_tracing,
test_trace_on_exception) fail at collection time when ENABLE_WRITE_APPROVALS=true
but the full approvals infrastructure config is absent from the local .env.
Overriding the flag here prevents the MissingConfigError that would otherwise
fire at module-load time; individual tests supply their own policy_state dicts
so this does not affect test coverage.
"""

import os

os.environ["ENABLE_WRITE_APPROVALS"] = "false"
