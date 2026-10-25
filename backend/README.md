# Backend: Quota Watch Bridge

A small self-hosted service that collects **Codex and Claude Code limits** and
**agent activity** from all your computers and serves them as one compact JSON
document. The desk display reads it; so can anything else that speaks HTTP
(an Apple Watch complication, a menu-bar widget, a shell prompt).

```text
Computers (hooks, on every event)         Server (Docker Compose)                       Consumers
Codex / Claude Code ── signed POST ──┐    ┌─ caddy: TLS, only API paths pass ─────┐
                                     └──> │  quota-watch: FastAPI + SQLite         │ ──> GET /v1/widget
                                          │  quota-poller: Codex app-server +      │     (display, watch)
                                          └─ Claude Agent SDK, limits every 15 s ──┘
```

- **Limits are per account**, so the server polls them itself: the
  `quota-poller` container signs in to Codex and Claude with its **own** server
  sessions and reads the 5-hour and weekly windows.
- **Activity is per computer**: IDE hooks push `working`, `waiting_approval`,
  `waiting_input`, `idle` or `error` the moment it changes. There is no
  background process on the computers.
- **Nothing sensitive leaves your computers**: no OAuth tokens, API keys,
  prompts, answers, source code, project paths or transcripts. Only an
  anonymised session state (hashed session ID) and the computer's name.

## What is supported

- several computers on one account;
- Codex 5-hour and weekly limits;
- Claude Code 5-hour and weekly limits for claude.ai Pro/Max plans;
- agent states `working`, `waiting_approval`, `waiting_input`, `idle`, `error`;
- one aggregated JSON with per-provider blocks, flat fields for simple widgets,
  and a `laptops` array with per-computer details;
- an HMAC-SHA256 key per computer, timestamps and one-time nonces;
- a separate read-only key for displays and widgets;
- TLS through Caddy, replay protection, body size and rate limits.

## Widget JSON

`GET /v1/widget` with the header `X-Widget-Key: <read-only key>` returns
something like this (shortened):

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-20T12:00:00+00:00",
  "providers": {
    "codex": {
      "status": "working",
      "working_agents": 1,
      "waiting_agents": 0,
      "errors": 0,
      "five_hour": {"remaining_percent": 75.0, "used_percent": 25.0, "resets_at": "2026-09-20T14:10:00+00:00"},
      "weekly": {"remaining_percent": 58.0, "used_percent": 42.0, "resets_at": "2026-09-24T09:00:00+00:00"}
    },
    "claude": {"status": "idle", "working_agents": 0, "waiting_agents": 0, "errors": 0, "five_hour": {"...": "..."}, "weekly": {"...": "..."}}
  },
  "widget_compact": "Cdx 75% · Cl 60% · 1 active",
  "widget_gauge": 0.6,
  "codex_5h_remaining_pct": 75.0,
  "claude_5h_remaining_pct": 60.0,
  "active_agents_total": 1,
  "waiting_agents_total": 0,
  "laptops_total": 2,
  "laptops": [
    {
      "id": "macbook-pro",
      "name": "MacBook Pro",
      "online": null,
      "availability": "last_known",
      "activity": {
        "codex": {"state": "working", "active_sessions": 1},
        "claude": {"state": "idle", "active_sessions": 0}
      }
    }
  ]
}
```

The display uses the `providers` block. `widget_gauge` is always the smaller of
the Codex and Claude remainders, so a single gauge conservatively shows the
limit closest to running out.

## Deploy on a server

You need a small Linux server with Docker Compose, a DNS name pointing at it,
and ports 80 and 443 open. 1 vCPU and 1 GB RAM is enough.

1. Clone the repository and go to `backend/`:

   ```bash
   git clone https://github.com/MalyshkoA/agents-usage-and-limits-monitor.git
   cd agents-usage-and-limits-monitor/backend
   cp .env.example .env
   cp .env.poller.example .env.poller
   chmod 600 .env .env.poller
   ```

2. Generate one secret per computer, one for the server poller and one
   read-only key for the display (and per watch/widget, if you like):

   ```bash
   openssl rand -hex 32
   ```

3. Fill in `.env`:

   - `QWB_DOMAIN`: the DNS name of the server, for example `quota.example.com`;
   - `QWB_DEVICE_KEYS_JSON`: `{"macbook-pro":"<key>","mac-mini":"<key>","server-poller":"<key>"}`;
   - `QWB_WIDGET_KEYS`: the display key (comma-separated if there are several);
   - keep `QWB_LIMIT_SOURCE_DEVICES=server-poller`, so the poller is not listed as a laptop.

4. Put the same `server-poller` key into `QWB_POLLER_SECRET` in `.env.poller`.

5. Start the API and Caddy, then sign the poller in once. The sessions are kept
   in the `quota-poller-data` volume:

   ```bash
   docker compose up -d --build quota-watch caddy
   docker compose run --rm -it quota-poller quota-watch-poller login
   docker compose up -d quota-poller
   ```

   Codex signs in with a device code (`codex login --device-auth`), Claude with
   `claude auth login`: open the link, approve, paste the code back. (`claude
   setup-token` is not enough: its token cannot read plan limits.) You can revoke
   these sessions in your account settings at any time without touching your
   computers. `docker compose run --rm quota-poller quota-watch-poller status`
   shows which sessions exist; logs are in `docker logs quota-poller`.

6. Check it:

   ```bash
   curl https://quota.example.com/healthz
   curl -H 'X-Widget-Key: <display key>' https://quota.example.com/v1/widget
   ```

Caddy obtains and renews the TLS certificate on its own and forwards only
`/healthz`, `/v1/ingest/*` and `/v1/widget`; everything else gets a cheap 404.
If the server already runs a reverse proxy, delete the `caddy` service from
`compose.yaml` and route those three paths to `quota-watch:8787` (see
`deploy/Caddyfile`). Do not publish port 8787 directly: the API trusts
`X-Forwarded-For` from its proxy for per-IP rate limiting.

Each Claude poll starts Claude Code for about a second of CPU and up to
~250 MB of memory. On a very small server raise `QWB_POLL_CLAUDE_SECONDS`.

## Connect your computers

Every computer reports its agents' activity through IDE hooks. Install the
small client once per computer (macOS or Linux, Python 3.11+):

```bash
python3 -m venv ~/.local/share/quota-watch-bridge
~/.local/share/quota-watch-bridge/bin/pip install /path/to/agents-usage-and-limits-monitor/backend
mkdir -p ~/.config/quota-watch
cp /path/to/agents-usage-and-limits-monitor/backend/client.example.toml ~/.config/quota-watch/client.toml
```

In `client.toml` set `server_url`, a unique `device_id` (it must match a key
name in `QWB_DEVICE_KEYS_JSON`) and `display_name`. Because the server poller
reads the limits, set `enabled = false` under both `[providers.codex]` and
`[providers.claude]`: the computer then sends activity only. Store this
computer's key separately:

```bash
umask 077
printf '%s\n' '<this computer key>' > ~/.config/quota-watch/device-secret
```

**Codex.** Merge the `hooks` section of `config/codex-hooks.json` into
`~/.codex/hooks.json` (do not overwrite an existing file), then open `/hooks`
in Codex and trust the new hooks.

**Claude Code.** Merge the `hooks` section of
`config/claude-settings.fragment.json` into `~/.claude/settings.json`. The
`statusLine` entry is optional; if you already have a status line, combine the
outputs instead of replacing it.

The hooks receive event metadata but keep only a hash of the session ID and the
state. A repeated hook with the same state does not send anything.

### Without a server poller

If you would rather not keep Codex/Claude sessions on the server, the computers
can report limits themselves:

- leave both providers enabled in `client.toml` and point
  `providers.codex.binary` at the absolute path from `which codex` (launchd has
  a minimal `PATH`);
- run `quota-watch-agent` in the background with
  `deploy/com.example.quota-watch-agent.plist` (replace `REPLACE_ME`, copy it to
  `~/Library/LaunchAgents/`, load it with `launchctl bootstrap`). It reads Codex
  limits locally through the official Codex app-server
  (`account/rateLimits/read`) while Codex is active;
- for Claude limits install the Agent SDK collector (`cd claude_usage && pnpm
  install --frozen-lockfile`) and run it every minute with
  `deploy/com.example.quota-watch-claude.plist` (replace `REPLACE_ME`,
  `NODE_BINARY`, `INSTALL_DIR`). It reads `/usage` without sending a prompt and
  does not spend tokens.

First manual run:

```bash
~/.local/share/quota-watch-bridge/bin/quota-watch-agent \
  --config ~/.config/quota-watch/client.toml \
  --once --refresh-codex --force --print
```

The agent is change-only: it posts only when a percentage, reset time, state
or session count changes, and retries failed deliveries with a 15 s to 5 min
backoff. Set `poll_when_idle = true` under `[providers.codex]` if window resets
should reach the server while Codex is idle.

## Other consumers: Apple Watch

The flat `widget_*` fields exist for JSON complication apps such as
Complicator, which cannot aggregate arrays:

- URL `https://quota.example.com/v1/widget`, custom header
  `X-Widget-Key: <a read-only key>`;
- one rectangular complication: JSON path `widget_compact`;
- multi-field layouts: `widget_title`, `widget_value`, `widget_subtitle`, and
  `widget_gauge` (range `0...1`).

watchOS decides when a complication refreshes, so it may lag behind the display.
Never put the key into the URL: query strings end up in access logs.

## Security model

- Every computer has its own key; a leaked key cannot sign for other devices.
- The signature covers the HTTP method, path, timestamp, nonce and the SHA-256
  of the body. Timestamps are accepted in a short window; nonces only once.
- Global and per-IP rate limits run before signature checks; a separate
  per-device limit runs after them, so unauthenticated traffic cannot exhaust a
  computer's allowance.
- Body size is capped in Caddy and in the app; Uvicorn caps concurrent
  connections; containers are read-only, drop all capabilities and have CPU,
  memory and process limits.
- Display and widget keys are read-only and see only the aggregated endpoint.
- SQLite stores no secrets: only the latest snapshots and recent nonces.
- Without heartbeats the server cannot know that a computer was switched off:
  `online` is `null` and `availability` is `last_known`. The last state is kept
  until the next hook; its age is in `last_seen_at` / `age_seconds`.
- A limit is kept until its `resets_at`, then dropped from the aggregate.
- Lost the display or a watch? Rotate only `QWB_WIDGET_KEYS`. Lost a computer?
  Rotate only its key.

## Configuration

`.env` (API, see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `QWB_DOMAIN` | | DNS name Caddy serves and gets a certificate for |
| `QWB_DEVICE_KEYS_JSON` | `{}` | `{"device-id": "key"}` for every computer and the poller |
| `QWB_WIDGET_KEYS` | | Comma-separated read-only keys for displays and widgets |
| `QWB_LIMIT_SOURCE_DEVICES` | | Devices that only supply limits (`server-poller`) |
| `QWB_DEVICE_STALE_SECONDS` | `180` | When a computer's snapshot counts as stale |
| `QWB_LIMIT_STALE_SECONDS` | `900` | When a limit snapshot counts as stale |
| `QWB_ACTIVE_STATE_TTL_SECONDS` | `0` | `0` keeps the last hook state until the next hook |
| `QWB_SIGNATURE_MAX_AGE_SECONDS` | `300` | Accepted clock skew for signed requests |
| `QWB_INGEST_REQUESTS_PER_MINUTE` | `30` | Per-device ingest limit |
| `QWB_INGEST_REQUESTS_PER_IP_MINUTE` | `90` | Per-IP ingest limit |
| `QWB_GLOBAL_INGEST_REQUESTS_PER_MINUTE` | `600` | Global ingest limit |
| `QWB_WIDGET_REQUESTS_PER_IP_MINUTE` | `120` | Per-IP widget limit (the display polls once a second) |

`.env.poller` (see `.env.poller.example`): `QWB_POLLER_SECRET`,
`QWB_POLLER_DEVICE_ID` (`server-poller`), `QWB_POLLER_ACCOUNT_ID`,
`QWB_POLL_CODEX_SECONDS`, `QWB_POLL_CLAUDE_SECONDS`.

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install . httpx
.venv/bin/python -m unittest discover -s tests -v
```
