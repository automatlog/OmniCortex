# Direct Relay

This is a separate low-latency FreeSWITCH to PersonaPlex runtime.

## What it does
- Accepts `audio_fork` websocket media on `WS /calls`
- Relays raw `PCM16-LE`, mono, `16000 Hz` audio directly to PersonaPlex/Moshi
- Returns assistant audio on the same websocket back to FreeSWITCH
- Keeps existing `bridge.py` and the 3-file bridge stack untouched

## Run

Install runtime dependencies in the environment used on RunPod:

```bash
uv pip install -e ".[voice-relay]"
```

```bash
python scripts/relay.py \
  --host 0.0.0.0 \
  --port 8080 \
  --path /calls \
  --personaplex-ws ws://127.0.0.1:8998/api/chat \
  --preset-file config/direct_relay_presets.example.json \
  --preset-name icici_priya \
  --tts-enabled \
  --backchannel-enabled
```

## Optional OmniCortex prompt fetch

```bash
python scripts/relay.py \
  --host 0.0.0.0 \
  --port 8080 \
  --personaplex-ws ws://127.0.0.1:8998/api/chat \
  --omnicortex-fetch-enabled \
  --omnicortex-api-base http://127.0.0.1:8000 \
  --omnicortex-bearer <token> \
  --omnicortex-agent-id <agent_id> \
  --preset-file config/direct_relay_presets.example.json
```

Prompt fetch precedence:
1. If `agent_id` is provided and OmniCortex fetch is enabled, fetch `/agents/{agent_id}/system-prompt` and `/agents/{agent_id}`.
2. If that fails and a static preset/file exists, fall back to static.
3. If neither exists, session setup fails.

## Endpoints
- `GET /health`
- `WS /calls?call_uuid=<uuid>[&agent_id=<agent_id>][&preset=<preset>]`

## Dialplan

```xml
<extension name="direct_relay_ai">
  <condition field="destination_number" expression="^5050$">
    <action application="answer"/>
    <action application="set" data="absolute_codec_string=L16@16000h@20i"/>
    <action application="set" data="read_codec=L16"/>
    <action application="set" data="read_rate=16000"/>
    <action application="set" data="write_codec=L16"/>
    <action application="set" data="write_rate=16000"/>
    <action application="audio_fork" data="start ws://<runpod-host>:<public-port>/calls?call_uuid=${uuid} 16000"/>
    <action application="park"/>
  </condition>
</extension>
```

## Operational checks
- `module_exists mod_audio_fork`
- `show codecs` includes `L16`
- allow SIP and RTP ports on the FreeSWITCH host
- map the relay container port to a public TCP port in RunPod

## Runtime notes
- Native PersonaPlex audio is preferred.
- Text-to-speech fallback is used only when native audio is not present.
- Barge-in is stop-phrase-only.
- Greeting, backchannels, and fallback TTS require `edge-tts` and `ffmpeg`.
- Local VAD / stop-phrase detection requires `faster-whisper` through `core.voice.asr_engine`.
