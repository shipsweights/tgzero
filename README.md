# tgzero

> Lightweight, zero-dependency Telegram C2 bridge.  
> Bridges server-side processes with a designated Telegram chat — from fire-and-forget alerts to interactive deployment gatekeepers.

---

## Installation

```bash
pip install tgzero
```

## Configuration

Create a `telegram.env` file in your working directory (or export the variables in your shell):

```bash
TELEGRAM_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi
TELEGRAM_CHAT_ID=1234567890
```

Secure the file:

```bash
chmod 600 telegram.env
```

---

## Commands

### `tgzero send` — Fire-and-forget notification

```bash
# Basic alert
tgzero send --msg "✅ Weekly backup uploaded to S3."

# Silent (no sound on phone)
tgzero send -m "Server load is high (85%)" --silent

# Machine-readable output
tgzero send -m "Done" --json
# → {"status": "success", "action": "send", "exit_code": 0, "latency_ms": 312}
```

---

### `tgzero ask` — Interactive gatekeeper

Pauses your script until you tap a button in Telegram.

```bash
# Simple yes/no gate (default OK button)
tgzero ask --prompt "Ready to restart nginx?"

# Custom buttons — first button = exit 0, any other = exit 1
if tgzero ask --prompt "Deploy to production?" --buttons "Deploy,Abort"; then
    ./deploy.sh
    tgzero send -m "🚀 Deployment successful!"
else
    echo "Aborted."
fi

# With timeout
tgzero ask -p "Approve migration?" -b "Approve,Skip" --timeout 300

# Multi-branch with --json
RESULT=$(tgzero ask -p "Choose environment" -b "Staging,Prod,Dev" --json)
ENV=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['reply_string'])")
echo "Deploying to: $ENV"
```

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | First button clicked (success / go) |
| `1` | Any other button clicked — literal label printed to stdout |
| `2` | Timeout — no reply within `--timeout` seconds |
| `3` | Network / API failure |
| `4` | Queue timeout — another `ask` is holding the lock |
| `5` | Terminated by `SIGTERM` / `SIGINT` |

---

### `tgzero daemon` — Persistent remote-control agent

Runs in the background (systemd / Docker) and executes allow-listed commands sent via Telegram.

```bash
tgzero daemon --allow-list "status,reboot,clear-logs" --interval 3
```

**From your phone:** type `status` → bot replies with command output.  
Unrecognised commands get a `⚠️ Command not permitted` reply.

#### systemd unit example

```ini
[Unit]
Description=tgzero Telegram C2 daemon
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/myapp
EnvironmentFile=/opt/myapp/telegram.env
ExecStart=tgzero daemon --allow-list "status,restart-nginx,clear-logs"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Security Notes

- All messages are validated against `TELEGRAM_CHAT_ID`. Messages from any other sender are logged and ignored.
- The `daemon` allow-list uses exact string matching — no shell interpolation.
- HTML special characters are automatically escaped before sending.
- Messages longer than 4096 characters are cleanly truncated.
- The `.env` file permissions are checked on startup; a warning is printed if the file is world-readable.
