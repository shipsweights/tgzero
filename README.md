# tgzero

> Zero-dependency, stdlib-only Telegram bridge for two-way CLI automation.
> Simple alerts or interactive command-and-control using nothing but the Python standard library.

| Command | What it does |
|---------|--------------|
| [`send`](#tgzero-send) | One-way alert |
| [`ask`](#tgzero-ask) | Block a script until you tap a button |
| [`run`](#tgzero-run) | Run a command locally, send its output |
| [`tail`](#tgzero-tail) | Stream a log file |
| [`daemon`](#tgzero-daemon) | Run allow-listed commands sent from Telegram |
| [`bridge` / `hook`](#claude-code-integration) | Answer Claude Code sessions from your phone |
| `ping` / `version` | Check connectivity / print version |

---

## Quick start

```bash
pip install tgzero
```

Create `telegram.env` in your working directory (or export the variables):

```bash
TELEGRAM_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi
TELEGRAM_CHAT_ID=987654321
```

```bash
chmod 600 telegram.env
tgzero ping        # a test message should arrive
```

> **`TELEGRAM_CHAT_ID` is your user ID, not the bot's.** Send any message to
> your bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and
> copy `message.chat.id` (or ask `@userinfobot`). Using the bot's own ID fails
> with `403: the bot can't send messages to the bot`.

---

## Commands

### tgzero send

```bash
tgzero send -m "✅ Weekly backup uploaded to S3."
tgzero send -m "Server load is high (85%)" --silent   # no sound
tgzero send -m "Done" --json
# → {"status": "success", "action": "send", "exit_code": 0, "latency_ms": 312}
```

### tgzero ask

Pauses your script until you tap a button. First button → exit `0`.

```bash
if tgzero ask -p "Deploy to production?" -b "Deploy,Abort" --timeout 300; then
    ./deploy.sh
fi

# Multiple choices — read the label from JSON
ENV=$(tgzero ask -p "Environment?" -b "Staging,Prod,Dev" --json \
      | python3 -c "import sys,json; print(json.load(sys.stdin)['reply_string'])")
```

| Exit | Meaning |
|------|---------|
| `0` | First button |
| `1` | Other button (label printed to stdout) |
| `2` | Timeout |
| `3` | Network / API failure |
| `4` | Another `ask` holds the lock |
| `5` | Terminated (`SIGTERM` / `SIGINT`) |

### tgzero run

Runs a command and sends output, exit code and duration. Default timeout: 300 s.

```bash
tgzero run "df -h"
tgzero run --timeout 60 "journalctl -u nginx --since today --no-pager"
```

> **No shell.** Commands go through `shlex.split` with `shell=False`, so pipes,
> redirects and builtins (`|`, `>`, `exit`) don't work. Use the tool's own
> flags instead, e.g. `pg_dump mydb -f backup.sql`.

What arrives in Telegram:

```
✅ $ df -h
Exit: 0 · Took: 0.1s
Filesystem      Size  Used Avail Use% Mounted on      ← monospace block
/dev/sda1        50G   12G   36G  25% /
```

Output longer than 40 lines (or Telegram's 4096-char limit) is shown as a
preview (first 15 + last 10 lines) and the full text is attached as `output.txt`.

| Exit | Meaning |
|------|---------|
| `0` | Done, result delivered |
| `1` | Command not found / config missing |
| `2` | Timed out |
| `3` | Network / API failure |

### tgzero tail

Forwards new lines of a file (starts at the end, batches lines).

```bash
tgzero tail /var/log/app.log --filter "error,critical" --label "app"
```

Stop with `Ctrl+C` / `SIGTERM`. A shutdown notice is sent.

### tgzero daemon

Runs commands sent from Telegram, but only those on the allow-list.
Matching is exact: the message must equal an entry character for character.

```bash
tgzero daemon --allow-list "df -h,uptime,systemctl status nginx" --interval 3
```

Other commands get `⚠️ Command not permitted`. Commands are rate-limited (2 s cooldown).
Long output works as in `run`.

<details>
<summary>systemd unit</summary>

```ini
[Unit]
Description=tgzero Telegram daemon
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/myapp
EnvironmentFile=/opt/myapp/telegram.env
ExecStart=tgzero daemon --allow-list "df -h,uptime"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```
</details>

---

## Claude Code integration

Get a Telegram message when a Claude Code session stops and needs you; reply
(Telegram **reply**) and the text is typed into that terminal.

1. Run Claude Code inside **tmux** (replies are injected via `tmux send-keys`).
2. Add the hook to `~/.claude/settings.json`:
   ```json
   {
     "hooks": {
       "Stop":             [{ "hooks": [{ "type": "command", "command": "tgzero hook" }] }],
       "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "tgzero hook" }] }]
     }
   }
   ```
3. Start one bridge per machine: `tgzero bridge` (`--ttl SECONDS` expires
   unanswered prompts, default 6 h).

If you answer on the PC instead, the Telegram message is marked
"✅ Answered on PC" and its buttons are removed.

> `bridge` must be the only process polling this bot. Don't run `ask` or
> `daemon` with the same token at the same time.

---

## Message icons

| Icon | Meaning |
|------|---------|
| ✅ | Exit code 0 |
| ❌ | Non-zero exit code |
| ⏱ | Timeout |
| ⚠️ | Command not found / error / not permitted |

System notices (start, stop, rate limit) never use the `$ command` header.

---

## Security notes

- Only messages from `TELEGRAM_CHAT_ID` are processed; others are logged and ignored.
- Never `shell=True`. User input is never passed to a shell.
- All text sent as HTML is escaped (`&`, `<`, `>`, `"`); ANSI colour codes are stripped.
- `telegram.env` and its directory are checked for unsafe permissions on startup.
- The `ask` lock lives in a per-user `0700` directory and is `chmod 600`.
- Output is sent **as-is**: secrets printed by a command will reach Telegram.
