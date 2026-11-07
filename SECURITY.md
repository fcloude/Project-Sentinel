# Security Policy

## Reporting a vulnerability
Email **security@YOUR-DOMAIN** (set before launch) with steps to reproduce. Please do not open a public issue.
We acknowledge within 3 business days and aim to ship a fix within 90 days (sooner for critical issues).

## Scope
Project Sentinel is self-hosted. Reports about the dashboard, authentication, file handling, camera/URL handling,
notification channels and the update/licence code are in scope.

## Operator hardening checklist
- Keep `HOST=127.0.0.1`. For remote access use a VPN/Tailscale or a TLS reverse proxy; never port-forward the dashboard.
- Set `SENTINEL_HTTPS=true` when served over HTTPS and keep `SENTINEL_TRUSTED_PROXIES` equal to the real number of proxies.
- Keep `.env`, `data/` and `snapshots/` out of backups you do not control; encrypt the disk.
- Run `pip-audit` monthly and update dependencies.
- If a Telegram token, `SECRET_KEY` or `.env` was ever committed, treat it as public: revoke it
  with @BotFather, generate replacements, and purge the history with `git filter-repo`. Revocation
  is the real fix; history rewriting only removes copies you control.
- Never force-add `.env`. `.gitignore` excludes it; check `git status` before every commit.
