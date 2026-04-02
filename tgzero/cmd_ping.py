"""
tgzero.cmd_ping
~~~~~~~~~~~~~~~
Implements `tgzero ping` — verifies credentials and sends a test message.

Exit codes
----------
0  Test message delivered successfully.
1  Delivery failed (bad token, wrong chat ID, network error, missing config).
"""

import sys

from .api    import send_message
from .config import load_config

# --- Terminal Styling ---
if sys.stdout.isatty():
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    RESET  = "\033[0m"
else:
    GREEN = RED = YELLOW = RESET = ""


def run(args) -> int:  # noqa: ARG001  (no args used but signature must match)
    """Entry point called by the CLI dispatcher."""
    print(f"{YELLOW}Checking credentials...{RESET}")

    token, chat_id = load_config()
    if not token or not chat_id:
        return 1

    print(f"  Token:    {token[:10]}...  (truncated for safety)")
    print(f"  Chat ID:  {chat_id}")
    print(f"{YELLOW}Sending test message...{RESET}")

    ok = send_message(token, chat_id, "✅ tgzero ping — connection successful.")

    if ok:
        print(f"{GREEN}Ping successful! Check your Telegram for the test message.{RESET}")
        return 0
    else:
        print(f"{RED}Ping failed. Check your TELEGRAM_TOKEN and TELEGRAM_CHAT_ID.{RESET}")
        return 1
