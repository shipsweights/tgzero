"""
tgzero.lock
~~~~~~~~~~~
Atomic lockfile management for serialising concurrent `tgzero ask` calls.

Design notes
------------
* The lock file is written at LOCK_PATH and contains the PID of the holder.
* On acquisition the PID is validated against /proc/{pid}/cmdline so that a
  stale lock left by a crashed process (whose PID was subsequently recycled by
  the OS) is never mistakenly treated as live.
* All public helpers raise LockError on unrecoverable failure so callers can
  map cleanly to exit code 4 (Queue Timeout).
"""

import os
import sys
import time

LOCK_PATH    = "/tmp/tgzero.lock"
_POLL        = 0.5   # seconds between acquisition attempts
_TGZERO_TAG  = "tgzero"   # substring expected in /proc/PID/cmdline


class LockError(RuntimeError):
    """Raised when the lockfile cannot be acquired within the allowed window."""


def _pid_is_live_tgzero(pid: int) -> bool:
    """Returns True only if *pid* is running and its cmdline contains 'tgzero'.

    Falls back to a plain existence check on non-Linux systems where /proc is
    unavailable.
    """
    cmdline_path = f"/proc/{pid}/cmdline"
    if os.path.exists(cmdline_path):
        try:
            with open(cmdline_path, "rb") as f:
                cmdline = f.read().replace(b"\x00", b" ").decode(errors="replace")
            return _TGZERO_TAG in cmdline
        except OSError:
            return False
    # Fallback: just check whether the PID exists at all
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _read_lock_pid() -> int | None:
    """Reads the PID from the lock file; returns None if unreadable/malformed."""
    try:
        with open(LOCK_PATH, "r") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _write_lock() -> None:
    """Writes the current PID atomically to the lock file."""
    tmp = LOCK_PATH + f".{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        f.write(str(os.getpid()))
    os.replace(tmp, LOCK_PATH)   # atomic on POSIX


def acquire(queue_timeout: float | None = None) -> None:
    """Blocks until the lock is acquired or *queue_timeout* seconds elapse.

    Args:
        queue_timeout: Maximum seconds to wait (None = wait forever).

    Raises:
        LockError: If the timeout is exceeded.
    """
    deadline = (time.monotonic() + queue_timeout) if queue_timeout is not None else None

    while True:
        if not os.path.exists(LOCK_PATH):
            _write_lock()
            return  # We own the lock

        # Lock file exists — check if the holder is still alive
        holder_pid = _read_lock_pid()
        if holder_pid is None or not _pid_is_live_tgzero(holder_pid):
            # Stale lock — clear it and try to claim immediately
            try:
                os.remove(LOCK_PATH)
            except OSError:
                pass
            _write_lock()
            return

        # Live holder — wait a bit before retrying
        if deadline is not None and time.monotonic() >= deadline:
            raise LockError(
                f"Could not acquire lock within {queue_timeout}s "
                f"(held by PID {holder_pid})."
            )

        time.sleep(_POLL)


def release() -> None:
    """Releases the lock if we are the current holder; silently ignores errors."""
    holder_pid = _read_lock_pid()
    if holder_pid == os.getpid():
        try:
            os.remove(LOCK_PATH)
        except OSError:
            pass
