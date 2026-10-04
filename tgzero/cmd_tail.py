"""
tgzero.cmd_tail
~~~~~~~~~~~~~~~
Implements `tgzero tail` — watches a file for new lines and forwards
them to Telegram in near-real-time, with optional keyword filtering.

Behaviour
---------
* Seeks to the end of the file on startup (does not replay history).
* Batches lines arriving within --batch-delay seconds into a single
  Telegram message to avoid flooding the API.
* Optionally filters to lines containing --filter keyword(s).
* Handles SIGTERM / SIGINT gracefully.

Exit codes
----------
0  Stopped cleanly by signal.
1  File not found or missing config.
"""

import signal
import sys
import time

from .api    import sanitize, send_message, strip_ansi
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

_BATCH_DELAY  = 2.0   # seconds to wait before flushing a batch to Telegram
_POLL_INTERVAL = 0.5  # seconds between file reads
_MAX_BATCH    = 3800  # max chars per Telegram message


def _make_signal_handler(token: str, chat_id: str, filepath: str):
    def handler(signum, frame):  # noqa: ARG001
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\n{YELLOW}Signal {sig_name} — stopping tail.{RESET}")
        send_message(token, chat_id,
                     f"🔴 tgzero tail stopped ({sig_name}): <code>{filepath}</code>")
        sys.exit(0)
    return handler


def run(args) -> int:
    """Entry point called by the CLI dispatcher."""
    token, chat_id = load_config()
    if not token or not chat_id:
        return 1

    filepath = args.file
    filters  = [f.strip() for f in args.filter.split(",") if f.strip()] if args.filter else []
    label    = sanitize(args.label or filepath)

    try:
        f = open(filepath, "r", errors="replace")
        f.seek(0, 2)   # Seek to end — don't replay existing content
    except FileNotFoundError:
        print(f"{RED}File not found: {filepath}{RESET}")
        return 1
    except OSError as e:
        print(f"{RED}Cannot open file: {e}{RESET}")
        return 1

    # Signal handling
    handler = _make_signal_handler(token, chat_id, filepath)
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT,  handler)

    print(f"{BLUE}Tailing: {filepath}{RESET}")
    if filters:
        print(f"{BLUE}Filter:  {', '.join(filters)}{RESET}")
    send_message(token, chat_id, f"👁 tgzero tail started: <code>{label}</code>")

    batch      = []
    last_flush = time.monotonic()

    def flush_batch():
        if not batch:
            return
        # ANSI-strip and HTML-sanitize each raw line before it goes anywhere
        # near <pre> — previously this went out completely unsanitized, so a
        # log line containing "<" or "&" could break the HTML parse mode (or
        # worse, inject markup) and colored log output would leak raw escape
        # bytes into the message.
        clean_lines = [sanitize(strip_ansi(l)) for l in batch]
        body = "\n".join(clean_lines)
        truncated = False
        if len(body) > _MAX_BATCH:
            body = body[:_MAX_BATCH]
            truncated = True

        text = f"<b>📄 {label}</b>\n<pre>{body}</pre>"
        if truncated:
            text += "\n<i>... [truncated]</i>"

        send_message(token, chat_id, text)
        batch.clear()

    while True:
        line = f.readline()

        if line:
            line = line.rstrip("\n")

            # Apply keyword filter if set
            if filters and not any(kw.lower() in line.lower() for kw in filters):
                continue

            print(f"{GREEN}{line}{RESET}")
            batch.append(line)

            # Flush immediately if batch is getting large
            if sum(len(l) for l in batch) >= _MAX_BATCH:
                flush_batch()
                last_flush = time.monotonic()

        else:
            # No new line — check if it's time to flush the pending batch
            if batch and (time.monotonic() - last_flush) >= _BATCH_DELAY:
                flush_batch()
                last_flush = time.monotonic()
            time.sleep(_POLL_INTERVAL)
