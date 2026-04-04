# RunPod PersonaPlex Deployment Guide
## Connecting FreeSWITCH to RunPod PersonaPlex Instance

## 📋 Overview

This guide explains how to connect bridge_relay.py to a PersonaPlex instance running on RunPod cloud infrastructure.

### Architecture

```
FreeSWITCH (On-Premise)
    │ WebSocket (L16/8kHz)
    ↓
bridge_relay.py (On-Premise)
    │ Secure WebSocket (Opus/24kHz)
    │ wss://
    ↓
RunPod Proxy
    │ lhoac81oebncui-8998.proxy.runpod.net
    ↓
PersonaPlex Server (RunPod Pod)
    │ Port 8998
    ↓
GPU Instance (A100/A40)
```

---

## 🚀 Quick Start

### 1. Get Your RunPod Endpoint

```bash
# Your RunPod endpoint format:
wss://[POD_ID]-[PORT].proxy.runpod.net/api/chat

# Example:
wss://lhoac81oebncui-8998.proxy.runpod.net/api/chat
```

### 2. Configure Environment

```bash
# Copy ICICI Bank configuration
cp .env.icici_bank .env

# Edit configuration
nano .env
```

Update these values:
```bash
# Replace with your actual RunPod endpoint
PERSONAPLEX_URL=wss://lhoac81oebncui-8998.proxy.runpod.net/api/chat

# Add bearer token if required
BEARER_TOKEN=your_token_here

# Voice and prompt are already configured for ICICI Bank
VOICE_PROMPT=NATF0.pt
TEXT_PROMPT=You work for ICICI Bank...
```

### 3. Test Connection

```bash
# Activate virtual environment
source venv/bin/activate

# Test bridge
python3 bridge_relay.py
```

Expected output:
```
======================================================================
  BRIDGE RELAY - FreeSWITCH <-> PersonaPlex Direct Connection
======================================================================
  Listening on: 0.0.0.0:8001
  PersonaPlex:  wss://lhoac81oebncui-8998.proxy.runpod.net/api/chat
  Agent ID:     (none)
  TTS:          Enabled
  Barge-in:     Enabled
======================================================================

Waiting for calls...
```

---

## 🔧 RunPod-Specific Configuration

### SSL/TLS (Required for RunPod)

RunPod uses secure WebSocket (wss://) by default:

```bash
# Use wss:// not ws://
PERSONAPLEX_URL=wss://lhoac81oebncui-8998.proxy.runpod.net/api/chat
```

### Authentication

If your RunPod instance requires authentication:

```bash
# Option 1: Bearer token
BEARER_TOKEN=your_runpod_token

# Option 2: API key
PERSONAPLEX_API_KEY=your_api_key
```

### Network Configuration

```bash
# Ensure outbound HTTPS/WSS is allowed
sudo ufw allow out 443/tcp

# Test connectivity
curl -I https://lhoac81oebncui-8998.proxy.runpod.net
```

---

## 🏦 ICICI Bank Use Case

### Agent Configuration

**Name**: Priya Sharma  
**Role**: Customer Service Representative  
**Voice**: NATF0.pt (Natural Female Voice)  
**Specialization**: Personal accounts and loan products

### Services Provided

1. **Account Services**
   - Balance inquiries
   - Recent transactions
   - Account management

2. **Loan Products**
   - Personal loans (10.5% p.a.)
   - Home loans
   - Car loans
   - Education loans

3. **Security**
   - Identity verification via mobile number
   - Date of birth confirmation
   - Secure account access

### Sample Conversation Flow

```
Customer: "Hello, I want to check my account balance"
Priya: "Hello! I'm Priya Sharma from ICICI Bank. I'd be happy to help 
        you with your account balance. For security purposes, may I 
        please verify your registered mobile number?"

Customer: "It's 9876543210"
Priya: "Thank you. And could you please confirm your date of birth?"

Customer: "15th August 1990"
Priya: "Thank you for verifying. Your current account balance is 
        Rs 50,000. Is there anything else I can help you with today?"

Customer: "Tell me about personal loans"
Priya: "Certainly! ICICI Bank offers competitive personal loan rates 
        starting from 10.5% per annum with flexible EMI options. We 
        provide instant approval for eligible customers. Would you 
        like me to check your eligibility?"
```

---

## 📞 FreeSWITCH Integration

### Install Dialplan

```bash
# Copy ICICI Bank dialplan
sudo cp freeswitch/icici_bank_dialplan.xml \
    /usr/local/freeswitch/conf/dialplan/default/

# Reload FreeSWITCH
fs_cli -x "reloadxml"
```

### Available Extensions

| Extension | Purpose |
|-----------|---------|
| 1800 | Main customer service line |
| 1801 | Loans department |
| 1802 | Account services |
| 1899 | Test extension (debug mode) |

### Test Call

```bash
# Connect to FreeSWITCH
fs_cli

# Make test call
originate user/1000 1800

# Or from SIP phone, dial: 1800
```

---

## 🔍 Troubleshooting RunPod Connection

### Issue 1: Connection Timeout

```bash
# Check RunPod pod status
# Login to RunPod dashboard
# Verify pod is running and not stopped

# Test endpoint
curl -I https://lhoac81oebncui-8998.proxy.runpod.net

# Check DNS resolution
nslookup lhoac81oebncui-8998.proxy.runpod.net
```

### Issue 2: SSL Certificate Error

```python
# If you get SSL verification errors, check bridge_relay.py
# The code should handle SSL properly:

ssl_ctx = ssl.create_default_context()
# For self-signed certs (not recommended for production):
# ssl_ctx.check_hostname = False
# ssl_ctx.verify_mode = ssl.CERT_NONE
```

### Issue 3: Authentication Failed

```bash
# Verify token in .env
echo $BEARER_TOKEN

# Check RunPod logs
# Login to RunPod dashboard → Pod → Logs

# Test with curl
curl -H "Authorization: Bearer YOUR_TOKEN" \
     https://lhoac81oebncui-8998.proxy.runpod.net/health
```

### Issue 4: High Latency

```bash
# Check network latency to RunPod
ping lhoac81oebncui-8998.proxy.runpod.net

# Traceroute
traceroute lhoac81oebncui-8998.proxy.runpod.net

# Expected latency:
# - Same region: 20-50ms
# - Different region: 100-200ms
# - International: 200-500ms
```

### Issue 5: Pod Stopped/Idle

```bash
# RunPod may stop idle pods
# Check pod status in dashboard
# Restart pod if needed

# Enable auto-start in RunPod settings
# Or use RunPod API to keep pod alive
```

---

## 📊 Performance Optimization

### Latency Considerations

```
On-Premise → RunPod Latency Breakdown:

FreeSWITCH → bridge_relay:     5ms
bridge_relay processing:       10ms
Network to RunPod:            50-200ms (varies by region)
RunPod processing:            200ms
Network back:                 50-200ms
bridge_relay → FreeSWITCH:    5ms

Total: 320-620ms (acceptable for voice AI)
```

### Reduce Latency

1. **Choose Nearest RunPod Region**
   ```bash
   # Select region closest to your FreeSWITCH server
   # US East, US West, EU, Asia
   ```

2. **Use Dedicated GPU**
   ```bash
   # A100 or A40 for best performance
   # Avoid shared GPU instances
   ```

3. **Optimize Audio Settings**
   ```bash
   # In .env, adjust frame size
   OPUS_FRAME_MS=20  # Default, good balance
   # Try 10ms for lower latency (higher CPU)
   # Try 40ms for lower CPU (higher latency)
   ```

4. **Enable Barge-in**
   ```bash
   # Allows customer to interrupt
   BARGE_IN_ENABLED=true
   BARGE_IN_RMS_THRESHOLD=0.012
   ```

---

## 💰 Cost Optimization

### RunPod Pricing (Approximate)

```
GPU Instance Costs:
- A100 (80GB): $1.89/hour
- A40 (48GB): $0.79/hour
- RTX 4090: $0.44/hour

Monthly Costs (24/7):
- A100: ~$1,360/month
- A40: ~$570/month
- RTX 4090: ~$317/month
```

### Cost Saving Tips

1. **Use Spot Instances**
   ```bash
   # 50-70% cheaper than on-demand
   # May be interrupted (have fallback)
   ```

2. **Auto-Stop Idle Pods**
   ```bash
   # Configure in RunPod dashboard
   # Stop after 15 minutes of inactivity
   ```

3. **Scale Based on Call Volume**
   ```bash
   # Use RunPod API to start/stop pods
   # Scale up during business hours
   # Scale down at night
   ```

4. **Use Smaller GPU for Testing**
   ```bash
   # RTX 4090 for development
   # A40/A100 for production
   ```

---

## 🔒 Security Best Practices

### 1. Use Secure WebSocket (wss://)

```bash
# Always use wss:// for RunPod
PERSONAPLEX_URL=wss://lhoac81oebncui-8998.proxy.runpod.net/api/chat
```

### 2. Protect Bearer Token

```bash
# Store in .env (not in code)
BEARER_TOKEN=your_secret_token

# Set file permissions
chmod 600 .env

# Never commit to git
echo ".env" >> .gitignore
```

### 3. Restrict Network Access

```bash
# Only allow bridge_relay to access RunPod
sudo ufw allow out to lhoac81oebncui-8998.proxy.runpod.net port 443

# Block other outbound connections
sudo ufw default deny outgoing
```

### 4. Enable RunPod Authentication

```bash
# In RunPod dashboard:
# - Enable API key authentication
# - Rotate keys regularly
# - Use different keys for dev/prod
```

### 5. Monitor Access Logs

```bash
# Check bridge_relay logs
sudo journalctl -u bridge-relay -f

# Check RunPod logs in dashboard
# Look for unauthorized access attempts
```

---

## 📈 Monitoring and Alerts

### Key Metrics to Monitor

1. **Connection Status**
   ```bash
   # Check if bridge is connected
   sudo systemctl status bridge-relay
   
   # Check active calls
   sudo netstat -an | grep :8001 | grep ESTABLISHED
   ```

2. **Latency**
   ```bash
   # Monitor round-trip time
   ping lhoac81oebncui-8998.proxy.runpod.net
   
   # Expected: <200ms
   ```

3. **Error Rate**
   ```bash
   # Check for connection errors
   sudo journalctl -u bridge-relay | grep ERROR
   
   # Expected: <1% error rate
   ```

4. **RunPod Pod Status**
   ```bash
   # Use RunPod API
   curl -H "Authorization: Bearer $RUNPOD_API_KEY" \
        https://api.runpod.io/v1/pods/$POD_ID
   ```

### Set Up Alerts

```bash
# Create monitoring script
cat > /opt/bridge-relay/monitor.sh << 'EOF'
#!/bin/bash
# Check if bridge is running
if ! systemctl is-active --quiet bridge-relay; then
    echo "ALERT: bridge-relay is down" | mail -s "Bridge Alert" admin@example.com
fi

# Check RunPod connectivity
if ! curl -s -o /dev/null -w "%{http_code}" https://lhoac81oebncui-8998.proxy.runpod.net | grep -q "200\|101"; then
    echo "ALERT: RunPod endpoint unreachable" | mail -s "RunPod Alert" admin@example.com
fi
EOF

# Add to crontab (check every 5 minutes)
crontab -e
*/5 * * * * /opt/bridge-relay/monitor.sh
```

---

## 🧪 Testing Checklist

- [ ] RunPod pod is running and accessible
- [ ] bridge_relay.py connects to RunPod endpoint
- [ ] FreeSWITCH dialplan configured
- [ ] Test call to extension 1800 successful
- [ ] Audio quality is clear (no distortion)
- [ ] Latency is acceptable (<500ms)
- [ ] Agent responds with correct identity (Priya Sharma)
- [ ] Agent mentions ICICI Bank services
- [ ] Barge-in works (customer can interrupt)
- [ ] TTS fallback works (if PersonaPlex audio fails)
- [ ] Call logs are recorded properly
- [ ] Security verification works (mobile, DOB)
- [ ] Loan information is accurate (10.5% p.a.)
- [ ] Account balance is mentioned (Rs 50,000)

---

## 📚 Additional Resources

### RunPod Documentation
- [RunPod Docs](https://docs.runpod.io/)
- [RunPod API](https://docs.runpod.io/reference/api)
- [GPU Pricing](https://www.runpod.io/pricing)

### PersonaPlex
- Voice models documentation
- API reference
- Best practices

### FreeSWITCH
- [Dialplan Guide](https://freeswitch.org/confluence/display/FREESWITCH/Dialplan)
- [mod_socket](https://freeswitch.org/confluence/display/FREESWITCH/mod_socket)

---

## 🎯 Production Deployment

### Step-by-Step

1. **Provision RunPod Pod**
   ```bash
   # Login to RunPod dashboard
   # Create new pod with A40/A100 GPU
   # Deploy PersonaPlex container
   # Note the proxy URL
   ```

2. **Configure bridge_relay**
   ```bash
   # Copy configuration
   sudo cp .env.icici_bank /opt/bridge-relay/.env
   
   # Update RunPod URL
   sudo nano /opt/bridge-relay/.env
   # Set: PERSONAPLEX_URL=wss://YOUR-POD-ID-8998.proxy.runpod.net/api/chat
   ```

3. **Install systemd service**
   ```bash
   cd systemd
   sudo bash install.sh
   ```

4. **Configure FreeSWITCH**
   ```bash
   sudo cp freeswitch/icici_bank_dialplan.xml \
       /usr/local/freeswitch/conf/dialplan/default/
   fs_cli -x "reloadxml"
   ```

5. **Start services**
   ```bash
   sudo systemctl start bridge-relay
   sudo systemctl status bridge-relay
   ```

6. **Test end-to-end**
   ```bash
   # Make test call
   fs_cli
   originate user/1000 1800
   ```

7. **Monitor and optimize**
   ```bash
   # Watch logs
   sudo journalctl -u bridge-relay -f
   
   # Monitor performance
   watch -n 5 'sudo netstat -an | grep :8001'
   ```

---

## 🆘 Support

### Logs Location
```bash
# bridge_relay logs
sudo journalctl -u bridge-relay -n 100

# FreeSWITCH logs
tail -f /usr/local/freeswitch/log/freeswitch.log

# RunPod logs
# Check RunPod dashboard → Pod → Logs
```

### Common Issues

1. **"Connection refused"** → Check RunPod pod status
2. **"SSL error"** → Verify wss:// URL and certificates
3. **"Authentication failed"** → Check BEARER_TOKEN
4. **"High latency"** → Choose closer RunPod region
5. **"No audio"** → Check codec settings and network

---

**Deployment Status**: Ready for production with RunPod  
**Use Case**: ICICI Bank Customer Service  
**Agent**: Priya Sharma  
**Last Updated**: 2026-04-03
