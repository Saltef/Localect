# Hosting Localect

One instance, two audiences. You sign in and get everything: your mail, your
facts, your model. Visitors, if you allow them, get a demo that runs on a
sample store, never sees your data, and cannot spend your key beyond the caps
you set.

## What changes when a password is set

`localect config --owner-password "…"` (or `LOCALECT_OWNER_PASSWORD`) turns the
login on. From then on:

- the web UI shows a sign-in screen; a correct password sets a signed,
  HttpOnly cookie for 30 days (Secure when the proxy says HTTPS);
- every `/api/` call needs that cookie, or the browser extension's pairing
  token, which counts as you;
- sign-in attempts are capped per address like any other visitor action;
- the password is stored as a PBKDF2 hash, never in clear. Set it to `""` to
  remove the login again.

`localect serve` warns when it listens beyond localhost without a password.

## Public demo mode

`localect config --public-mode demo` lets anyone open the site and use
**Compose**, and nothing else. What a visitor gets:

- a separate in-memory database seeded with the demo store (glossary, five
  policy documents, contacts): your knowledge base, mail, facts and history
  are never queried;
- the model you choose for them: `--public-model stub` (default, a
  deterministic stand-in that costs nothing) or `configured` (your model and
  key);
- caps: `public_hourly` tries per address per hour (default 20) and
  `public_daily` for everyone per day (default 300); the banner shows the
  visitor how many tries they have left;
- nothing kept: a visitor's reply is not written to history.

A visitor sees a banner saying all of this, and an "Owner? Sign in" link.

## Deploy with Docker Compose and automatic HTTPS

```bash
git clone https://github.com/Saltef/Localect && cd Localect
cp .env.example .env        # set LOCALECT_DOMAIN, LOCALECT_OWNER_PASSWORD, your model and key
docker compose up -d --build
```

`docker-compose.yml` runs Localect with a persistent volume for `/data` (the
database, settings, the signing secret) behind Caddy, which obtains and
renews the certificate for `LOCALECT_DOMAIN` and forwards the client address.
`LOCALECT_TRUST_PROXY=1` tells Localect to believe `X-Forwarded-For` and
`X-Forwarded-Proto` from that proxy, which is what makes the per-address caps
and the Secure cookie correct. Do not set it when Localect is exposed directly.

Point your domain's DNS at the host, open ports 80 and 443, and Caddy does
the rest. Any other reverse proxy works the same way as long as it sets those
two headers.

## Using it yourself, hosted

Import your mail as on a laptop, from inside the container's data volume or
through the Memory page's import box with a path the container can see (mount
the export: `-v ~/mail:/imports:ro`, then import `/imports/All mail.mbox`).
The browser extension pairs with a hosted Localect too: set its server URL to
`https://your-domain` and paste the token from Settings. Everything the
extension captures goes only to your instance.

## Threat model, briefly

- A stranger with the URL: sees the demo if it is on, otherwise a sign-in
  screen. Cannot reach settings, memory, knowledge, glossary, contacts,
  history or the extension token without the password.
- A web page you visit: cannot call your Localect, hosted or local, because a
  request from another origin is refused unless it is your paired extension.
- The demo cannot leak your data because it does not have it: the visitor
  path has its own database and its own tools.
- What this does not do: multi-user accounts, rate limiting by anything but
  address, or protection against a leaked owner password. Keep the password
  long, and rotate the extension token from Settings if a device is lost.
