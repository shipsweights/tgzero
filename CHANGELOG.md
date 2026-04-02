# Changelog

All notable changes to this project will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

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
