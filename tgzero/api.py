"""
tgzero.api
~~~~~~~~~~
Thin, zero-dependency wrapper around the Telegram Bot HTTP API.
All network I/O lives here; higher layers never touch urllib directly.
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

# --- Terminal Styling ---
if sys.stdout.isatty():
    RED   = "\033[91m"
    GREEN = "\033[92m"
    RESET = "\033[0m"
else:
    RED = GREEN = RESET = ""

TELEGRAM_MAX_LENGTH = 4096
_BASE = "https://api.telegram.org/bot{token}/{method}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize(text: str) -> str:
    """Escapes HTML special characters for Telegram's HTML parse mode.

    Covers the four characters that have meaning in both tag bodies and
    attribute values, making the output safe to embed in either context:

        & → &amp;   (must be first to avoid double-escaping)
        < → &lt;
        > → &gt;
        " → &quot;
    """
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def truncate(text: str, max_length: int = TELEGRAM_MAX_LENGTH) -> str:
    """Truncates text to Telegram's hard character limit."""
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def _url(token: str, method: str) -> str:
    return _BASE.format(token=token, method=method)


def _post(url: str, payload: dict, timeout: int) -> dict | None:
    """Makes a POST request; returns parsed JSON body or None on error."""
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"{RED}Telegram API Error ({e.code}): {e.reason}{RESET}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"{RED}Connection Error: {e.reason}{RESET}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"{RED}Unexpected Error: {e}{RESET}", file=sys.stderr)
    return None


def _get(url: str, timeout: int) -> dict | None:
    """Makes a GET request; returns parsed JSON body or None on error."""
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"{RED}Telegram API Error ({e.code}): {e.reason}{RESET}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"{RED}Connection Error: {e.reason}{RESET}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"{RED}Unexpected Error: {e}{RESET}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

def send_message(
    token: str,
    chat_id: str,
    text: str,
    *,
    silent: bool = False,
    buttons: list[str] | None = None,
    timeout: int = 10,
) -> bool:
    """Sends a plain or button-enhanced message.

    Args:
        token:    Bot token.
        chat_id:  Destination chat ID.
        text:     Message body (will be truncated automatically; callers are
                  responsible for sanitizing any user-supplied content within
                  the text before passing it here).
        silent:   If True, the notification arrives without a sound.
        buttons:  Optional list of button labels rendered as an inline keyboard.
        timeout:  HTTP timeout in seconds.

    Returns:
        True on success, False on any error.
    """
    safe_text = truncate(text)

    payload: dict = {
        "chat_id":               chat_id,
        "text":                  safe_text,
        "parse_mode":            "HTML",
        "disable_notification":  silent,
    }

    if buttons:
        # Each button is its own column in a single row for compact display
        keyboard = {"inline_keyboard": [[
            {"text": label, "callback_data": label} for label in buttons
        ]]}
        payload["reply_markup"] = json.dumps(keyboard)

    result = _post(_url(token, "sendMessage"), payload, timeout)
    return result is not None and result.get("ok", False)


def answer_callback_query(token: str, callback_query_id: str, timeout: int = 10) -> None:
    """Acknowledges a button press so Telegram removes the loading spinner."""
    payload = {"callback_query_id": callback_query_id}
    _post(_url(token, "answerCallbackQuery"), payload, timeout)


def get_updates(
    token: str,
    offset: int | None = None,
    long_poll_timeout: int = 30,
    http_timeout: int | None = None,
) -> list[dict]:
    """Fetches pending updates via long polling.

    Args:
        token:              Bot token.
        offset:             Acknowledge all updates below this ID.
        long_poll_timeout:  Seconds the Telegram server waits before returning empty.
        http_timeout:       Local socket timeout (defaults to long_poll_timeout + 5).

    Returns:
        List of update objects; empty list on any error.
    """
    if http_timeout is None:
        http_timeout = long_poll_timeout + 5

    url = f"{_url(token, 'getUpdates')}?timeout={long_poll_timeout}"
    if offset is not None:
        url += f"&offset={offset}"

    result = _get(url, http_timeout)
    if result and result.get("ok"):
        return result.get("result", [])
    return []
