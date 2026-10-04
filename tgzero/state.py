"""
tgzero.state
~~~~~~~~~~~~
On-disk request queue shared between `tgzero hook` (producer — invoked by
Claude Code) and `tgzero bridge` (consumer — the single Telegram poller).

Each request is one small JSON file, named "<id>.json", in a per-user
runtime directory (reusing the same 0700 directory convention as lock.py).
This is intentionally the simplest thing that works for a handful of
concurrent Claude Code sessions on one machine — not a general message
queue: writers only ever create a file under a fresh random id or rewrite
a file under an id they already own, so the lack of file locking here is a
deliberate, documented simplification rather than an oversight.
"""

import json
import os
import re
import secrets
import tempfile

from .lock import _lock_dir  # reuse the same 0700 per-user runtime dir

_VALID_ID = re.compile(r"^[a-f0-9]+$")


def _requests_dir() -> str:
    base = os.path.join(_lock_dir(), "tgzero-requests")
    os.makedirs(base, mode=0o700, exist_ok=True)
    os.chmod(base, 0o700)
    return base


def new_id() -> str:
    """Short random request id. Doubles as the Telegram callback_prefix for
    any buttons the request carries, so a button press decodes straight
    back to the request file with no extra lookup table."""
    return secrets.token_hex(4)


def _path(req_id: str) -> str:
    if not _VALID_ID.match(req_id):
        raise ValueError(f"invalid request id: {req_id!r}")
    return os.path.join(_requests_dir(), f"{req_id}.json")


def write(req_id: str, data: dict) -> None:
    """Writes a request file atomically (temp file + os.replace) so a reader
    never sees a half-written JSON file."""
    path = _path(req_id)
    d    = _requests_dir()
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read(req_id: str) -> dict | None:
    """Returns the request dict, or None if it doesn't exist / is unreadable
    (already resolved-and-deleted is the common case for 'None' here)."""
    try:
        with open(_path(req_id), "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def update(req_id: str, **fields) -> dict | None:
    """Read-modify-write a subset of fields. Returns the updated dict, or
    None if the request no longer exists (e.g. the bridge already resolved
    and deleted it) — callers should treat that as 'nothing to do', not as
    an error."""
    data = read(req_id)
    if data is None:
        return None
    data.update(fields)
    write(req_id, data)
    return data


def delete(req_id: str) -> None:
    """Removes a request file. Silently ignores a missing file."""
    try:
        os.remove(_path(req_id))
    except OSError:
        pass


def list_all() -> list[dict]:
    """Returns every currently-readable request, in no particular order."""
    out: list[dict] = []
    try:
        names = os.listdir(_requests_dir())
    except OSError:
        return out

    for name in names:
        if not name.endswith(".json"):
            continue
        data = read(name[:-5])
        if data is not None:
            out.append(data)
    return out
