# Changelog

All notable changes to this project will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.1.0] - 2026-04-01

### Added
- `tgzero send` — fire-and-forget Telegram notifications with `--silent` and `--json` flags
- `tgzero ask` — synchronous C2 gatekeeper with inline keyboard buttons
- `tgzero daemon` — long-running Telegram agent with command allow-list
- Full exit code contract (0–5) for `ask`
- Atomic lockfile concurrency with stale PID recovery
- SIGTERM / SIGINT signal handling with Telegram notification on shutdown
- Clock drift detection on daemon startup
- 60-second stale message filtering
- Zero runtime dependencies — pure stdlib
