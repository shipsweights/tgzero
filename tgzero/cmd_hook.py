"""
tgzero.cmd_hook
~~~~~~~~~~~~~~~
Implements `tgzero hook` — the fast, non-blocking producer side of the
Claude Code ↔ Telegram bridge. This is invoked directly by Claude Code's
own hook mechanism, never by a human (see README, "Claude Code
integration", for the settings.json wiring).

Reads one JSON object from Claude Code on stdin and:

  * on Stop             — writes a new pending request (last assistant
                           message + short rolling context) for
                           `tgzero bridge` to pick up and send to Telegram.
  * on UserPromptSubmit  — marks any still-open request(s) for this session
                           as answered on the PC, so `tgzero bridge` can
                           update the Telegram message instead of racing a
                           stale Telegram reply against what you just typed.
  * anything else        — ignored.

This command does NOT talk to Telegram itself and does NOT poll — all
network I/O happens in `tgzero bridge`. That split matters: a hook runs
inline in Claude Code's own control flow, so it must return in milliseconds
and must never fail Claude Code's turn. Exit code is always 0 (even on a
malformed/empty stdin payload or an internal error) for the same reason —
there is no useful way for Claude Code to react to a bridge wiring problem
mid-conversation, and failing here would be strictly worse than a silently
missed notification.
"""

import json
import os
import sys
import time

from . import state

_MAX_CONTEXT_CHARS = 3500   # kept comfortably inside Telegram's 4096 char cap
                             # once the project header / footer are added
_MAX_TURNS_BACK     = 6     # how many recent transcript entries to scan


def _read_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _extract_text(message: dict) -> str:
    """Best-effort plain text from one transcript message entry.

    Claude Code transcript message content is either a bare string or a
    list of content blocks (text / tool_use / tool_result / ...); only text
    blocks are human-readable context, so tool payloads are skipped here —
    a raw tool_use/tool_result block is usually either noise or something
    better sent as a file than squeezed into a chat bubble, which is a
    problem for a later iteration, not this one.
    """
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return ""


def _read_last_turns(transcript_path: str, max_turns: int = _MAX_TURNS_BACK) -> tuple[str, str]:
    """Returns (last_assistant_text, context_text) from the JSONL transcript.

    context_text is a short "user asked / assistant answered" excerpt built
    from the last few turns — enough to show what's going on in a single
    Telegram message without pulling in the whole session. Deliberately
    tolerant of transcript lines it can't parse: a transcript format change
    should degrade to "no context shown" here, not crash the hook.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return "", ""

    entries: list[dict] = []
    try:
        with open(transcript_path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return "", ""

    if not entries:
        return "", ""

    turns: list[str] = []
    last_assistant = ""

    for entry in entries[-max_turns:]:
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        text = _extract_text(msg).strip()
        if not text:
            continue
        if role == "assistant":
            last_assistant = text
            turns.append(f"🤖 {text}")
        elif role == "user":
            turns.append(f"🧑 {text}")

    context = "\n\n".join(turns)
    if len(context) > _MAX_CONTEXT_CHARS:
        context = context[-_MAX_CONTEXT_CHARS:]

    return last_assistant, context


def _handle_stop(payload: dict) -> None:
    session_id = payload.get("session_id", "")
    cwd        = payload.get("cwd") or os.getcwd()
    transcript = payload.get("transcript_path", "")

    last_assistant, context = _read_last_turns(transcript)
    if not last_assistant:
        # Nothing readable/worth surfacing — don't send an empty prompt.
        return

    req_id = state.new_id()
    state.write(req_id, {
        "id":            req_id,
        "status":        "pending",         # → "sent" once the bridge delivers it
        "session_id":    session_id,
        "cwd":           cwd,
        "project":       os.path.basename(cwd.rstrip("/")) or cwd,
        "pane":          os.environ.get("TMUX_PANE") or "",
        "created_at":    time.time(),
        "prompt_text":   last_assistant,
        "context_text":  context,
        "chat_id":       "",
        "message_id":    None,
        "answer":        None,
        "answered_via":  None,
    })


def _handle_user_prompt_submit(payload: dict) -> None:
    session_id = payload.get("session_id", "")
    if not session_id:
        return

    for req in state.list_all():
        if req.get("session_id") != session_id:
            continue
        if req.get("status") not in ("pending", "sent"):
            continue
        state.update(
            req["id"],
            status="answered_pc",
            answered_via="pc",
            answer=payload.get("prompt", ""),
        )


def run(args) -> int:  # noqa: ARG001 — dispatcher passes parsed argparse args; unused here
    """Entry point called by the CLI dispatcher. `tgzero hook` takes no CLI
    flags of its own — the hook payload comes from Claude Code on stdin."""
    payload = _read_stdin_json()
    event   = payload.get("hook_event_name", "")

    try:
        if event == "Stop":
            _handle_stop(payload)
        elif event == "UserPromptSubmit":
            _handle_user_prompt_submit(payload)
    except Exception:  # noqa: BLE001
        # A hook must never break Claude Code's own control flow — see the
        # module docstring. Nothing useful to report back to Claude Code
        # here; the bridge's own stderr is where this would be diagnosed.
        pass

    return 0
