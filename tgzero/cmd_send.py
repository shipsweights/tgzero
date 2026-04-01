"""
tgzero.cmd_send
~~~~~~~~~~~~~~~
Implements `tgzero send` — fire-and-forget Telegram notifications.

Exit codes
----------
0  Message delivered successfully.
1  Delivery failed (API error, network failure, missing config).
"""

import json
import sys
import time

from .api    import send_message
from .config import load_config

# --- Terminal Styling ---
if sys.stdout.isatty():
    GREEN = "\033[92m"
    RED   = "\033[91m"
    RESET = "\033[0m"
else:
    GREEN = RED = RESET = ""


def run(args) -> int:
    """Entry point called by the CLI dispatcher.

    Args:
        args: Parsed argparse namespace with .msg, .silent, .json.

    Returns:
        Integer exit code.
    """
    token, chat_id = load_config()
    if not token or not chat_id:
        if args.json:
            print(json.dumps({"status": "error", "action": "send",
                              "error": "missing_config", "exit_code": 1}))
        return 1

    start_ms = time.monotonic()
    ok = send_message(token, chat_id, args.msg, silent=args.silent)
    latency_ms = int((time.monotonic() - start_ms) * 1000)

    if args.json:
        payload = {
            "status":      "success" if ok else "error",
            "action":      "send",
            "exit_code":   0 if ok else 1,
            "latency_ms":  latency_ms,
        }
        print(json.dumps(payload))
    else:
        if ok:
            print(f"{GREEN}Message sent successfully.{RESET}")
        else:
            print(f"{RED}Failed to send message.{RESET}")

    return 0 if ok else 1
