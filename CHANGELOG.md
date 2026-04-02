# Changelog

All notable changes to this project will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.2.2] - 2026-04-02

Security and reliability hardening across the codebase. No new features.

### Fixed

**`lock.py`** — high severity
- Replaced `os.path.exists()` + write sequence with `os.open(O_CREAT | O_EXCL)` —
  a single atomic syscall that eliminates the TOCTOU race condition on acquisition
- Lock file now stores `"<pid>:<nonce>"` (random 8-byte hex token); `release()`
  verifies both PID and nonce before removing — a slow waking process can no
  longer accidentally delete a new holder's lock
- Lock file is `chmod 600` immediately after creation; moved into a per-user
  directory (`$XDG_RUNTIME_DIR` → `$TMPDIR` → `/tmp/tgzero-<uid>` at `0700`)
  so other local users cannot observe or interfere with it

**`cmd_ask.py`** — high severity
- `_get_offset()` (formerly `_flush_pending_updates()`) is now called *before*
  `send_message()` — closes a window where a fast reply arriving between sending
  the prompt and establishing the offset would be silently discarded
- User-supplied `--prompt` text is now passed through `sanitize()` before being
  embedded in the HTML message

**`cmd_run.py`** — medium severity
- Added `DEFAULT_TIMEOUT = 300s` to `subprocess.run()` — previously the process
  could hang forever on a blocking command
- `subprocess.TimeoutExpired` is now caught; sends a Telegram notification and
  returns exit code `2`
- Command string and captured output are now passed through `sanitize()` before
  being embedded in HTML

**`cmd_daemon.py`**
- Added `_MIN_CMD_INTERVAL_S = 2.0` rate limit — rapid messages from the
  authorised chat are rejected with a cooldown reply instead of triggering
  back-to-back subprocess spawns
- Empty `sender_id` (channel posts, service messages) is now skipped before
  the auth check — previously would reach the auth check with an empty string
- All user-visible strings passed to Telegram are now wrapped in `sanitize()`
- Allow-list entries logged in quotes on startup for easier operator verification
- Security and warning output redirected to `stderr`

**`api.py`**
- `sanitize()` now also escapes `"` → `&quot;`, making it safe in both HTML
  body and attribute value contexts
- API error messages redirected to `stderr` so they do not pollute `--json`
  output pipelines

**`config.py`**
- Added `strict` mode: `load_config(strict=True)` exits with code `1` on
  insecure file permissions instead of warning (mirrors SSH's `StrictModes`)
- Added parent directory write-permission check — a world-writable parent
  directory is now also flagged as a security risk
- All warnings and errors redirected to `stderr`

### Known issue
- `cmd_tail.py`: log lines forwarded to Telegram are not yet passed through
  `sanitize()` before being embedded in the `<pre>` block. Lines containing
  `<`, `>`, or `&` (common in stack traces, XML logs, HTML error pages) may
  cause Telegram's HTML parser to choke. Will be fixed in `0.2.3`.

---

## [0.2.1] - 2026-04-02

### Fixed
- README updated to cover all commands introduced in `0.2.0` (`run`, `tail`,
  `ping`, `version`) — previously only `send`, `ask`, and `daemon` were documented
- Project tagline corrected to match description used across all other files:
  *Zero-dependency, stdlib-only Telegram bridge for two-way CLI automation.*

---

## [0.2.0] - 2026-04-02

### Added
- `tgzero run` — executes a local shell command and sends output, exit code,
  and elapsed time to Telegram on completion
- `tgzero tail` — watches a file for new lines and forwards them to Telegram
  in real time; supports `--filter` (keyword matching) and `--label` (display name)
- `tgzero ping` — verifies API credentials and network connectivity by sending
  a test message; safe token preview printed locally
- `tgzero version` — prints the installed version as a subcommand
  (complements the existing `tgzero --version` flag)
- Friendly welcome screen when `tgzero` is run with no arguments:
  lists all commands, examples, and config hint
- Config hint in welcome screen:
  `TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in telegram.env or environment`

### Changed
- All command descriptions rewritten to be shorter and action-first
- Dynamic versioning: `pyproject.toml` now reads version from `tgzero.__version__`
  automatically — only `__init__.py` needs updating on release
- `subparsers.required` set to `False`; missing command now shows the welcome
  screen instead of an argparse error

---

## [0.1.1] - 2026-04-01

### Fixed
- Daemon command execution: fixed "No such file or directory" error when
  allow-listed commands contained arguments or spaces (`shlex.split` applied
  before `subprocess.run`)

---

## [0.1.0] - 2026-04-01

### Added
- `tgzero send` — fire-and-forget Telegram notifications with `--silent`
  and `--json` flags
- `tgzero ask` — synchronous C2 gatekeeper with inline keyboard buttons
- `tgzero daemon` — long-running Telegram agent with command allow-list
- Full exit code contract (0–5) for `ask`
- Atomic lockfile concurrency with stale PID recovery
- SIGTERM / SIGINT signal handling with Telegram notification on shutdown
- Clock drift detection on daemon startup
- 60-second stale message window on startup to drop outdated commands
- Zero runtime dependencies — pure Python stdlib
