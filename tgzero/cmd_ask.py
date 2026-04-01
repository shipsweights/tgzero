"""
tgzero.cmd_ask
~~~~~~~~~~~~~~
Implements `tgzero ask` — synchronous C2 gatekeeper.

Exit code contract
------------------
0  First button clicked (success / go).
1  Any other button clicked (abort / alternate).
   The literal button label is printed to stdout so bash can branch on it.
2  Timeout — user did not reply within --timeout seconds.
3  Network / API failure.
4  Queue timeout — could not acquire the local lockfile in time.
5  Terminated by SIGTERM or SIGINT.
"""

import json
import signal
import sys
import time

from .api    import answer_callback_query, get_updates, send_message
from .config import load_config
from .lock   import LockError, acquire, release

# --- Terminal Styling ---
if sys.stdout.isatty():
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RESET  = "\033[0m"
else:
    RED = GREEN = YELLOW = RESET = ""

# Sentinel used by signal handler to surface the exit code
_signal_exit_code: int | None = None


def _make_signal_handler(token: str, chat_id: str, use_json: bool):
    """Returns a SIGTERM/SIGINT handler that notifies Telegram, cleans up, exits."""

    def handler(signum, frame):  # noqa: ARG001
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        if not use_json:
            print(f"\n{YELLOW}Signal {sig_name} received — shutting down.{RESET}")
        send_message(
            token, chat_id,
            f"⚠️ ask process terminated by system signal ({sig_name}).",
        )
        release()
        if use_json:
            print(json.dumps({
                "status": "terminated", "action": "ask",
                "reply_string": None, "exit_code": 5, "latency_ms": None,
            }))
        sys.exit(5)

    return handler


def _flush_pending_updates(token: str) -> int | None:
    """Discards any already-queued updates; returns the next offset to use."""
    updates = get_updates(token, long_poll_timeout=1, http_timeout=6)
    if updates:
        return updates[-1]["update_id"] + 1
    return None


def run(args) -> int:
    """Entry point called by the CLI dispatcher."""
    token, chat_id = load_config()
    if not token or not chat_id:
        if args.json:
            print(json.dumps({"status": "error", "action": "ask",
                              "error": "missing_config", "exit_code": 3}))
        return 3

    # --- Parse buttons -------------------------------------------------------
    if args.buttons:
        buttons = [b.strip() for b in args.buttons.split(",") if b.strip()]
    else:
        buttons = ["OK"]

    # --- Acquire lockfile queue ----------------------------------------------
    # We use 2× the user timeout as the queue timeout so a queued process
    # doesn't give up before it even gets a chance to ask.
    queue_timeout = (args.timeout * 2) if args.timeout else None

    try:
        acquire(queue_timeout=queue_timeout)
    except LockError as exc:
        if not args.json:
            print(f"{RED}Queue timeout: {exc}{RESET}")
        else:
            print(json.dumps({
                "status": "queue_timeout", "action": "ask",
                "reply_string": None, "exit_code": 4, "latency_ms": None,
            }))
        return 4

    # --- Register signal handlers (after lock is held) -----------------------
    handler = _make_signal_handler(token, chat_id, args.json)
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT,  handler)

    start_ms  = time.monotonic()
    exit_code = 3          # default: network failure (overwritten on success)
    reply_str = None

    try:
        # --- Send the prompt -------------------------------------------------
        ok = send_message(token, chat_id, f"🤖 <b>{args.prompt}</b>",
                          buttons=buttons)
        if not ok:
            if not args.json:
                print(f"{RED}Failed to send prompt to Telegram.{RESET}")
            exit_code = 3
            return exit_code

        if not args.json:
            print(f"{YELLOW}Waiting for Telegram response...{RESET}")

        # Flush stale updates *after* sending the prompt so we don't
        # accidentally discard the reply that arrives quickly
        offset = _flush_pending_updates(token)
        deadline = (time.monotonic() + args.timeout) if args.timeout else None

        # --- Poll loop -------------------------------------------------------
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                if not args.json:
                    print(f"{YELLOW}Timeout reached — no reply received.{RESET}")
                send_message(token, chat_id, "⏱ No reply received — timed out.")
                exit_code = 2
                break

            remaining = max(1, int(deadline - time.monotonic())) if deadline else 25
            updates   = get_updates(token, offset=offset, long_poll_timeout=min(remaining, 25))

            if updates is None:  # network error surfaced as None
                exit_code = 3
                break

            for update in updates:
                offset = update["update_id"] + 1

                # --- Handle inline keyboard button press ---------------------
                cb = update.get("callback_query")
                if cb:
                    sender_id = str(cb.get("from", {}).get("id", ""))
                    if sender_id != chat_id:
                        if not args.json:
                            print(f"{RED}Unauthorized callback from ID: {sender_id}{RESET}")
                        continue
                    reply_str = cb.get("data", "")
                    answer_callback_query(token, cb["id"])

                # --- Handle plain text reply ---------------------------------
                else:
                    msg       = update.get("message", {})
                    sender_id = str(msg.get("chat", {}).get("id", ""))
                    if sender_id != chat_id:
                        if not args.json:
                            print(f"{RED}Unauthorized message from ID: {sender_id}{RESET}")
                        continue
                    reply_str = msg.get("text", "")

                # --- Resolve exit code from the reply ------------------------
                if reply_str == buttons[0]:
                    exit_code = 0
                else:
                    exit_code = 1
                    # Print the literal button label so bash can branch on it
                    if not args.json:
                        print(reply_str)
                    else:
                        # Will be captured in the JSON object below
                        pass

                if not args.json:
                    colour = GREEN if exit_code == 0 else RED
                    print(f"{colour}Reply received: '{reply_str}'{RESET}")
                break  # inner for-loop — we have our answer

            else:
                # No authorised reply found in this batch — keep polling
                continue
            break  # outer while-loop — we have our answer

    except Exception as e:  # noqa: BLE001
        if not args.json:
            print(f"{RED}Unexpected error: {e}{RESET}")
        exit_code = 3

    finally:
        release()

    latency_ms = int((time.monotonic() - start_ms) * 1000)

    if args.json:
        status_map = {0: "success", 1: "abort", 2: "timeout",
                      3: "network_error", 4: "queue_timeout", 5: "terminated"}
        print(json.dumps({
            "status":       status_map.get(exit_code, "unknown"),
            "action":       "ask",
            "reply_string": reply_str,
            "exit_code":    exit_code,
            "latency_ms":   latency_ms,
        }))

    return exit_code
