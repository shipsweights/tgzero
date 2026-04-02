# tgzero

> Zero-dependency, stdlib-only Telegram bridge for two-way CLI automation.
> Simple alerts or interactive command-and-control using nothing but the Python standard library.

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

Verify everything is working:

```bash
tgzero ping
```

---

## Commands

### `tgzero send` — Send a one-way alert or notification

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

### `tgzero ask` — Pause script and wait for button-click approval

Pauses your script until you tap a button in Telegram.

```bash
# Simple gate — default OK button
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

### `tgzero daemon` — Enable remote control: execute commands from Telegram

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

### `tgzero run` — Execute a command and send its output to Telegram

Runs any shell command locally and sends the output, exit code, and elapsed time
to Telegram when it completes. Useful for one-shot admin tasks you want to
trigger remotely and get results back from.

```bash
# Check disk usage
tgzero run "df -h"

# Run a database backup and get notified when done
tgzero run "pg_dump mydb > /backups/mydb.sql"

# Any command with flags — quote the whole thing
tgzero run "journalctl -u nginx --since today --no-pager"
```

**What you receive in Telegram:**
```
✅ $ df -h
Exit: 0 · Started: 14:32:01 · Took: 0.1s

Filesystem      Size  Used Avail Use% Mounted on
/dev/sda1        50G   12G   36G  25% /
...
```

---

### `tgzero tail` — Stream a log file to Telegram in real time

Watches a file for new lines and forwards them to Telegram. Seeks to the end
on startup — does not replay existing content. Lines are batched to avoid
flooding the API.

```bash
# Watch an nginx error log
tgzero tail /var/log/nginx/error.log

# Forward only lines containing "error" or "critical"
tgzero tail /var/log/app.log --filter "error,critical"

# Use a friendly label instead of the full file path in Telegram messages
tgzero tail /var/log/app.log --filter "error,warn" --label "app"
```

Stop with `Ctrl+C` or `SIGTERM` — the bot sends a shutdown notification to Telegram.

---

### `tgzero ping` — Verify API credentials and network connectivity

Sends a test message to confirm your token, chat ID, and network are all working.
The first command to run after initial setup.

```bash
tgzero ping
# Checking credentials...
#   Token:    1234567890...  (truncated for safety)
#   Chat ID:  1234567890
# Sending test message...
# Ping successful! Check your Telegram for the test message.
```

---

### `tgzero version` — Print the installed tgzero version

```bash
tgzero version
# tgzero 0.2.1

# Also available as a flag
tgzero --version
```

---

## Security Notes

- All messages are validated against `TELEGRAM_CHAT_ID`. Messages from any other sender are logged and ignored.
- The `daemon` allow-list uses exact string matching — no shell interpolation.
- `run` and `daemon` use `shlex.split` + `shell=False` — user input is never passed to a shell.
- HTML special characters are automatically escaped before sending.
- Messages longer than 4096 characters are cleanly truncated.
- The `.env` file permissions are checked on startup; a warning is printed if the file is world-readable.
