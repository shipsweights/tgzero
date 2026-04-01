"""
tgzero.config
~~~~~~~~~~~~~
Loads and validates environment configuration from a .env file or
shell environment variables.
"""

import os
import stat
import sys

# --- Terminal Styling ---
# Disable ANSI codes when output is redirected to a file or pipe
if sys.stdout.isatty():
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    RESET  = "\033[0m"
else:
    RED = YELLOW = RESET = ""


def manual_load_dotenv(filepath: str) -> None:
    """Loads variables from a .env file into the environment.

    - Warns if the file has overly permissive permissions (readable by others)
    - Strips inline comments from values  (e.g. TOKEN=abc # comment → abc)
    - Skips malformed lines gracefully
    - Does NOT overwrite variables already set in the environment
    """
    if not os.path.exists(filepath):
        return

    # Warn if readable by group or others
    try:
        mode = os.stat(filepath).st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            print(
                f"{YELLOW}Warning: '{filepath}' is readable by others. "
                f"Secure it with: chmod 600 {filepath}{RESET}"
            )
    except OSError:
        pass

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key   = key.strip()
            value = value.strip().strip('"').strip("'")

            # Strip inline comments (e.g. TOKEN=abc # my token → abc)
            if " #" in value:
                value = value.split(" #", 1)[0].strip()

            # Never overwrite an already-exported shell variable
            if key and key not in os.environ:
                os.environ[key] = value


def load_config() -> tuple[str, str]:
    """Resolves TOKEN and CHAT_ID, checking the .env file beside the CWD.

    Returns:
        (TOKEN, CHAT_ID) — either may be empty string if not set.
    """
    # Look for telegram.env in the current working directory
    manual_load_dotenv(os.path.join(os.getcwd(), "telegram.env"))

    token   = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print(
            f"{RED}Error: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID is not set. "
            f"Export them or place them in a 'telegram.env' file.{RESET}"
        )

    return token, chat_id
