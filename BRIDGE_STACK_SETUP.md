# Bridge Stack Setup Guide

Complete guide for setting up the bridge stack (bridge_in + brain_orchestrator + bridge_out) on the same Linux server as FreeSWITCH.

## Architecture

```
FreeSWITCH (SIP Phone)
    ↓ audio_fork (websocket)
bridge_in.py (port 8001)
    ↓ websocket
brain_orchestrator.py (port 8101) ←→ PersonaPlex (RunPod)
    ↓ websocket
bridge_out.py (port 8002)
    ↓ HTTP stream
FreeSWITCH (playback)
```

## Prerequisites

1. Python 3.8+ with required packages:
```bash
pip install aiohttp numpy sphn edge-tts
```

2. FreeSWITCH installed and running

3. Access to PersonaPlex on RunPod

## Installation Steps

### 1. Copy Files to FreeSWITCH Server

Transfer these files to your FreeSWITCH server:
- `bridge_in.py`
- `bridge_out.py`
- `brain_orchestrator.py`
- `start_bridge_stack.sh`

```bash
# On your local machine
scp bridge_in.py bridge_out.py brain_orchestrator.py start_bridge_stack.sh \
    root@your-freeswitch-server:/opt/omnicortex/
```

### 2. Configure the Stack

Edit `start_bridge_stack.sh` and update:

```bash
# PersonaPlex WebSocket URL
PERSONAPLEX_WS="wss://lhoac81oebncui-8998.proxy.runpod.net/api/chat"

# Voice prompt
VOICE_PROMPT="NATF0.pt"

# Text prompt (optional)
TEXT_PROMPT="Your system prompt here..."
```

### 3. Make Script Executable

```bash
chmod +x start_bridge_stack.sh
```

### 4. Install FreeSWITCH Dialplan

```bash
# Copy dialplan
sudo cp freeswitch/bridge_stack_dialplan.xml \
    /usr/local/freeswitch/conf/dialplan/default/

# Reload FreeSWITCH config
fs_cli -x "reloadxml"
```

## Usage

### Start the Bridge Stack

```bash
./start_bridge_stack.sh start
```

Expected output:
```
[INFO] Starting bridge stack...
[INFO] Starting brain_orchestrator on port 8101...
[INFO] brain_orchestrator started (PID: 12345)
[INFO] Starting bridge_in on port 8001...
[INFO] bridge_in started (PID: 12346)
[INFO] Starting bridge_out on port 8002...
[INFO] bridge_out started (PID: 12347)

[INFO] Bridge Stack Status:

  ✓ brain_orchestrator (PID: 12345)
  ✓ bridge_in (PID: 12346)
  ✓ bridge_out (PID: 12347)

[INFO] Bridge stack started successfully!
[INFO] FreeSWITCH should connect to:
[INFO]   - Inbound:  ws://127.0.0.1:8001/freeswitch?call_uuid=${uuid}
[INFO]   - Outbound: http://127.0.0.1:8002/stream/${uuid}.raw
```

### Check Status

```bash
./start_bridge_stack.sh status
```

### View Logs

```bash
# View brain_orchestrator logs
./start_bridge_stack.sh logs brain_orchestrator

# View bridge_in logs
./start_bridge_stack.sh logs bridge_in

# View bridge_out logs
./start_bridge_stack.sh logs bridge_out
```

### Stop the Stack

```bash
./start_bridge_stack.sh stop
```

### Restart the Stack

```bash
./start_bridge_stack.sh restart
```

## Testing

### 1. Test with SIP Phone

Dial `7777` from your SIP phone. You should:
1. Hear the call connect
2. Be able to speak and hear AI responses
3. Experience natural conversation with barge-in support

### 2. Check Component Health

```bash
# Check brain_orchestrator
curl http://127.0.0.1:8101/health

# Check bridge_in
curl http://127.0.0.1:8001/health

# Check bridge_out
curl http://127.0.0.1:8002/health
```

Expected response: `{"status": "ok"}`

### 3. Monitor FreeSWITCH Logs

```bash
tail -f /usr/local/freeswitch/log/freeswitch.log | grep -E "7777|audio_fork|playback"
```

## Dialplan Extensions

The dialplan includes multiple test extensions:

- **7777** - Standard AI call with default settings
- **7778** - Call with custom agent_id and token
- **7779** - Call with male voice (NATM0.pt)
- **7770** - Test/debug call with extra logging

## Troubleshooting

### Issue: Components won't start

**Check Python dependencies:**
```bash
pip install aiohttp numpy sphn edge-tts
```

**Check if ports are available:**
```bash
netstat -tlnp | grep -E ':(8001|8002|8101)'
```

### Issue: No audio from AI

**Check bridge_out logs:**
```bash
./start_bridge_stack.sh logs bridge_out
```

**Verify PersonaPlex connection:**
```bash
./start_bridge_stack.sh logs brain_orchestrator | grep "upstream connected"
```

### Issue: Audio choppy or delayed

**Check for dropped frames:**
```bash
./start_bridge_stack.sh logs brain_orchestrator | grep "dropped"
```

**Increase outbound queue:**
Edit `start_bridge_stack.sh` and add to brain_orchestrator:
```bash
--outbound-queue-max 800
```

### Issue: Barge-in not working

**Check if local ASR is available:**
```bash
./start_bridge_stack.sh logs brain_orchestrator | grep "phrase barge"
```

**Disable barge-in if needed:**
Edit `start_bridge_stack.sh` and change:
```bash
--barge-in-enabled  # Remove this line or change to --no-barge-in-enabled
```

## Advanced Configuration

### Custom Sample Rates

If your FreeSWITCH uses different sample rates:

```bash
# In start_bridge_stack.sh, modify brain_orchestrator:
--fs-sample-rate 16000 \      # FreeSWITCH sample rate
--moshi-sample-rate 24000 \   # PersonaPlex sample rate
```

### Enable Debug Logging

```bash
# Add to each component in start_bridge_stack.sh:
--log-level DEBUG
```

### TTS Fallback Configuration

```bash
# In start_bridge_stack.sh, modify bridge_out:
--tts-voice "en-US-AriaNeural" \
--tts-flush-after-sec 1.5 \
```

### Silence Pump Tuning

```bash
# In start_bridge_stack.sh, modify brain_orchestrator:
--silence-frame-ms 20 \
--silence-skip-recent-sec 0.025 \
```

## Production Deployment

### 1. Create Systemd Service

Create `/etc/systemd/system/bridge-stack.service`:

```ini
[Unit]
Description=OmniCortex Bridge Stack
After=network.target freeswitch.service

[Service]
Type=forking
User=root
WorkingDirectory=/opt/omnicortex
ExecStart=/opt/omnicortex/start_bridge_stack.sh start
ExecStop=/opt/omnicortex/start_bridge_stack.sh stop
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable bridge-stack
sudo systemctl start bridge-stack
sudo systemctl status bridge-stack
```

### 2. Log Rotation

Create `/etc/logrotate.d/bridge-stack`:

```
/opt/omnicortex/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
}
```

### 3. Monitoring

Add to your monitoring system:
```bash
# Health check script
#!/bin/bash
for port in 8001 8002 8101; do
    curl -f http://127.0.0.1:$port/health || exit 1
done
```

## Performance Tuning

### For High Call Volume

1. Increase queue sizes in `start_bridge_stack.sh`:
```bash
--outbound-queue-max 1000
```

2. Disable TTS fallback if not needed:
```bash
--no-tts-enabled
```

3. Adjust session idle timeout:
```bash
--session-idle-sec 30
```

### For Low Latency

1. Reduce silence frame size:
```bash
--silence-frame-ms 10
```

2. Disable silence pump if not needed:
```bash
# Remove --silence-pump-enabled
```

## Support

For issues or questions:
1. Check logs in `./logs/`
2. Verify all components are running: `./start_bridge_stack.sh status`
3. Test each component health endpoint
4. Review FreeSWITCH logs for connection issues
