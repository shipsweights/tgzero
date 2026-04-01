"""
tgzero.__main__ / tgzero.cli
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unified CLI entry point.  Installed as the `tgzero` console script.

Usage
-----
tgzero send   --msg "…" [--silent] [--json]
tgzero ask    --prompt "…" [--buttons "A,B"] [--timeout N] [--json]
tgzero daemon --allow-list "cmd1,cmd2" [--interval N]
"""

import argparse
import sys

from . import __version__

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tgzero",
        description=(
            "tgzero — Zero-dependency, stdlib-only Telegram bridge for two-way CLI automation.\n"
            "Simple alerts or interactive command-and-control using nothing but the Python standard library."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"tgzero {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # -------------------------------------------------------------------------
    # tgzero send
    # -------------------------------------------------------------------------
    send_p = subparsers.add_parser(
        "send",
        help="Fire-and-forget Telegram notification.",
        description=(
            "Sends a one-way notification to the configured Telegram chat.\n"
            "Ideal for cron jobs, pipeline completions, and background alerts."
        ),
    )
    send_p.add_argument(
        "--msg", "-m",
        required=True,
        metavar="TEXT",
        help="Message text to send (max 4096 chars; longer text is truncated).",
    )
    send_p.add_argument(
        "--silent", "-s",
        action="store_true",
        default=False,
        help="Send without a notification sound on the recipient's device.",
    )
    send_p.add_argument(
        "--json", "-j",
        action="store_true",
        default=False,
        help="Suppress plain-text logs; output a single JSON object on completion.",
    )

    # -------------------------------------------------------------------------
    # tgzero ask
    # -------------------------------------------------------------------------
    ask_p = subparsers.add_parser(
        "ask",
        help="Pause script execution until a Telegram reply is received.",
        description=(
            "Synchronous C2 gatekeeper.  Sends a prompt with optional inline\n"
            "keyboard buttons and blocks until the authorised user replies.\n\n"
            "Exit codes:\n"
            "  0  First button clicked (success / go)\n"
            "  1  Any other button clicked (abort / alternate)\n"
            "  2  Timeout — no reply within --timeout seconds\n"
            "  3  Network / API failure\n"
            "  4  Queue timeout — another ask is holding the lock\n"
            "  5  Process terminated by SIGTERM / SIGINT\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ask_p.add_argument(
        "--prompt", "-p",
        required=True,
        metavar="TEXT",
        help="Question or prompt sent to the Telegram user.",
    )
    ask_p.add_argument(
        "--buttons", "-b",
        default=None,
        metavar="LABELS",
        help=(
            "Comma-separated button labels (e.g. 'Deploy,Abort,Check'). "
            "First button = exit 0; any other = exit 1. "
            "Defaults to a single 'OK' button."
        ),
    )
    ask_p.add_argument(
        "--timeout", "-t",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Seconds to wait before giving up (exit 2). Default: wait forever.",
    )
    ask_p.add_argument(
        "--json", "-j",
        action="store_true",
        default=False,
        help=(
            "Suppress plain-text logs; output a single JSON object on completion.\n"
            "The process still returns the correct exit code."
        ),
    )

    # -------------------------------------------------------------------------
    # tgzero daemon
    # -------------------------------------------------------------------------
    daemon_p = subparsers.add_parser(
        "daemon",
        help="Long-running Telegram C2 agent (for systemd / Docker).",
        description=(
            "Monitors Telegram for ad-hoc administrative commands.\n"
            "Only commands listed in --allow-list are executed.\n"
            "Designed to run as a systemd service or Docker container.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    daemon_p.add_argument(
        "--allow-list", "-a",
        default="",
        metavar="COMMANDS",
        help="Comma-separated list of permitted shell commands (e.g. 'status,reboot').",
    )
    daemon_p.add_argument(
        "--interval", "-i",
        type=int,
        default=3,
        metavar="SECONDS",
        help="Polling frequency in seconds (default: 3).",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    # Lazy imports keep startup fast and avoid circular deps
    if args.command == "send":
        from .cmd_send import run
    elif args.command == "ask":
        from .cmd_ask import run
    elif args.command == "daemon":
        from .cmd_daemon import run
    else:
        parser.print_help()
        sys.exit(1)

    sys.exit(run(args))


if __name__ == "__main__":
    main()
