"""
tgzero.api
~~~~~~~~~~
Thin, zero-dependency wrapper around the Telegram Bot HTTP API.
All network I/O lives here; higher layers never touch urllib directly.
"""

import json
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

# --- Terminal Styling ---
if sys.stdout.isatty():
    RED   = "\033[91m"
    GREEN = "\033[92m"
    RESET = "\033[0m"
else:
    RED = GREEN = RESET = ""

TELEGRAM_MAX_LENGTH = 4096
_BASE = "https://api.telegram.org/bot{token}/{method}"

# Matches CSI-style ANSI escape sequences (colors, cursor movement, etc.) —
# e.g. "\x1b[91m", "\x1b[0m", "\x1b[2K". Telegram's HTML parse mode has no
# concept of terminal color; left unstripped, these show up as literal
# garbage characters in a <pre> block instead of being interpreted.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


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


def strip_ansi(text: str) -> str:
    """Removes ANSI escape sequences (terminal color/cursor codes).

    Any command or log output piped into tgzero may carry color codes meant
    for a real terminal (colored CLI tools, `ls --color`, colored log
    formatters...). Telegram's HTML parse mode cannot render them — call this
    before sanitize()/<pre> so they don't show up as raw control characters.
    """
    return _ANSI_RE.sub("", text)


def is_long(output: str, *, max_lines: int = 40, max_output: int = 3500) -> bool:
    """True if output is too long to show inline (callers then attach the full text)."""
    raw = strip_ansi(output) if output else ""
    return raw.count("\n") + 1 > max_lines or len(sanitize(raw)) > max_output


def _preview(text: str, max_lines: int, head: int = 15, tail: int = 10) -> str:
    """First `head` and last `tail` lines with an omission marker, if text has > max_lines lines."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    omitted = len(lines) - head - tail
    return "\n".join(lines[:head] + [f"... [{omitted} lines omitted] ..."] + lines[-tail:])


def format_command_block(
    command: str,
    output: str,
    *,
    status_emoji: str | None = None,
    meta: str | None = None,
    max_output: int = 3500,
    max_lines: int = 40,
    truncated_note: str = "output truncated",
) -> str:
    """Builds a terminal-like HTML block: "$ command" header + <pre> output.

    This is the single place that decides what "looks like a terminal" means
    inside a Telegram message, so `run`, `daemon`, and `tail` render command
    output consistently:
        [status_emoji] $ command
        [meta line, e.g. "Exit: 0 · Took: 1.2s"]
        <pre>output, ANSI-stripped and HTML-escaped</pre>

    Output is ANSI-stripped and HTML-sanitized automatically — callers must
    NOT pre-sanitize `output` (double-escaping would corrupt it); `command`
    and `meta` likewise must be raw/pre-sanitized by the caller only if they
    build it themselves, since this function sanitizes `command` too but
    passes `meta` through unchanged (callers construct it from trusted,
    already-safe strings like "Exit: 0 · Took: 1.2s").

    Args:
        command:       The command/line label shown after "$ ".
        output:        Raw command output (may contain ANSI codes).
        status_emoji:  Optional leading emoji, e.g. "✅" / "❌" / "⏱".
        meta:          Optional second line (exit code, timing, etc.) — HTML
                       already safe, inserted as-is.
        max_lines:     Longer output is shown as head + tail preview.
        truncated_note: Italic note under a truncated block (e.g. "full output attached").
        max_output:    Output is truncated to this many characters before
                       being wrapped in <pre>, leaving headroom for the
                       header within Telegram's 4096-char message limit.

    Returns:
        A single HTML string ready to pass to send_message().
    """
    raw = strip_ansi(output) if output else ""
    truncated = False
    if is_long(raw, max_lines=max_lines, max_output=max_output):
        raw = _preview(raw, max_lines)
        truncated = True
    # Trim the RAW text (not the escaped one) so we never cut an entity like
    # "&amp;" in half; re-check because escaping makes the text longer.
    while len(sanitize(raw)) > max_output:
        raw = raw[:int(len(raw) * 0.9)]
        truncated = True
    clean = sanitize(raw)

    header = f"<b>$ {sanitize(command)}</b>"
    if status_emoji:
        header = f"{status_emoji} {header}"

    lines = [header]
    if meta:
        lines.append(meta)

    if clean.strip():
        body = f"<pre>{clean}</pre>"
        if truncated:
            body += f"\n<i>... {truncated_note}</i>"
    else:
        body = "<pre>(no output)</pre>"
    lines.append(body)

    return "\n".join(lines)


def ok(result: dict | None) -> bool:
    """True if a call returned a successful Telegram API response.

    Every public function below now returns the *parsed response body* (or
    None on transport failure) instead of a bare bool, so callers can also
    read message_id, description, etc. This helper keeps the common
    success/failure check a one-liner.
    """
    return isinstance(result, dict) and result.get("ok", False)


def message_id(result: dict | None) -> int | None:
    """Extracts the message_id from a successful sendMessage/editMessage* result."""
    if ok(result):
        return result.get("result", {}).get("message_id")
    return None


def make_callback_prefix() -> str:
    """Short random id used to namespace a message's button callback_data.

    callback_data is capped at 64 bytes by Telegram and, previously, this
    module used the raw button label as callback_data — identical labels
    across different prompts (e.g. two "OK" buttons from two concurrent
    scripts) were therefore indistinguishable, and a long/unicode label could
    silently exceed the byte limit. Encoding "<prefix>:<index>" instead keeps
    every callback small, unique per-message, and independent of label text.
    """
    return secrets.token_hex(4)


def _url(token: str, method: str) -> str:
    return _BASE.format(token=token, method=method)


def _normalize(payload: dict) -> dict:
    """Converts Python bools to Telegram's expected lowercase JSON-style strings.

    urllib.parse.urlencode(str(True)) produces "True"/"False" (Python repr),
    but the Telegram Bot API's form-urlencoded parameters — e.g.
    disable_notification, allow_sending_without_reply — require the literal
    strings "true"/"false". Left unconverted, `--silent` (and reply-threading)
    would silently never take effect even though the call "succeeds".
    """
    return {
        k: ("true" if v is True else "false" if v is False else v)
        for k, v in payload.items()
    }


def _post(url: str, payload: dict, timeout: int) -> dict | None:
    """Makes a POST request; returns parsed JSON body or None on transport error."""
    data = urllib.parse.urlencode(_normalize(payload)).encode("utf-8")
    req  = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
            print(f"{RED}Telegram API Error ({e.code}): {body.get('description', e.reason)}{RESET}",
                  file=sys.stderr)
            return body
        except Exception:  # noqa: BLE001
            print(f"{RED}Telegram API Error ({e.code}): {e.reason}{RESET}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"{RED}Connection Error: {e.reason}{RESET}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"{RED}Unexpected Error: {e}{RESET}", file=sys.stderr)
    return None


def _get(url: str, timeout: int) -> dict | None:
    """Makes a GET request; returns parsed JSON body or None on transport error."""
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
            print(f"{RED}Telegram API Error ({e.code}): {body.get('description', e.reason)}{RESET}",
                  file=sys.stderr)
            return body
        except Exception:  # noqa: BLE001
            print(f"{RED}Telegram API Error ({e.code}): {e.reason}{RESET}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"{RED}Connection Error: {e.reason}{RESET}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"{RED}Unexpected Error: {e}{RESET}", file=sys.stderr)
    return None


def _multipart_post(url: str, fields: dict, file_field: str, filename: str,
                     file_bytes: bytes, timeout: int) -> dict | None:
    """Minimal stdlib multipart/form-data POST (no external deps)."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []

    for key, value in _normalize(fields).items():
        if value is None:
            continue
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8")
        )

    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
    )
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    body = b"".join(parts)
    req = urllib.request.Request(url, data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body_json = json.loads(e.read().decode())
            print(f"{RED}Telegram API Error ({e.code}): {body_json.get('description', e.reason)}{RESET}",
                  file=sys.stderr)
            return body_json
        except Exception:  # noqa: BLE001
            print(f"{RED}Telegram API Error ({e.code}): {e.reason}{RESET}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"{RED}Connection Error: {e.reason}{RESET}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"{RED}Unexpected Error: {e}{RESET}", file=sys.stderr)
    return None


def _keyboard_for(buttons: list[str], callback_prefix: str) -> dict:
    """Builds an inline_keyboard whose callback_data is '<prefix>:<index>'.

    Buttons are placed two to a row so longer option lists (e.g. AskUserQuestion
    choices) stay readable instead of forming one very wide row.
    """
    cells = [{"text": label, "callback_data": f"{callback_prefix}:{i}"}
             for i, label in enumerate(buttons)]
    rows = [cells[i:i + 2] for i in range(0, len(cells), 2)]
    return {"inline_keyboard": rows}


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
    callback_prefix: str | None = None,
    reply_to_message_id: int | None = None,
    timeout: int = 10,
) -> dict | None:
    """Sends a plain or button-enhanced message.

    Args:
        token:                Bot token.
        chat_id:               Destination chat ID.
        text:                  Message body (truncated automatically; callers
                               are responsible for sanitizing any
                               user-supplied content within the text before
                               passing it here).
        silent:                If True, the notification arrives without a sound.
        buttons:               Optional list of button labels rendered as an
                               inline keyboard. callback_data is generated as
                               "<prefix>:<index>" — never the raw label — so
                               the caller must keep its own `buttons` list
                               around to translate an index back to a label.
        callback_prefix:       Namespace for this message's buttons. Defaults
                               to a fresh random token (see
                               make_callback_prefix); pass one explicitly to
                               reuse/predict it (e.g. correlating with a
                               request id).
        reply_to_message_id:   If set, thread this message as a reply.
        timeout:               HTTP timeout in seconds.

    Returns:
        The parsed Telegram API response (dict, with "ok"/"result"), or None
        on transport failure. Use ok(result) / message_id(result) to inspect it.
    """
    safe_text = truncate(text)

    payload: dict = {
        "chat_id":               chat_id,
        "text":                  safe_text,
        "parse_mode":            "HTML",
        "disable_notification":  silent,
    }

    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
        payload["allow_sending_without_reply"] = True

    if buttons:
        prefix = callback_prefix or make_callback_prefix()
        payload["reply_markup"] = json.dumps(_keyboard_for(buttons, prefix))

    return _post(_url(token, "sendMessage"), payload, timeout)


def edit_message_text(
    token: str,
    chat_id: str,
    msg_id: int,
    text: str,
    *,
    buttons: list[str] | None = None,
    callback_prefix: str | None = None,
    timeout: int = 10,
) -> dict | None:
    """Edits an existing message's text (and optionally its keyboard).

    Used to turn a pending prompt into a resolved one in place — e.g.
    replacing "🤖 Deploy to prod? [Deploy] [Abort]" with
    "✅ Deploy to prod? → Deploy (answered on PC)" and dropping the buttons —
    instead of sending a second message.
    Pass buttons=[] (empty, not None) to clear any existing keyboard.
    """
    safe_text = truncate(text)
    payload: dict = {
        "chat_id":    chat_id,
        "message_id": msg_id,
        "text":       safe_text,
        "parse_mode": "HTML",
    }
    if buttons:
        prefix = callback_prefix or make_callback_prefix()
        payload["reply_markup"] = json.dumps(_keyboard_for(buttons, prefix))
    elif buttons is not None:
        # Explicit empty list: remove the keyboard entirely.
        payload["reply_markup"] = json.dumps({"inline_keyboard": []})

    return _post(_url(token, "editMessageText"), payload, timeout)


def edit_message_reply_markup(
    token: str,
    chat_id: str,
    msg_id: int,
    *,
    buttons: list[str] | None = None,
    callback_prefix: str | None = None,
    timeout: int = 10,
) -> dict | None:
    """Replaces (or, if buttons is None/empty, clears) a message's inline keyboard."""
    payload: dict = {"chat_id": chat_id, "message_id": msg_id}
    if buttons:
        prefix = callback_prefix or make_callback_prefix()
        payload["reply_markup"] = json.dumps(_keyboard_for(buttons, prefix))
    else:
        payload["reply_markup"] = json.dumps({"inline_keyboard": []})

    return _post(_url(token, "editMessageReplyMarkup"), payload, timeout)


def send_document(
    token: str,
    chat_id: str,
    filename: str,
    content: bytes | str,
    *,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
    timeout: int = 20,
) -> dict | None:
    """Sends content as a file attachment (e.g. full context too long to fit a message).

    content may be str (encoded as UTF-8) or raw bytes.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")

    fields: dict = {"chat_id": chat_id}
    if caption:
        fields["caption"] = truncate(caption, 1024)
        fields["parse_mode"] = "HTML"
    if reply_to_message_id is not None:
        fields["reply_to_message_id"] = reply_to_message_id
        fields["allow_sending_without_reply"] = True

    return _multipart_post(_url(token, "sendDocument"), fields, "document",
                            filename, content, timeout)


def answer_callback_query(token: str, callback_query_id: str, text: str | None = None,
                           timeout: int = 10) -> dict | None:
    """Acknowledges a button press so Telegram removes the loading spinner."""
    payload: dict = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return _post(_url(token, "answerCallbackQuery"), payload, timeout)


def get_updates(
    token: str,
    offset: int | None = None,
    long_poll_timeout: int = 30,
    http_timeout: int | None = None,
) -> list[dict] | None:
    """Fetches pending updates via long polling.

    Args:
        token:              Bot token.
        offset:             Acknowledge all updates below this ID.
        long_poll_timeout:  Seconds the Telegram server waits before returning empty.
        http_timeout:       Local socket timeout (defaults to long_poll_timeout + 5).

    Returns:
        List of update objects (possibly empty, meaning "no new updates — but
        the call succeeded"), or None if the call itself failed (network
        error, bad token, etc). Callers MUST distinguish `None` from `[]`:
        treating both the same hides real connectivity/auth failures as
        silent "nothing happened" loops.
    """
    if http_timeout is None:
        http_timeout = long_poll_timeout + 5

    url = f"{_url(token, 'getUpdates')}?timeout={long_poll_timeout}"
    if offset is not None:
        url += f"&offset={offset}"

    result = _get(url, http_timeout)
    if result is None:
        return None
    if result.get("ok"):
        return result.get("result", [])
    return None
