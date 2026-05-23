import os

# Guard: ensure ENABLE_WRITE_APPROVALS is false during test collection
# so approval-dependent config is not required to run unit tests.
os.environ.setdefault("ENABLE_WRITE_APPROVALS", "false")
