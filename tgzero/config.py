"""
tgzero.config
~~~~~~~~~~~~~
Loads and validates environment configuration from a .env file or
shell environment variables.
"""

import os
import stat
import sys


class ConfigError(RuntimeError):
    """Raised for unrecoverable config problems (e.g. unsafe .env permissions
    in strict mode). Never calls sys.exit() itself — a long-running caller
    (the future `bridge`) needs to catch this and keep running (log + retry
    on next reload) rather than have the whole process killed from inside a
    helper function. One-shot CLI commands get the old exit(1) behaviour via
    load_config()'s default exit_on_error=True, which converts this into
    sys.exit(1) at the single call site that knows it's safe to do so."""

# --- Terminal Styling ---
# Disable ANSI codes when output is redirected to a file or pipe
if sys.stdout.isatty():
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    RESET  = "\033[0m"
else:
    RED = YELLOW = RESET = ""


def _check_env_file_permissions(filepath: str, strict: bool) -> None:
    """Warns (or raises ConfigError, in strict mode) when the .env file is
    too permissive.

    Checks both the file itself and its parent directory — a world-readable
    directory leaks the file's existence and may allow path traversal on some
    filesystems.
    """
    try:
        file_mode = os.stat(filepath).st_mode
        dir_mode  = os.stat(os.path.dirname(os.path.abspath(filepath))).st_mode
    except OSError:
        return

    issues: list[str] = []

    if file_mode & (stat.S_IRGRP | stat.S_IROTH):
        issues.append(
            f"'{filepath}' is readable by group/others — run: chmod 600 {filepath}"
        )
    if dir_mode & (stat.S_IWGRP | stat.S_IWOTH):
        issues.append(
            f"parent directory of '{filepath}' is group/world-writable"
        )

    for issue in issues:
        if strict:
            # Print to stderr so it isn't swallowed by --json pipelines
            print(f"{RED}Error: {issue}{RESET}", file=sys.stderr)
        else:
            print(f"{YELLOW}Warning: {issue}{RESET}", file=sys.stderr)

    if strict and issues:
        raise ConfigError("; ".join(issues))


def manual_load_dotenv(filepath: str, *, strict: bool = False, force: bool = False) -> None:
    """Loads variables from a .env file into the environment.

    Args:
        filepath: Path to the env file.
        strict:   If True, exit(1) when file permissions are too permissive
                  instead of merely warning.  Mirrors ssh's StrictModes.
        force:    If True, overwrite variables already present in the
                  environment with the file's values. Needed by long-running
                  processes (e.g. a future `daemon`/bridge reloading on
                  SIGHUP after `telegram.env` was rewritten by a token
                  rotation) — without it, a changed token would silently
                  never take effect for the life of the process.

    Behaviour:
    - Warns (or aborts in strict mode) if file/dir permissions are too open.
    - Strips inline comments from values  (e.g. TOKEN=abc # comment → abc)
    - Skips malformed lines gracefully.
    - By default does NOT overwrite variables already set in the environment
      (one-shot CLI commands keep letting a real shell export win); pass
      force=True to change that.
    """
    if not os.path.exists(filepath):
        return

    _check_env_file_permissions(filepath, strict)

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

            # Never overwrite an already-exported shell variable, unless the
            # caller explicitly asked for a reload.
            if key and (force or key not in os.environ):
                os.environ[key] = value


def load_config(*, strict: bool = False, force: bool = False,
                 exit_on_error: bool = True) -> tuple[str, str]:
    """Resolves TOKEN and CHAT_ID, checking the .env file in the CWD.

    Args:
        strict:        Passed through to manual_load_dotenv — raises
                       ConfigError on bad file perms when True.
        force:         Passed through to manual_load_dotenv — reload values
                       even if already present in the environment (see
                       manual_load_dotenv).
        exit_on_error: If True (the default — correct for every existing
                       one-shot CLI command), a ConfigError from strict-mode
                       permission checks is converted to sys.exit(1) here.
                       A long-running caller (the future `bridge`, reloading
                       on SIGHUP) should pass False and catch ConfigError
                       itself, so one bad reload doesn't kill the process.

    Returns:
        (TOKEN, CHAT_ID) — either may be empty string if not set.

    Raises:
        ConfigError: Only when exit_on_error=False and strict=True and the
                     .env file/directory permissions are unsafe.
    """
    try:
        manual_load_dotenv(
            os.path.join(os.getcwd(), "telegram.env"),
            strict=strict,
            force=force,
        )
    except ConfigError:
        if exit_on_error:
            sys.exit(1)
        raise

    token   = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print(
            f"{RED}Error: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID is not set. "
            f"Export them or place them in a 'telegram.env' file.{RESET}",
            file=sys.stderr,
        )

    return token, chat_id
