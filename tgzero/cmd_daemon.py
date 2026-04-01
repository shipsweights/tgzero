"""
tgzero.cmd_daemon
~~~~~~~~~~~~~~~~~
Implements `tgzero daemon` — long-running Telegram C2 agent.

Behaviours
----------
* Polls Telegram every --interval seconds for commands.
* Ignores messages from any sender other than TELEGRAM_CHAT_ID.
* Executes only commands present in --allow-list as literal strings
  (never shell-interpolated).
* Replies with ⚠️ message for unauthorized commands.
* On startup, drops messages older than 60 seconds (stale window).
* Logs a warning if system clock drifts >10 s from Telegram's timestamps.
* Handles SIGTERM / SIGINT gracefully — sends a Telegram notification
  before exiting.
"""

import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from .api    import get_updates, send_message
from .config import load_config

# --- Terminal Styling ---
if sys.stdout.isatty():
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    RESET  = "\033[0m"
else:
    RED = GREEN = YELLOW = BLUE = RESET = ""

_STALE_WINDOW_SECONDS = 60
_CLOCK_DRIFT_WARN_S   = 10


def _utc_now() -> float:
    return datetime.now(tz=timezone.utc).timestamp()


def _check_clock_drift(updates: list) -> None:
    """Logs a warning if the local clock drifts significantly from Telegram's."""
    for update in updates:
        msg = update.get("message") or update.get("callback_query", {}).get("message")
        if msg and "date" in msg:
            telegram_ts = msg["date"]
            drift = abs(_utc_now() - telegram_ts)
            if drift > _CLOCK_DRIFT_WARN_S:
                print(
                    f"{YELLOW}Warning: system clock differs from Telegram server "
                    f"time by {drift:.0f}s. Stale-message filtering may behave "
                    f"unexpectedly. Consider syncing NTP.{RESET}"
                )
            return   # Only need to check once


def _flush_stale(token: str) -> int | None:
    """Drops all pending updates older than the stale window; returns next offset."""
    updates = get_updates(token, long_poll_timeout=1, http_timeout=6)
    if not updates:
        return None

    _check_clock_drift(updates)

    now    = _utc_now()
    offset = None

    for update in updates:
        offset = update["update_id"] + 1
        msg    = update.get("message", {})
        ts     = msg.get("date", 0)
        age    = now - ts
        if age > _STALE_WINDOW_SECONDS:
            print(f"{YELLOW}Dropping stale message (age: {age:.0f}s){RESET}")

    return offset


def _execute_command(command: str, allow_list: list[str]) -> str:
    """Runs an allow-listed command and returns its output (truncated to 3900 chars)."""
    cmd_parts = shlex.split(command)
    result = subprocess.run(
        cmd_parts,
        shell=False,          # Never shell=True — command is a plain string
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (result.stdout + result.stderr).strip()
    if len(output) > 3900:
        output = output[:3900] + "\n... [truncated]"
    return output or "(no output)"


def _make_signal_handler(token: str, chat_id: str):
    def handler(signum, frame):  # noqa: ARG001
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\n{YELLOW}Signal {sig_name} received — daemon shutting down.{RESET}")
        send_message(token, chat_id,
                     f"🔴 tgzero daemon stopped by system signal ({sig_name}).")
        sys.exit(0)

    return handler


def run(args) -> int:
    """Entry point called by the CLI dispatcher."""
    token, chat_id = load_config()
    if not token or not chat_id:
        return 1

    # --- Parse allow-list ----------------------------------------------------
    allow_list: list[str] = []
    if args.allow_list:
        allow_list = [c.strip() for c in args.allow_list.split(",") if c.strip()]

    interval: int = args.interval

    # --- Signal handling -----------------------------------------------------
    handler = _make_signal_handler(token, chat_id)
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT,  handler)

    # --- Startup -------------------------------------------------------------
    print(f"{BLUE}tgzero daemon started.{RESET}")
    if allow_list:
        print(f"{BLUE}Allow-list: {', '.join(allow_list)}{RESET}")
    else:
        print(f"{YELLOW}Warning: no --allow-list defined. No commands will be executed.{RESET}")

    send_message(token, chat_id, "🟢 tgzero daemon started.")

    # Flush stale messages
    offset = _flush_stale(token)

    # --- Main poll loop ------------------------------------------------------
    while True:
        updates = get_updates(token, offset=offset, long_poll_timeout=interval,
                              http_timeout=interval + 5)

        for update in updates:
            offset = update["update_id"] + 1

            msg       = update.get("message", {})
            sender_id = str(msg.get("chat", {}).get("id", ""))
            text      = msg.get("text", "").strip()
            msg_ts    = msg.get("date", 0)

            # Drop messages outside the stale window at runtime too
            age = _utc_now() - msg_ts
            if age > _STALE_WINDOW_SECONDS:
                print(f"{YELLOW}Dropping late-arriving stale message (age: {age:.0f}s){RESET}")
                continue

            # Security: reject unauthorised senders
            if sender_id != chat_id:
                print(f"{RED}Unauthorized attempt from ID: {sender_id}{RESET}")
                continue

            if not text:
                continue

            print(f"{BLUE}Received command: '{text}'{RESET}")

            # Validate against allow-list
            if text not in allow_list:
                allowed_str = ", ".join(allow_list) if allow_list else "(none)"
                reply = f"⚠️ Command not permitted. Authorized commands: {allowed_str}"
                send_message(token, chat_id, reply)
                print(f"{YELLOW}Rejected: '{text}' not in allow-list.{RESET}")
                continue

            # Execute and reply
            try:
                print(f"{GREEN}Executing: '{text}'{RESET}")
                output = _execute_command(text, allow_list)
                send_message(token, chat_id, f"<b>$ {text}</b>\n<pre>{output}</pre>")
            except subprocess.TimeoutExpired:
                send_message(token, chat_id, f"⚠️ Command '{text}' timed out after 30s.")
            except Exception as e:  # noqa: BLE001
                send_message(token, chat_id, f"⚠️ Error executing '{text}': {e}")

        time.sleep(interval)
