# Bridge Relay Deployment Guide
## Direct FreeSWITCH → PersonaPlex Connection on Linux

## 📋 Overview

**bridge_relay.py** is a simplified voice bridge that connects FreeSWITCH directly to PersonaPlex server, bypassing the OmniCortex proxy. Designed for Linux deployment on the same server as FreeSWITCH.

### Architecture

```
FreeSWITCH (Port 5060/5080)
    │ WebSocket (L16/8kHz)
    ↓
bridge_relay.py (Port 8001)
    │ WebSocket (Opus/24kHz)
    ↓
PersonaPlex Server (Port 8998)
```

---

## 🚀 Quick Start

### 1. Prerequisites

```bash
# Python 3.8+
python3 --version

# Install system dependencies
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv ffmpeg

# FreeSWITCH should be installed
which freeswitch
```

### 2. Install Python Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install \
    websockets \
    opuslib \
    numpy \
    edge-tts \
    aiohttp
```

### 3. Configure Environment

```bash
# Create .env file
cat > .env << 'EOF'
# Server settings
BRIDGE_PORT=8001

# PersonaPlex connection
PERSONAPLEX_URL=ws://localhost:8998/api/chat
PERSONAPLEX_API_KEY=

# Agent configuration
AGENT_ID=
BEARER_TOKEN=
VOICE_PROMPT=NATF0.pt
TEXT_PROMPT=You are a helpful assistant.

# TTS settings
TTS_ENABLED=true
TTS_DIR=/tmp/bridge_tts
FS_CLI=/usr/local/freeswitch/bin/fs_cli

# Barge-in settings
BARGE_IN_ENABLED=true
BARGE_IN_RMS_THRESHOLD=0.012
BARGE_IN_MIN_AUDIO_SEC=0.8
BARGE_IN_MAX_AUDIO_SEC=2.5

# Debug
DEBUG=false
EOF

# Load environment
source .env
```

### 4. Test Run

```bash
# Activate virtual environment
source venv/bin/activate

# Run bridge
python3 bridge_relay.py
```

Expected output:
```
======================================================================
  BRIDGE RELAY - FreeSWITCH <-> PersonaPlex Direct Connection
======================================================================
  Listening on: 0.0.0.0:8001
  PersonaPlex:  ws://localhost:8998/api/chat
  Agent ID:     (none)
  TTS:          Enabled
  Barge-in:     Disabled
======================================================================

Waiting for calls...
```

---

## 🔧 Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BRIDGE_PORT` | 8001 | Port for FreeSWITCH connections |
| `PERSONAPLEX_URL` | ws://localhost:8998/api/chat | PersonaPlex WebSocket URL |
| `PERSONAPLEX_API_KEY` | (empty) | API key for PersonaPlex |
| `AGENT_ID` | (empty) | Default agent ID |
| `BEARER_TOKEN` | (empty) | Bearer token for authentication |
| `VOICE_PROMPT` | NATF0.pt | Voice model (NATF0-3, NATM0-3, VARF0-4, VARM0-4) |
| `TEXT_PROMPT` | You are a helpful assistant. | System prompt |
| `TTS_ENABLED` | true | Enable TTS fallback |
| `TTS_DIR` | /tmp/bridge_tts | Directory for TTS files |
| `FS_CLI` | /usr/local/freeswitch/bin/fs_cli | FreeSWITCH CLI path |
| `BARGE_IN_ENABLED` | true | Enable barge-in detection |
| `BARGE_IN_RMS_THRESHOLD` | 0.012 | RMS threshold for barge-in |
| `BARGE_IN_MIN_AUDIO_SEC` | 0.8 | Minimum audio duration |
| `BARGE_IN_MAX_AUDIO_SEC` | 2.5 | Maximum audio duration |
| `DEBUG` | false | Enable debug logging |

### Voice Options

#### Natural Voices (Recommended)
- `NATF0.pt` - Female, general conversations
- `NATF1.pt` - Female, professional
- `NATF2.pt` - Female, Hindi (experimental)
- `NATF3.pt` - Female, warm/friendly
- `NATM0.pt` - Male, general conversations
- `NATM1.pt` - Male, Hindi (experimental)
- `NATM2.pt` - Male, professional
- `NATM3.pt` - Male, deep/authoritative

#### Variety Voices
- `VARF0.pt` to `VARF4.pt` - Female variety
- `VARM0.pt` to `VARM4.pt` - Male variety

---

## 📞 FreeSWITCH Integration

### Dialplan Configuration

Create `/usr/local/freeswitch/conf/dialplan/default/voice_ai.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<include>
  <extension name="voice_ai_bridge">
    <condition field="destination_number" expression="^(9999)$">
      <!-- Answer the call -->
      <action application="answer"/>
      
      <!-- Set variables -->
      <action application="set" data="call_uuid=${uuid}"/>
      <action application="set" data="agent_id=YOUR_AGENT_ID"/>
      <action application="set" data="token=YOUR_BEARER_TOKEN"/>
      
      <!-- Connect to bridge_relay -->
      <action application="socket" 
              data="127.0.0.1:8001 async full"/>
      
      <!-- Hangup -->
      <action application="hangup"/>
    </condition>
  </extension>
</include>
```

### Alternative: Using mod_audio_fork

```xml
<extension name="voice_ai_fork">
  <condition field="destination_number" expression="^(9999)$">
    <action application="answer"/>
    
    <!-- Fork audio to bridge_relay -->
    <action application="audio_fork" 
            data="ws://127.0.0.1:8001/${uuid}?agent_id=YOUR_AGENT_ID&token=YOUR_TOKEN"/>
    
    <!-- Keep call alive -->
    <action application="park"/>
  </condition>
</extension>
```

### Reload Dialplan

```bash
# Connect to FreeSWITCH console
fs_cli

# Reload XML
reloadxml

# Test
originate user/1000 9999
```

---

## 🐳 Systemd Service Setup

### Create Service File

```bash
sudo nano /etc/systemd/system/bridge-relay.service
```

```ini
[Unit]
Description=Bridge Relay - FreeSWITCH to PersonaPlex
After=network.target freeswitch.service
Wants=freeswitch.service

[Service]
Type=simple
User=freeswitch
Group=freeswitch
WorkingDirectory=/opt/bridge-relay
EnvironmentFile=/opt/bridge-relay/.env
ExecStart=/opt/bridge-relay/venv/bin/python3 /opt/bridge-relay/bridge_relay.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/tmp/bridge_tts

[Install]
WantedBy=multi-user.target
```

### Install and Enable

```bash
# Create installation directory
sudo mkdir -p /opt/bridge-relay
sudo chown freeswitch:freeswitch /opt/bridge-relay

# Copy files
sudo cp bridge_relay.py /opt/bridge-relay/
sudo cp .env /opt/bridge-relay/
sudo cp -r venv /opt/bridge-relay/

# Set permissions
sudo chown -R freeswitch:freeswitch /opt/bridge-relay

# Create TTS directory
sudo mkdir -p /tmp/bridge_tts
sudo chown freeswitch:freeswitch /tmp/bridge_tts

# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable bridge-relay

# Start service
sudo systemctl start bridge-relay

# Check status
sudo systemctl status bridge-relay
```

### Service Management

```bash
# Start
sudo systemctl start bridge-relay

# Stop
sudo systemctl stop bridge-relay

# Restart
sudo systemctl restart bridge-relay

# Status
sudo systemctl status bridge-relay

# Logs
sudo journalctl -u bridge-relay -f

# Logs (last 100 lines)
sudo journalctl -u bridge-relay -n 100
```

---

## 🧪 Testing

### 1. Health Check

```bash
# Check if bridge is running
curl http://localhost:8001/health

# Expected: Connection refused (no HTTP endpoint)
# This is normal - bridge only accepts WebSocket
```

### 2. WebSocket Test

```bash
# Install websocat
sudo apt-get install -y websocat

# Test connection
websocat ws://localhost:8001/test-uuid-1234
```

### 3. FreeSWITCH Test Call

```bash
# Connect to FreeSWITCH
fs_cli

# Make test call
originate user/1000 9999

# Check bridge logs
sudo journalctl -u bridge-relay -f
```

### 4. Audio Test

```bash
# Call extension 9999
# Speak into phone
# Verify:
# - Audio is sent to PersonaPlex
# - AI responds
# - Audio is played back
```

---

## 📊 Monitoring

### Log Levels

```bash
# Normal operation
[INFO] [12345678] New call started
[INFO] [12345678] Connected to PersonaPlex
[INFO] [12345678] Handshake received
[INFO] [12345678] Text: Hello, how can I help?
[INFO] [12345678] Call ended

# Debug mode (DEBUG=true)
[DEBUG] [12345678] Audio pump started
[DEBUG] [12345678] Sending audio frame: 480 samples
[DEBUG] [12345678] Received audio frame: 480 samples

# Errors
[ERROR] [12345678] Bridge error: Connection refused
[ERROR] [12345678] Invalid UUID: not-a-uuid
[ERROR] [12345678] Decode error: Invalid opus packet
```

### Metrics to Monitor

```bash
# Active connections
sudo netstat -an | grep :8001 | grep ESTABLISHED | wc -l

# Memory usage
ps aux | grep bridge_relay.py

# CPU usage
top -p $(pgrep -f bridge_relay.py)

# Disk usage (TTS files)
du -sh /tmp/bridge_tts

# Log size
sudo journalctl -u bridge-relay --disk-usage
```

---

## 🔒 Security

### 1. Firewall Configuration

```bash
# Allow bridge port (internal only)
sudo ufw allow from 127.0.0.1 to any port 8001

# Or specific subnet
sudo ufw allow from 192.168.1.0/24 to any port 8001
```

### 2. SSL/TLS (Optional)

```bash
# If PersonaPlex uses SSL
export PERSONAPLEX_URL=wss://personaplex.example.com/api/chat

# Update bridge_relay.py to handle SSL verification
```

### 3. Authentication

```bash
# Use bearer token
export BEARER_TOKEN=your_secret_token

# Use API key
export PERSONAPLEX_API_KEY=your_api_key
```

### 4. User Permissions

```bash
# Run as freeswitch user (not root)
sudo -u freeswitch python3 bridge_relay.py
```

---

## 🐛 Troubleshooting

### Issue 1: Connection Refused

```bash
# Check if PersonaPlex is running
curl http://localhost:8998/health

# Check if port is open
sudo netstat -tulpn | grep 8998

# Check firewall
sudo ufw status
```

### Issue 2: No Audio

```bash
# Check FreeSWITCH audio settings
fs_cli -x "show channels"

# Check codec
fs_cli -x "show codec"

# Verify audio path
sudo tcpdump -i lo -n port 8001
```

### Issue 3: TTS Not Working

```bash
# Check edge-tts installation
pip list | grep edge-tts

# Test edge-tts
edge-tts --text "Hello world" --write-media test.mp3

# Check ffmpeg
ffmpeg -version

# Check fs_cli path
which fs_cli
```

### Issue 4: High CPU Usage

```bash
# Check active calls
sudo netstat -an | grep :8001 | grep ESTABLISHED

# Check for stuck processes
ps aux | grep bridge_relay

# Restart service
sudo systemctl restart bridge-relay
```

### Issue 5: Memory Leak

```bash
# Monitor memory over time
watch -n 5 'ps aux | grep bridge_relay'

# Check for orphaned TTS files
ls -lh /tmp/bridge_tts

# Clean up old files
find /tmp/bridge_tts -type f -mtime +1 -delete
```

---

## 📈 Performance Tuning

### 1. Optimize Audio Buffer

```python
# In bridge_relay.py, adjust:
OPUS_FRAME_MS = 20  # Try 10 or 40 for different latency/quality
```

### 2. Disable TTS if Not Needed

```bash
export TTS_ENABLED=false
```

### 3. Adjust Barge-in Sensitivity

```bash
# More sensitive (interrupts easier)
export BARGE_IN_RMS_THRESHOLD=0.008

# Less sensitive (requires louder speech)
export BARGE_IN_RMS_THRESHOLD=0.020
```

### 4. Increase Connection Timeout

```python
# In bridge_relay.py, adjust:
ping_interval=20,  # Try 30 or 60
ping_timeout=30,   # Try 60 or 90
```

---

## 🔄 Upgrade Process

### 1. Backup Current Version

```bash
sudo cp /opt/bridge-relay/bridge_relay.py /opt/bridge-relay/bridge_relay.py.backup
```

### 2. Update Code

```bash
sudo cp bridge_relay.py /opt/bridge-relay/
sudo chown freeswitch:freeswitch /opt/bridge-relay/bridge_relay.py
```

### 3. Restart Service

```bash
sudo systemctl restart bridge-relay
```

### 4. Verify

```bash
sudo systemctl status bridge-relay
sudo journalctl -u bridge-relay -n 50
```

### 5. Rollback if Needed

```bash
sudo cp /opt/bridge-relay/bridge_relay.py.backup /opt/bridge-relay/bridge_relay.py
sudo systemctl restart bridge-relay
```

---

## 📚 Additional Resources

### Documentation
- `PERSONAPLEX_SUMMARY.md` - PersonaPlex overview
- `THREE_PROCESS_ARCHITECTURE_ANALYSIS.md` - Alternative architecture
- `RELAY_HTTP_VS_WEBSOCKET_ANALYSIS.md` - WebSocket explanation

### FreeSWITCH
- [FreeSWITCH Documentation](https://freeswitch.org/confluence/)
- [mod_audio_fork](https://freeswitch.org/confluence/display/FREESWITCH/mod_audio_fork)
- [Event Socket](https://freeswitch.org/confluence/display/FREESWITCH/Event+Socket+Library)

### PersonaPlex
- PersonaPlex GitHub (if available)
- Voice model documentation
- API reference

---

## 🎯 Production Checklist

- [ ] Python 3.8+ installed
- [ ] Virtual environment created
- [ ] Dependencies installed
- [ ] Environment variables configured
- [ ] FreeSWITCH dialplan updated
- [ ] Systemd service created
- [ ] Service enabled and started
- [ ] Firewall configured
- [ ] Logs monitored
- [ ] Test call successful
- [ ] Audio quality verified
- [ ] TTS fallback tested
- [ ] Barge-in tested (if enabled)
- [ ] Performance metrics baseline
- [ ] Backup strategy in place
- [ ] Monitoring alerts configured

---

## 🆘 Support

### Logs Location
```bash
# Systemd journal
sudo journalctl -u bridge-relay

# TTS files
ls -lh /tmp/bridge_tts

# FreeSWITCH logs
tail -f /usr/local/freeswitch/log/freeswitch.log
```

### Debug Mode
```bash
# Enable debug logging
export DEBUG=true
sudo systemctl restart bridge-relay

# Watch logs
sudo journalctl -u bridge-relay -f
```

### Common Commands
```bash
# Check service status
sudo systemctl status bridge-relay

# View recent logs
sudo journalctl -u bridge-relay -n 100

# Follow logs
sudo journalctl -u bridge-relay -f

# Restart service
sudo systemctl restart bridge-relay

# Check connections
sudo netstat -an | grep :8001
```

---

## 🎉 Success Indicators

When everything is working correctly, you should see:

```
[INFO] [12345678] New call started
[INFO] [12345678] Connected to PersonaPlex
[INFO] [12345678] Handshake received
[INFO] [12345678] Text: Hello! How can I help you today?
[INFO] [12345678] Call ended
```

And the caller should:
- Hear the AI voice clearly
- Experience low latency (<500ms)
- Be able to interrupt (if barge-in enabled)
- Have natural conversation flow

---

**Deployment Status**: Ready for production
**Last Updated**: 2026-04-03
**Version**: 1.0.0
