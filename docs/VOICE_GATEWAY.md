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

## Two-Leg Run (`/listen` + `/speak`)

Use this when your telephony side has separate inbound/outbound bridges.

`call_uuid` is required on both websockets and must be the same value.

```bash
cd /workspace/OmniCortex
source .moshi-venv/bin/activate

python scripts/voice_gateway_two_leg.py \
  --host 0.0.0.0 \
  --port 8099 \
  --listen-endpoint /listen \
  --speak-endpoint /speak \
  --omnicortex-voice-ws ws://127.0.0.1:8000/voice/ws \
  --default-agent-id <agent_uuid> \
  --default-token <bearer_token> \
  --default-voice-prompt NATF0.pt \
  --inbound-mode pcm16 \
  --outbound-mode pcm16 \
  --fs-sample-rate 8000 \
  --moshi-sample-rate 24000 \
  --barge-in-enabled \
  --barge-in-rms-threshold 0.02
```

Example endpoints from media gateway:

- `ws://<host>:8099/listen?call_uuid=<uuid>&agent_id=<agent_uuid>&token=<token>`
- `ws://<host>:8099/speak?call_uuid=<uuid>`

Two-leg mode includes queue flush barge-in by default:
- If inbound RMS crosses threshold, pending outbound audio is dropped.
- Optional control interrupt frame is sent upstream (`FRAME_CTRL`).

## Three-Process Runtime Shape

If you want strict separation by responsibility, run:

1. `brain_orchestrator.py` (session owner + upstream PersonaPlex/Omni WS)
2. `bridge_in.py` (telephony inbound to orchestrator)
3. `bridge_out.py` (orchestrator outbound to telephony)

```bash
# terminal 1
python brain_orchestrator.py \
  --host 0.0.0.0 \
  --port 8101 \
  --omnicortex-voice-ws ws://127.0.0.1:8000/voice/ws \
  --default-agent-id <agent_uuid> \
  --default-token <bearer_token>

# terminal 2
python bridge_in.py \
  --host 0.0.0.0 \
  --port 8102 \
  --endpoint /listen \
  --orchestrator-ingest-ws ws://127.0.0.1:8101/ingest

# terminal 3
python bridge_out.py \
  --host 0.0.0.0 \
  --port 8103 \
  --endpoint /speak \
  --orchestrator-egress-ws ws://127.0.0.1:8101/egress
```

Telephony side must use the same `call_uuid` on both legs:

- `ws://<host>:8102/listen?call_uuid=<uuid>&agent_id=<agent_uuid>&token=<token>`
- `ws://<host>:8103/speak?call_uuid=<uuid>`

Dialplan HTTP playback mode (no Redis) is also supported by `bridge_out.py`:

- `http://<host>:8103/stream/<uuid>`

Example:

```xml
<action application="playback" data="http://127.0.0.1:8103/stream/${uuid}"/>
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
