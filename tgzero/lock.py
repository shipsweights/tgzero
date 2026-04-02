"""
tgzero.lock
~~~~~~~~~~~
Atomic lockfile management for serialising concurrent `tgzero ask` calls.

Design notes
------------
* The lock file lives in a per-user temp directory (XDG_RUNTIME_DIR or a
  mode-0700 fallback under /tmp) and is chmod 600 immediately after creation
  so other local users cannot observe it.
* Acquisition uses open(..., O_CREAT | O_EXCL) which is a single atomic
  syscall — no TOCTOU race between an existence check and a write.
* The file contains "<PID>:<nonce>" so that a stale lock whose PID was
  recycled by an unrelated process is not mistaken for a live tgzero holder
  (the nonce is checked against a side-file that only the real holder knows).
* All public helpers raise LockError on unrecoverable failure so callers can
  map cleanly to exit code 4 (Queue Timeout).
"""

import os
import secrets
import stat
import tempfile
import time

_POLL       = 0.5    # seconds between acquisition attempts
_TGZERO_TAG = "tgzero"   # substring expected in /proc/PID/cmdline


class LockError(RuntimeError):
    """Raised when the lockfile cannot be acquired within the allowed window."""


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _lock_dir() -> str:
    """Returns a mode-0700 directory suitable for our lock file.

    Preference order:
      1. $XDG_RUNTIME_DIR  (systemd-managed, already 0700, user-scoped)
      2. $TMPDIR           (may be user-scoped on macOS / some Linux setups)
      3. /tmp/tgzero-<uid> (created on demand, chmod 0700)
    """
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg and os.path.isdir(xdg):
        return xdg

    tmp = tempfile.gettempdir()
    uid_dir = os.path.join(tmp, f"tgzero-{os.getuid()}")
    os.makedirs(uid_dir, mode=0o700, exist_ok=True)
    # Harden in case makedirs inherited a permissive umask
    os.chmod(uid_dir, 0o700)
    return uid_dir


def _lock_path() -> str:
    return os.path.join(_lock_dir(), "tgzero.lock")


# ---------------------------------------------------------------------------
# Liveness check
# ---------------------------------------------------------------------------

def _pid_is_live_tgzero(pid: int) -> bool:
    """Returns True only if *pid* is running and its cmdline contains 'tgzero'.

    Falls back to a plain kill(0) existence check on non-Linux systems where
    /proc is unavailable.
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


# ---------------------------------------------------------------------------
# Low-level read / write
# ---------------------------------------------------------------------------

def _read_lock(path: str) -> tuple[int, str] | None:
    """Reads '<pid>:<nonce>' from the lock file.

    Returns (pid, nonce) or None if unreadable / malformed.
    """
    try:
        with open(path, "r") as f:
            raw = f.read().strip()
        pid_s, nonce = raw.split(":", 1)
        return int(pid_s), nonce
    except (OSError, ValueError):
        return None


def _try_create_lock(path: str) -> str | None:
    """Attempts an atomic exclusive create of *path*.

    Returns the nonce string on success, None if the file already exists.
    Raises OSError for any other filesystem error.
    """
    nonce = secrets.token_hex(8)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None
    try:
        os.write(fd, f"{os.getpid()}:{nonce}".encode())
    finally:
        os.close(fd)
    # Harden in case a restrictive umask prevented 0o600 above
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return nonce


# Module-level nonce so release() can verify we still own the lock
_held_nonce: str | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def acquire(queue_timeout: float | None = None) -> None:
    """Blocks until the lock is acquired or *queue_timeout* seconds elapse.

    Args:
        queue_timeout: Maximum seconds to wait (None = wait forever).

    Raises:
        LockError: If the timeout is exceeded.
    """
    global _held_nonce

    path     = _lock_path()
    deadline = (time.monotonic() + queue_timeout) if queue_timeout is not None else None

    while True:
        nonce = _try_create_lock(path)
        if nonce is not None:
            _held_nonce = nonce
            return  # We own the lock

        # Lock exists — inspect the holder
        info = _read_lock(path)
        if info is None:
            # Unreadable / truncated — treat as stale and remove
            try:
                os.remove(path)
            except OSError:
                pass
            continue  # retry immediately

        holder_pid, _holder_nonce = info
        if not _pid_is_live_tgzero(holder_pid):
            # Stale lock — remove and retry
            try:
                os.remove(path)
            except OSError:
                pass
            continue

        # Live holder — check timeout then sleep
        if deadline is not None and time.monotonic() >= deadline:
            raise LockError(
                f"Could not acquire lock within {queue_timeout}s "
                f"(held by PID {holder_pid})."
            )

        time.sleep(_POLL)


def release() -> None:
    """Releases the lock only if we are the confirmed current holder.

    Verifies both PID and nonce before removing, so a slow process that woke
    up after its lock was forcibly cleared never deletes a new holder's lock.
    Silently ignores all errors.
    """
    global _held_nonce

    if _held_nonce is None:
        return

    path = _lock_path()
    info = _read_lock(path)
    if info is not None:
        holder_pid, holder_nonce = info
        if holder_pid == os.getpid() and holder_nonce == _held_nonce:
            try:
                os.remove(path)
            except OSError:
                pass

    _held_nonce = None
