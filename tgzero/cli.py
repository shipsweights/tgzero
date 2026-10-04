"""
tgzero.__main__ / tgzero.cli
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unified CLI entry point.  Installed as the `tgzero` console script.

Usage
-----
tgzero send    --msg "…" [--silent] [--json]
tgzero ask     --prompt "…" [--buttons "A,B"] [--timeout N] [--json]
tgzero daemon  --allow-list "cmd1,cmd2" [--interval N]
tgzero run     "shell command"
tgzero tail    <file> [--filter "keyword"] [--label "name"]
tgzero bridge  [--ttl SECONDS]
tgzero hook                      (invoked by Claude Code, not by hand)
tgzero ping
tgzero version
"""

import argparse
import sys

from . import __version__


def _print_welcome() -> None:
    """Prints a friendly overview when tgzero is called with no arguments."""
    print(f"""
  tgzero v{__version__} — Zero-dependency, stdlib-only Telegram bridge

  Usage:  tgzero COMMAND [options]

  Commands:
    send      Send a one-way alert or notification
    ask       Pause script and wait for button-click approval
    daemon    Enable remote control: execute commands from Telegram
    run       Execute a command and send its output to Telegram
    tail      Stream a log file to Telegram in real time
    bridge    Run the Claude Code ↔ Telegram bridge (one per machine)
    hook      Claude Code hook entry point — not meant to be run by hand
    ping      Verify API credentials and network connectivity
    version   Print the installed tgzero version

  Examples:
    tgzero send -m "Backup complete"
    tgzero ask -p "Deploy to prod?" -b "Deploy,Abort"
    tgzero daemon --allow-list "status,reboot"
    tgzero run "df -h"
    tgzero tail /var/log/nginx/error.log --filter "error,warn"
    tgzero bridge

  Config:   TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in telegram.env or environment.

  Run  tgzero COMMAND --help  for full options.
""")


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
    subparsers.required = False  # We handle the no-command case ourselves

    # -------------------------------------------------------------------------
    # tgzero send
    # -------------------------------------------------------------------------
    send_p = subparsers.add_parser(
        "send",
        help="Send a one-way alert or notification.",
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
        help="Pause script and wait for button-click approval.",
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
        help="Enable remote control: execute commands from Telegram.",
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

    # -------------------------------------------------------------------------
    # tgzero run
    # -------------------------------------------------------------------------
    run_p = subparsers.add_parser(
        "run",
        help="Execute a command and send its output to Telegram.",
        description=(
            "Runs a shell command locally and sends the output, exit code,\n"
            "and elapsed time to Telegram when it completes.\n\n"
            "Example:\n"
            "  tgzero run \"df -h\"\n"
            "  tgzero run \"pg_dump mydb > backup.sql\"\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_p.add_argument(
        "command_str",
        metavar="COMMAND",
        help="Shell command to execute (quote if it contains spaces or flags).",
    )
    run_p.add_argument(
        "--timeout", "-t",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Kill the command if it runs longer than this (default: 300s).",
    )

    # -------------------------------------------------------------------------
    # tgzero tail
    # -------------------------------------------------------------------------
    tail_p = subparsers.add_parser(
        "tail",
        help="Stream a log file to Telegram in real time.",
        description=(
            "Watches a file for new lines and forwards them to Telegram.\n"
            "Seeks to the end on startup — does not replay existing content.\n"
            "Lines are batched to avoid flooding the Telegram API.\n\n"
            "Example:\n"
            "  tgzero tail /var/log/nginx/error.log\n"
            "  tgzero tail /var/log/app.log --filter \"error,critical\" --label \"app\"\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tail_p.add_argument(
        "file",
        metavar="FILE",
        help="Path to the file to watch.",
    )
    tail_p.add_argument(
        "--filter", "-f",
        default=None,
        metavar="KEYWORDS",
        help="Comma-separated keywords; only matching lines are forwarded (case-insensitive).",
    )
    tail_p.add_argument(
        "--label", "-l",
        default=None,
        metavar="NAME",
        help="Display name shown in Telegram messages (defaults to the file path).",
    )

    # -------------------------------------------------------------------------
    # tgzero bridge
    # -------------------------------------------------------------------------
    bridge_p = subparsers.add_parser(
        "bridge",
        help="Run the Claude Code ↔ Telegram bridge (one instance per machine).",
        description=(
            "Long-running process that turns `tgzero hook` requests into\n"
            "Telegram messages and routes replies back into the originating\n"
            "terminal via tmux. This is the ONLY process that should call\n"
            "Telegram's getUpdates for this chat while it runs — don't run\n"
            "`tgzero ask` or `tgzero daemon` against the same token/chat at\n"
            "the same time.\n\n"
            "See README, \"Claude Code integration\", for the Stop /\n"
            "UserPromptSubmit hook wiring this expects.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    bridge_p.add_argument(
        "--ttl",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Expire an unanswered prompt after this long (default: 21600 / 6h).",
    )

    # -------------------------------------------------------------------------
    # tgzero hook
    # -------------------------------------------------------------------------
    subparsers.add_parser(
        "hook",
        help="Claude Code hook entry point (not meant to be run by hand).",
        description=(
            "Reads a Claude Code hook payload (JSON) from stdin and writes a\n"
            "request for `tgzero bridge` to pick up. Takes no flags — wire it\n"
            "into Claude Code's settings.json as the command for the Stop and\n"
            "UserPromptSubmit hooks. See README, \"Claude Code integration\".\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # -------------------------------------------------------------------------
    # tgzero ping
    # -------------------------------------------------------------------------
    subparsers.add_parser(
        "ping",
        help="Verify API credentials and network connectivity.",
        description=(
            "Loads TELEGRAM_TOKEN and TELEGRAM_CHAT_ID, sends a test message,\n"
            "and confirms the connection is working.\n\n"
            "Exit codes:\n"
            "  0  Test message delivered successfully\n"
            "  1  Delivery failed (bad token, wrong chat ID, no network)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # -------------------------------------------------------------------------
    # tgzero version
    # -------------------------------------------------------------------------
    subparsers.add_parser(
        "version",
        help="Print the installed tgzero version.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    # No command supplied — print friendly overview instead of an error
    if not args.command:
        _print_welcome()
        sys.exit(0)

    if args.command == "version":
        print(f"tgzero {__version__}")
        sys.exit(0)

    if args.command == "ping":
        from .cmd_ping import run
    elif args.command == "send":
        from .cmd_send import run
    elif args.command == "ask":
        from .cmd_ask import run
    elif args.command == "daemon":
        from .cmd_daemon import run
    elif args.command == "run":
        from .cmd_run import run
    elif args.command == "tail":
        from .cmd_tail import run
    elif args.command == "bridge":
        from .cmd_bridge import run
    elif args.command == "hook":
        from .cmd_hook import run
    else:
        parser.print_help()
        sys.exit(1)

    sys.exit(run(args))


if __name__ == "__main__":
    main()
