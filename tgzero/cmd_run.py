"""
tgzero.cmd_run
~~~~~~~~~~~~~~
Implements `tgzero run` — executes a local shell command and sends
the output and exit status to Telegram when it finishes.

Exit codes
----------
0  Command completed and result delivered to Telegram.
1  Delivery failed or missing config.
2  Command timed out.
3  Network / API failure.
"""

import shlex
import subprocess
import sys
import time
from datetime import datetime

from .api    import format_command_block, ok, sanitize, send_message
from .config import load_config

# --- Terminal Styling ---
if sys.stdout.isatty():
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    RESET  = "\033[0m"
else:
    GREEN = RED = YELLOW = RESET = ""

MAX_OUTPUT       = 3900   # leave headroom for the header inside Telegram's 4096 limit
DEFAULT_TIMEOUT  = 300    # 5 minutes — sane default for admin tasks


def run(args) -> int:
    """Entry point called by the CLI dispatcher."""
    token, chat_id = load_config()
    if not token or not chat_id:
        return 1

    command = args.command_str
    timeout = getattr(args, "timeout", None) or DEFAULT_TIMEOUT

    print(f"{YELLOW}Running: {command}{RESET}")

    start   = time.monotonic()
    started = datetime.now().strftime("%H:%M:%S")

    try:
        result = subprocess.run(
            shlex.split(command),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        msg = format_command_block(command, "", status_emoji="⏱",
                                   meta=f"Command timed out after {elapsed:.0f}s.")
        send_message(token, chat_id, msg)
        print(f"{RED}Timed out after {elapsed:.0f}s{RESET}")
        return 2
    except FileNotFoundError:
        msg = f"⚠️ Command not found: <code>{sanitize(command)}</code>"
        send_message(token, chat_id, msg)
        print(f"{RED}Command not found: {command}{RESET}")
        return 1
    except Exception as e:  # noqa: BLE001
        send_message(token, chat_id, f"⚠️ Failed to run command: {sanitize(str(e))}")
        return 1

    elapsed = time.monotonic() - start
    output  = (result.stdout + result.stderr).strip()
    status  = "✅" if result.returncode == 0 else "❌"

    meta = (
        f"Exit: <code>{result.returncode}</code> · "
        f"Started: {started} · "
        f"Took: {elapsed:.1f}s"
    )
    text = format_command_block(command, output, status_emoji=status, meta=meta,
                                max_output=MAX_OUTPUT)

    sent = send_message(token, chat_id, text)

    # Also print locally (raw, with ANSI intact — this is the real terminal)
    if output:
        print(output)
    colour = GREEN if result.returncode == 0 else RED
    print(f"{colour}Exited {result.returncode} in {elapsed:.1f}s{RESET}")

    return 0 if ok(sent) else 3
