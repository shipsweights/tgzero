"""
tgzero.cmd_bridge
~~~~~~~~~~~~~~~~~
Implements `tgzero bridge` — the single long-running process connecting
Claude Code (via `tgzero hook`, writing request files — see state.py) to
Telegram.

Responsibilities
----------------
* Is the ONLY process that should call Telegram's getUpdates for this chat
  while it's running. `tgzero ask` / `tgzero daemon` long-poll independently
  and will 409-conflict with this if run at the same time on the same
  token — pick one model per chat.
* Watches the shared request directory for new Stop-event prompts (written
  by `tgzero hook`), sends each to Telegram with its rolling context.
* Matches a Telegram reply — a reply-to-this-message text, or (for a future
  button-bearing request type) a callback — back to the request that
  prompted it, and injects the answer into the originating terminal via
  `tmux send-keys`.
* Watches for requests resolved directly on the PC (the UserPromptSubmit
  hook marks them "answered_pc") and edits the Telegram message to show
  that instead of leaving a stale prompt around to be answered twice.
* Expires requests nobody answered within --ttl.

Exit codes
----------
0  Clean shutdown (SIGTERM/SIGINT).
1  Missing config, or another bridge instance already holds the lock.
"""

import signal
import subprocess
import sys
import time

from . import state
from .api    import (answer_callback_query, edit_message_text, get_updates,
                      message_id, ok, sanitize, send_message)
from .config import load_config
from .lock   import LockError, acquire, release

# --- Terminal Styling ---
if sys.stdout.isatty():
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    RESET  = "\033[0m"
else:
    RED = GREEN = YELLOW = BLUE = RESET = ""

_LOCK_NAME     = "tgzero-bridge"
_POLL_SECONDS  = 15            # getUpdates long-poll window
_DEFAULT_TTL_S = 6 * 3600      # expire an unanswered prompt after 6h


# ---------------------------------------------------------------------------
# tmux injection
# ---------------------------------------------------------------------------

def _tmux_inject(pane: str, text: str) -> bool:
    """Types `text` into the given tmux pane and presses Enter.

    Returns False (doing nothing) if pane is unset or tmux/the pane is
    unavailable — the caller must tell the Telegram user explicitly in that
    case, since silently not injecting would look identical to "it worked"
    from their side of the chat.
    """
    if not pane:
        return False
    try:
        subprocess.run(["tmux", "send-keys", "-t", pane, "-l", "--", text],
                       check=True, capture_output=True, timeout=5)
        subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"],
                       check=True, capture_output=True, timeout=5)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def _prompt_message(req: dict, *, suffix: str = "") -> str:
    """HTML text for a request's Telegram message, in its current state.

    Rebuilt (not just appended-to) on every edit so the header/project/body
    always matches what's in the request file, with `suffix` adding the
    resolution line (answer / "answered on PC" / expired) at the bottom.
    """
    project = sanitize(req.get("project") or "?")
    body    = req.get("context_text") or req.get("prompt_text") or "(no content)"
    header  = f"🤖 <b>[{project}]</b>"
    text    = f"{header}\n<pre>{sanitize(body)}</pre>"
    if suffix:
        text += f"\n{suffix}"
    else:
        text += "\n<i>Reply to this message to send your answer to the terminal.</i>"
    return text


# ---------------------------------------------------------------------------
# Request-directory side (producer: tgzero hook)
# ---------------------------------------------------------------------------

def _send_pending(token: str, chat_id: str) -> None:
    for req in state.list_all():
        if req.get("status") != "pending":
            continue
        result = send_message(token, chat_id, _prompt_message(req),
                              callback_prefix=req["id"])
        if ok(result):
            state.update(req["id"], status="sent", chat_id=chat_id,
                         message_id=message_id(result))
            print(f"{GREEN}→ sent {req['id']} [{req.get('project')}]{RESET}")
        else:
            print(f"{RED}Failed to deliver request {req['id']} — will retry next cycle.{RESET}",
                  file=sys.stderr)


def _sync_pc_answers(token: str, chat_id: str) -> None:
    for req in state.list_all():
        if req.get("status") != "answered_pc":
            continue
        mid = req.get("message_id")
        if mid:
            edit_message_text(token, chat_id, mid,
                              _prompt_message(req, suffix="✅ <b>Answered on PC.</b>"),
                              buttons=[])
        state.delete(req["id"])
        print(f"{BLUE}✓ {req['id']} resolved on PC{RESET}")


def _expire_stale(token: str, chat_id: str, ttl: float) -> None:
    now = time.time()
    for req in state.list_all():
        if req.get("status") not in ("pending", "sent"):
            continue
        if now - req.get("created_at", now) < ttl:
            continue
        mid = req.get("message_id")
        if mid:
            edit_message_text(token, chat_id, mid,
                              _prompt_message(req, suffix="⌛ <b>Expired — no answer.</b>"),
                              buttons=[])
        state.delete(req["id"])
        print(f"{YELLOW}⌛ {req['id']} expired{RESET}")


# ---------------------------------------------------------------------------
# Telegram side (consumer: getUpdates)
# ---------------------------------------------------------------------------

def _find_by_message_id(mid: int) -> dict | None:
    for req in state.list_all():
        if req.get("status") == "sent" and req.get("message_id") == mid:
            return req
    return None


def _find_single_pending() -> dict | None:
    pending = [r for r in state.list_all() if r.get("status") == "sent"]
    return pending[0] if len(pending) == 1 else None


def _resolve_with_answer(token: str, chat_id: str, req: dict, answer_text: str) -> None:
    injected = _tmux_inject(req.get("pane", ""), answer_text)
    state.update(req["id"], status="answered_telegram", answer=answer_text,
                 answered_via="telegram")

    suffix = f"✅ → {sanitize(answer_text)}"
    if not injected:
        suffix += ("\n⚠️ <i>Could not type the answer into the terminal "
                   "(no tmux pane, or tmux unavailable) — type it manually on the PC.</i>")

    mid = req.get("message_id")
    if mid:
        edit_message_text(token, chat_id, mid, _prompt_message(req, suffix=suffix), buttons=[])

    state.delete(req["id"])
    print(f"{GREEN}← {req['id']} answered via Telegram: "
          f"{answer_text[:60]!r}{'' if injected else ' (tmux inject FAILED)'}{RESET}")


def _handle_callback(token: str, chat_id: str, cb: dict) -> None:
    sender_id = str(cb.get("from", {}).get("id", ""))
    if sender_id != chat_id:
        answer_callback_query(token, cb["id"])
        return

    req_id, _, idx_str = cb.get("data", "").partition(":")
    req = state.read(req_id)
    if req is None or req.get("status") != "sent":
        answer_callback_query(token, cb["id"], "Nieaktualne.")
        return

    answer_callback_query(token, cb["id"])
    # Stop-event requests don't carry buttons today (see module docstring);
    # this path exists for a future button-bearing request type. For now,
    # treat whatever index came back as the literal answer text.
    _resolve_with_answer(token, chat_id, req, idx_str)


def _handle_message(token: str, chat_id: str, msg: dict) -> None:
    sender_id = str(msg.get("chat", {}).get("id", ""))
    if sender_id != chat_id:
        return

    text = (msg.get("text") or "").strip()
    if not text or text.startswith("/"):
        return

    reply_to = msg.get("reply_to_message")
    req = _find_by_message_id(reply_to["message_id"]) if reply_to else None
    if req is None:
        req = _find_single_pending()
    if req is None:
        print(f"{YELLOW}? ignored message {text[:60]!r}: no matching open request "
              f"(reply_to={reply_to['message_id'] if reply_to else None}){RESET}")
        send_message(token, chat_id,
                     "⚠️ I can't tell which request this answer belongs to — "
                     "please reply directly to the specific message.")
        return

    _resolve_with_answer(token, chat_id, req, text)


def _handle_update(token: str, chat_id: str, update: dict) -> None:
    cb = update.get("callback_query")
    if cb:
        _handle_callback(token, chat_id, cb)
        return
    msg = update.get("message")
    if msg:
        _handle_message(token, chat_id, msg)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _make_signal_handler(token: str, chat_id: str):
    def handler(signum, frame):  # noqa: ARG001
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\n{YELLOW}Signal {sig_name} — bridge shutting down.{RESET}")
        send_message(token, chat_id, f"🔴 tgzero bridge stopped ({sig_name}).")
        release(name=_LOCK_NAME)
        sys.exit(0)
    return handler


def run(args) -> int:
    """Entry point called by the CLI dispatcher."""
    token, chat_id = load_config()
    if not token or not chat_id:
        return 1

    try:
        acquire(queue_timeout=2, name=_LOCK_NAME)
    except LockError:
        print(f"{RED}Another tgzero bridge is already running for this user.{RESET}",
              file=sys.stderr)
        return 1

    ttl = getattr(args, "ttl", None) or _DEFAULT_TTL_S

    handler = _make_signal_handler(token, chat_id)
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT,  handler)

    print(f"{BLUE}tgzero bridge started — the only process that should be "
          f"polling Telegram for this chat right now.{RESET}")
    send_message(token, chat_id, "🟢 tgzero bridge started — notifications will appear here.")

    offset = None
    try:
        while True:
            _send_pending(token, chat_id)
            _sync_pc_answers(token, chat_id)
            _expire_stale(token, chat_id, ttl)

            updates = get_updates(token, offset=offset, long_poll_timeout=_POLL_SECONDS)
            if updates is None:
                print(f"{RED}getUpdates failed — retrying in 5s.{RESET}", file=sys.stderr)
                time.sleep(5)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                try:
                    _handle_update(token, chat_id, update)
                except Exception as e:  # noqa: BLE001
                    print(f"{RED}Error handling update {update.get('update_id')}: {e}{RESET}",
                          file=sys.stderr)
    finally:
        release(name=_LOCK_NAME)

    return 0
