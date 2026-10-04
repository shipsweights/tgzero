"""
tgzero.cmd_daemon
~~~~~~~~~~~~~~~~~
Implements `tgzero daemon` — long-running Telegram C2 agent.

Behaviours
----------
* Polls Telegram for commands via long-polling.
* Ignores messages from any sender other than TELEGRAM_CHAT_ID.
* Executes only commands present in --allow-list as literal strings
  (never shell-interpolated).
* Replies with ⚠️ message for unrecognised commands.
* On startup, drops messages older than 60 seconds (stale window).
* Logs a warning if system clock drifts >10 s from Telegram's timestamps.
* Enforces a minimum cooldown between command executions to prevent flooding.
* Handles SIGTERM / SIGINT gracefully — sends a Telegram notification
  before exiting.
"""

import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from .api    import (format_command_block, get_updates, is_long, ok, sanitize,
                     send_document, send_message, strip_ansi)
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
_CMD_TIMEOUT_S        = 30    # subprocess hard timeout
_MIN_CMD_INTERVAL_S   = 2.0   # minimum seconds between command executions


def _utc_now() -> float:
    return datetime.now(tz=timezone.utc).timestamp()


def _notify(token: str, chat_id: str, text: str) -> None:
    """send_message wrapper that logs (instead of silently swallowing)
    delivery failures. The daemon can't block on them — a dropped reply just
    means the operator doesn't see one message — but a *silent* string of
    failures (bad token, chat blocked the bot, rate limit) previously looked
    identical to everything working."""
    result = send_message(token, chat_id, text)
    if not ok(result):
        print(f"{RED}Failed to deliver message to Telegram.{RESET}", file=sys.stderr)


def _check_clock_drift(updates: list) -> None:
    """Logs a warning if the local clock drifts significantly from Telegram's."""
    for update in updates:
        msg = update.get("message") or update.get("callback_query", {}).get("message")
        if msg and "date" in msg:
            drift = abs(_utc_now() - msg["date"])
            if drift > _CLOCK_DRIFT_WARN_S:
                print(
                    f"{YELLOW}Warning: system clock differs from Telegram server "
                    f"time by {drift:.0f}s. Stale-message filtering may behave "
                    f"unexpectedly. Consider syncing NTP.{RESET}",
                    file=sys.stderr,
                )
            return  # Only need to check once per batch


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


def _execute_command(command: str) -> str:
    """Runs an allow-listed command and returns its full, ANSI-stripped output."""
    result = subprocess.run(
        shlex.split(command),
        shell=False,           # Never shell=True — command is a plain string
        capture_output=True,
        text=True,
        timeout=_CMD_TIMEOUT_S,
    )
    return strip_ansi(result.stdout + result.stderr).strip()


def _make_signal_handler(token: str, chat_id: str):
    def handler(signum, frame):  # noqa: ARG001
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\n{YELLOW}Signal {sig_name} received — daemon shutting down.{RESET}")
        _notify(token, chat_id,
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
        # Print each entry in quotes so operators can verify exact strings
        quoted = ", ".join(f'"{c}"' for c in allow_list)
        print(f"{BLUE}Allow-list ({len(allow_list)} commands): {quoted}{RESET}")
    else:
        print(f"{YELLOW}Warning: no --allow-list defined. No commands will be executed.{RESET}",
              file=sys.stderr)

    _notify(token, chat_id, "🟢 tgzero daemon started.")

    # Flush stale messages
    offset = _flush_stale(token)

    # Rate-limit state — track when the last command was executed
    last_cmd_time: float = 0.0

    # --- Main poll loop ------------------------------------------------------
    while True:
        updates = get_updates(token, offset=offset, long_poll_timeout=interval,
                              http_timeout=interval + 5)

        if updates is None:
            # Transport/API failure — don't advance offset, back off, retry.
            print(f"{RED}getUpdates failed — retrying in {interval}s.{RESET}", file=sys.stderr)
            time.sleep(interval)
            continue

        for update in updates:
            offset = update["update_id"] + 1

            msg       = update.get("message", {})
            sender_id = str(msg.get("chat", {}).get("id", ""))
            text      = msg.get("text", "").strip()
            msg_ts    = msg.get("date", 0)

            # Drop messages with no sender (channel posts, service messages)
            if not sender_id:
                continue

            # Drop messages outside the stale window at runtime too
            age = _utc_now() - msg_ts
            if age > _STALE_WINDOW_SECONDS:
                print(f"{YELLOW}Dropping late-arriving stale message (age: {age:.0f}s){RESET}")
                continue

            # Security: reject unauthorised senders
            if sender_id != chat_id:
                print(f"{RED}Unauthorized attempt from ID: {sender_id}{RESET}",
                      file=sys.stderr)
                continue

            if not text:
                continue

            print(f"{BLUE}Received command: '{text}'{RESET}")

            # Validate against allow-list
            if text not in allow_list:
                allowed_str = ", ".join(f'"{c}"' for c in allow_list) if allow_list else "(none)"
                reply = f"⚠️ Command not permitted. Allowed: {allowed_str}"
                _notify(token, chat_id, reply)
                print(f"{YELLOW}Rejected: '{text}' not in allow-list.{RESET}")
                continue

            # Rate limiting — prevent flooding via rapid Telegram messages
            elapsed_since_last = time.monotonic() - last_cmd_time
            if elapsed_since_last < _MIN_CMD_INTERVAL_S:
                cooldown = _MIN_CMD_INTERVAL_S - elapsed_since_last
                _notify(
                    token, chat_id,
                    f"⏳ Rate limit: please wait {cooldown:.1f}s before sending another command.",
                )
                print(f"{YELLOW}Rate limited: cooldown {cooldown:.1f}s remaining.{RESET}")
                continue

            # Execute and reply
            try:
                print(f"{GREEN}Executing: '{text}'{RESET}")
                output = _execute_command(text)
                last_cmd_time = time.monotonic()
                long = is_long(output)
                _notify(token, chat_id, format_command_block(
                    text, output,
                    truncated_note="preview — full output attached" if long
                    else "output truncated"))
                if long:
                    send_document(token, chat_id, "output.txt", output)
            except subprocess.TimeoutExpired:
                _notify(token, chat_id, format_command_block(
                    text, "", status_emoji="⏱",
                    meta=f"Command timed out after {_CMD_TIMEOUT_S}s."))
            except Exception as e:  # noqa: BLE001
                _notify(token, chat_id, format_command_block(
                    text, str(e), status_emoji="⚠️",
                    meta="Error executing command"))

        time.sleep(interval)
