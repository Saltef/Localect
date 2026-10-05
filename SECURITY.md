# Security Policy

Localect runs on your own machine. Nothing it does reaches the network except
the model endpoint you configure in Settings; there is no account and no
telemetry. What's still worth securing:

- `~/.localect/settings.json` holds your model API key in clear text, and
  `~/.localect/localect.db` holds your imported mail, glossary and history.
  Treat that directory like any other credentials file.
- Hosting Localect behind a reverse proxy (`docker-compose.yml`, see
  `docs/HOSTING.md`) puts it on the network. Set an owner password
  (`localect config --owner-password`) before you do, and keep `trust_proxy`
  off unless Caddy or another proxy is actually terminating TLS in front
  of it.
- The browser extension's pairing token (`docs/EXTENSION.md`) is a bearer
  credential for your own Localect. It's shown once in Settings and never
  sent anywhere but your own server.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting instead of a public
issue: this repository's **Security** tab → **Report a vulnerability**.
That reaches the maintainer directly and keeps the report private until a
fix ships.

Include what you'd include in a bug report: the version (`localect
--version`), how to reproduce it, and what you'd expect instead. If it's
exploitable with no configuration beyond a default install, say so — that's
the highest-priority class of report.

## Scope

In scope: anything reachable through `localect serve` as shipped, the
`extension/` code, and the Docker/Compose hosting path in
`docs/HOSTING.md`.

Out of scope: a model provider's own API or infrastructure, and anything
that requires the attacker to already have access to your machine or your
`~/.localect/` directory.
