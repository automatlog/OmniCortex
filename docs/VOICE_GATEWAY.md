# Voice Gateway

This project includes a lightweight bridge service at `scripts/voice_gateway.py` for:

1. FreeSWITCH/media websocket leg (`/calls`)
2. OmniCortex Moshi proxy websocket (`/voice/ws`)

## Why this exists

Moshi websocket expects framed binary messages (kind + payload), while telecom/media streams often arrive as raw PCM16 or module-specific frames. The gateway handles conversion and forwarding.

## Run

Use an environment that includes `aiohttp`, `numpy`, and `sphn` (typically `.moshi-venv`):

```bash
cd /workspace/OmniCortex
source .moshi-venv/bin/activate

python scripts/voice_gateway.py \
  --host 0.0.0.0 \
  --port 8099 \
  --endpoint /calls \
  --omnicortex-voice-ws ws://127.0.0.1:8000/voice/ws \
  --default-agent-id <agent_uuid> \
  --default-token <bearer_token> \
  --default-voice-prompt NATF0.pt \
  --inbound-mode pcm16 \
  --outbound-mode pcm16 \
  --fs-sample-rate 8000 \
  --moshi-sample-rate 24000
```

## TLS modes

Option A: terminate TLS at nginx (recommended) and proxy `/calls` to `http://127.0.0.1:8099/calls`.

Option B: direct TLS in gateway:

```bash
python scripts/voice_gateway.py \
  --host 0.0.0.0 \
  --port 443 \
  --endpoint /calls \
  --ssl-cert /path/to/fullchain.pem \
  --ssl-key /path/to/privkey.pem
```

## Key env vars

- `OMNICORTEX_VOICE_WS` (default `ws://127.0.0.1:8000/voice/ws`)
- `VOICE_GATEWAY_AGENT_ID`
- `VOICE_GATEWAY_TOKEN`
- `VOICE_GATEWAY_VOICE_PROMPT` (default `NATF0.pt`)
- `VOICE_GATEWAY_INBOUND_MODE` (`pcm16` or `moshi`)
- `VOICE_GATEWAY_OUTBOUND_MODE` (`pcm16` or `moshi`)
- `VOICE_GATEWAY_FS_SR` (default `8000`)
- `VOICE_GATEWAY_MOSHI_SR` (default `24000`)

## Health endpoint

`GET /health` returns:

```json
{"status":"ok"}
```

## FreeSWITCH Verto WS client (in OmniCortex API)

`api.py` now also exposes a Verto websocket client/proxy layer for `wss://.../verto` checks.

- `GET /freeswitch/verto/check`
  - Verifies websocket handshake to Verto from OmniCortex.
  - Query params:
    - `url` (optional override; otherwise uses env `FREESWITCH_VERTO_WS_URL`)
    - `timeout_sec` (optional, default `8`)
  - Requires `Authorization: Bearer <token>`.

- `WS /freeswitch/verto/ws`
  - Relays frames between your client and upstream Verto websocket.
  - Query params:
    - `token` (bearer token if header is not set)
    - `url` or `target_url` (optional override)
    - `timeout_sec` (optional)

### Env vars for Verto client

- `FREESWITCH_VERTO_WS_URL` (default `wss://172.22.0.2:7443`)
- `FREESWITCH_VERTO_SSL_VERIFY` (`true`/`false`, default `false`)

### Example check command

```bash
curl -sS "http://127.0.0.1:8000/freeswitch/verto/check?url=wss://172.22.0.2:7443&timeout_sec=8" \
  -H "Authorization: Bearer <YOUR_TOKEN>"
```
