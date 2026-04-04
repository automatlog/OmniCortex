# Relay.py - HTTP vs WebSocket Analysis

## 🔍 Current Implementation

### What relay.py Does

**relay.py** is a **voice gateway/bridge** that:
1. Accepts WebSocket connections from FreeSWITCH/telephony systems
2. Forwards audio to PersonaPlex server via WebSocket
3. Receives AI responses and sends back to telephony

### Current Architecture

```
FreeSWITCH/Telephony
    │ WebSocket
    ↓
relay.py (Port 8099)
    │ WebSocket (ws://localhost:8998/api/chat)
    ↓
PersonaPlex Server
    │ HTTP/REST
    ↓
OmniCortex API (Port 8000)
```

### Current Configuration

```python
# Default in relay.py
personaplex_ws = "ws://127.0.0.1:8998/api/chat"  # WebSocket URL

# Environment variable
PERSONAPLEX_WS=ws://127.0.0.1:8998/api/chat
```

---

## ❓ Question: Should We Use HTTP Port URL?

### Current: WebSocket Connection
```python
personaplex_ws = "ws://127.0.0.1:8998/api/chat"
```

### Alternative: HTTP Port URL?
```python
# This would NOT work for relay.py
personaplex_http = "http://127.0.0.1:8998/api/chat"  # ❌ Wrong
```

---

## 🎯 Answer: NO - WebSocket is Required

### Why WebSocket is Necessary

#### 1. **Real-Time Bidirectional Communication**
```python
# relay.py needs to:
# - Send audio frames continuously (client → server)
# - Receive audio frames continuously (server → client)
# - Both happen simultaneously (full-duplex)

# WebSocket: ✅ Perfect for this
async def _fs_to_upstream_loop(self):
    # Continuously send audio
    while not self.closed:
        audio_data = await get_audio()
        await self.upstream_ws.send_bytes(audio_data)

async def _upstream_to_fs_loop(self):
    # Continuously receive audio
    async for msg in self.upstream_ws:
        await self.fs_ws.send_bytes(msg.data)
```

#### 2. **Low Latency Requirements**
- Voice conversations need <500ms latency
- HTTP request/response adds overhead
- WebSocket maintains persistent connection

#### 3. **Streaming Audio**
```python
# Audio streaming pattern (relay.py)
while conversation_active:
    # Send user audio frame
    await upstream_ws.send_bytes(b'\x01' + opus_audio)
    
    # Receive AI audio frame
    ai_audio = await upstream_ws.receive()
    
    # Send to telephony
    await fs_ws.send_bytes(ai_audio)
```

---

## 📊 HTTP vs WebSocket Comparison

### HTTP (Request/Response)
```
❌ NOT suitable for relay.py

Client                    Server
  │                         │
  ├──── POST /audio ───────>│
  │                         │ (process)
  │<──── Response ──────────┤
  │                         │
  ├──── POST /audio ───────>│  (New connection each time)
  │                         │
  │<──── Response ──────────┤
  │                         │

Problems:
- Connection overhead per request
- Cannot receive while sending
- Higher latency
- Not full-duplex
```

### WebSocket (Persistent Connection)
```
✅ Perfect for relay.py

Client                    Server
  │                         │
  ├──── WS Connect ────────>│
  │<──── Handshake ─────────┤
  │                         │
  ├──── Audio Frame ───────>│
  │<──── Audio Frame ───────┤
  ├──── Audio Frame ───────>│
  │<──── Audio Frame ───────┤
  │<──── Text Frame ────────┤
  ├──── Audio Frame ───────>│
  │<──── Audio Frame ───────┤
  │         ...              │

Benefits:
- Single persistent connection
- Full-duplex (send + receive simultaneously)
- Low latency
- Efficient for streaming
```

---

## 🔧 When HTTP Port URL IS Beneficial

### Scenario 1: REST API Calls
```python
# OmniCortex API uses HTTP for REST endpoints
# This is CORRECT usage

# Get agents list
GET http://localhost:8000/agents

# Get agent prompt
GET http://localhost:8000/agents/{id}/system-prompt

# Query with RAG
POST http://localhost:8000/query
```

### Scenario 2: Health Checks
```python
# relay.py exposes HTTP health endpoint
GET http://localhost:8099/health

# Returns:
{
  "status": "ok",
  "personaplex_ws": "ws://127.0.0.1:8998/api/chat",
  "active_calls": 2
}
```

### Scenario 3: Static Content
```python
# Serving UI files
GET http://localhost:8998/index.html
GET http://localhost:8998/assets/app.js
```

---

## 💡 Correct Usage Patterns

### 1. Voice Relay (relay.py)
```python
# ✅ CORRECT: Use WebSocket
personaplex_ws = "ws://127.0.0.1:8998/api/chat"

# ❌ WRONG: Don't use HTTP
personaplex_http = "http://127.0.0.1:8998/api/chat"
```

### 2. OmniCortex API Integration
```python
# ✅ CORRECT: Use HTTP for REST API
omnicortex_base_url = "http://localhost:8000"

# Fetch agent data
async with session.get(f"{omnicortex_base_url}/agents/{id}") as resp:
    agent = await resp.json()
```

### 3. Mixed Usage (relay.py does this)
```python
# ✅ CORRECT: Use both appropriately

# HTTP for fetching agent configuration
omnicortex_api_base = "http://localhost:8000"
agent_data = await http_get(f"{omnicortex_api_base}/agents/{id}")

# WebSocket for voice streaming
personaplex_ws = "ws://127.0.0.1:8998/api/chat"
ws = await session.ws_connect(personaplex_ws)
```

---

## 🚀 Performance Comparison

### Latency Test Results (Typical)

#### WebSocket (Current)
```
Connection Setup:    50ms (once)
Audio Frame Send:    1-5ms
Audio Frame Receive: 1-5ms
Total Round Trip:    200-300ms
Overhead:            Minimal
```

#### HTTP (Hypothetical)
```
Connection Setup:    50ms (per request)
Audio Frame Send:    50-100ms
Audio Frame Receive: 50-100ms
Total Round Trip:    500-1000ms
Overhead:            High
```

### Bandwidth Efficiency

#### WebSocket
```
Frame overhead:      2-14 bytes per frame
Connection reuse:    Yes
Compression:         Optional (per-message)
Efficiency:          High
```

#### HTTP
```
Header overhead:     200-500 bytes per request
Connection reuse:    Limited (HTTP/1.1 keep-alive)
Compression:         Per-response
Efficiency:          Lower
```

---

## 🎯 Recommendations

### For relay.py Voice Gateway

**✅ Keep Using WebSocket**

Reasons:
1. **Full-duplex required** - Send and receive simultaneously
2. **Low latency critical** - Voice needs <500ms
3. **Streaming audio** - Continuous data flow
4. **Efficient** - Single persistent connection
5. **Industry standard** - WebRTC, telephony use WebSocket

### For OmniCortex API Integration

**✅ Keep Using HTTP**

Reasons:
1. **REST API pattern** - Request/response model
2. **Stateless operations** - Get agent, fetch prompt
3. **Standard HTTP methods** - GET, POST, PUT, DELETE
4. **Easy debugging** - curl, Postman, browser
5. **Caching friendly** - HTTP caching headers

---

## 🔍 Code Evidence from relay.py

### WebSocket Connection Setup
```python
# Line ~850 in relay.py
async def _connect_upstream(self) -> None:
    params = {
        "text_prompt": self.prompt.system_prompt,
        "voice_prompt": self.prompt.voice_prompt,
        "seed": str(self.cfg.seed),
    }
    url = self.cfg.personaplex_ws  # WebSocket URL
    separator = "&" if "?" in url else "?"
    upstream_url = f"{url}{separator}{urlencode(params)}"
    
    # SSL context for wss://
    ssl_ctx = None
    if upstream_url.startswith("wss://") and not self.cfg.personaplex_ssl_verify:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
    
    # Connect via WebSocket
    self.upstream_ws = await self.service.http.ws_connect(
        upstream_url,
        ssl=ssl_ctx,
        timeout=aiohttp.ClientTimeout(total=self.cfg.connect_timeout_sec),
    )
```

### Bidirectional Audio Streaming
```python
# Sending audio to PersonaPlex
async def _fs_to_upstream_loop(self):
    while not self.closed:
        # Get audio from FreeSWITCH
        audio_data = await self.get_audio_from_fs()
        
        # Send to PersonaPlex via WebSocket
        await self.upstream_ws.send_bytes(audio_data)

# Receiving audio from PersonaPlex
async def _upstream_to_fs_loop(self):
    async for msg in self.upstream_ws:
        if msg.type == aiohttp.WSMsgType.BINARY:
            # Send to FreeSWITCH
            await self.fs_ws.send_bytes(msg.data)
```

---

## 📝 Configuration Examples

### Current (Correct) Configuration

```bash
# Environment variables
export PERSONAPLEX_WS=ws://127.0.0.1:8998/api/chat
export OMNICORTEX_API_BASE=http://localhost:8000

# Command line
python core/voice/relay.py \
  --personaplex-ws ws://127.0.0.1:8998/api/chat \
  --omnicortex-api-base http://localhost:8000
```

### Production with SSL

```bash
# Use wss:// for secure WebSocket
export PERSONAPLEX_WS=wss://personaplex.example.com/api/chat
export OMNICORTEX_API_BASE=https://api.example.com

# With SSL verification
python core/voice/relay.py \
  --personaplex-ws wss://personaplex.example.com/api/chat \
  --personaplex-ssl-verify \
  --omnicortex-api-base https://api.example.com
```

---

## 🐛 Common Mistakes

### ❌ Mistake 1: Using HTTP for Voice
```python
# WRONG - Will not work
personaplex_ws = "http://127.0.0.1:8998/api/chat"

# Error: Cannot establish WebSocket connection to HTTP URL
```

### ❌ Mistake 2: Using WebSocket for REST API
```python
# WRONG - Inefficient and unnecessary
omnicortex_ws = "ws://localhost:8000/agents"

# Should use HTTP:
omnicortex_http = "http://localhost:8000/agents"
```

### ❌ Mistake 3: Wrong Protocol for SSL
```python
# WRONG - Mixed protocols
personaplex_ws = "http://127.0.0.1:8998/api/chat"  # Should be ws://
omnicortex_api = "ws://localhost:8000"             # Should be http://

# CORRECT
personaplex_ws = "ws://127.0.0.1:8998/api/chat"
omnicortex_api = "http://localhost:8000"

# CORRECT with SSL
personaplex_ws = "wss://example.com/api/chat"
omnicortex_api = "https://example.com"
```

---

## 🎯 Summary

### Question: Is HTTP port URL beneficial for relay.py?

**Answer: NO**

### Why?
1. **WebSocket is required** for full-duplex voice streaming
2. **HTTP cannot handle** simultaneous send/receive
3. **Latency would increase** significantly with HTTP
4. **Current implementation is optimal** for voice use case

### When to Use Each

| Use Case | Protocol | Example |
|----------|----------|---------|
| Voice streaming (relay.py) | WebSocket | `ws://localhost:8998/api/chat` |
| REST API calls | HTTP | `http://localhost:8000/agents` |
| Static files | HTTP | `http://localhost:8998/index.html` |
| Health checks | HTTP | `http://localhost:8099/health` |
| Secure voice | WebSocket+SSL | `wss://example.com/api/chat` |
| Secure API | HTTPS | `https://example.com/api` |

---

## 🚀 Optimization Recommendations

### Current Setup is Already Optimal

The relay.py implementation is well-designed:

✅ Uses WebSocket for voice (correct)
✅ Uses HTTP for API calls (correct)
✅ Supports SSL/TLS (wss://, https://)
✅ Handles connection failures gracefully
✅ Implements health checks via HTTP
✅ Efficient audio streaming

### No Changes Needed

**Recommendation**: Keep the current architecture. It follows best practices for real-time voice applications.

---

## 📚 Additional Resources

- **WebSocket RFC**: https://tools.ietf.org/html/rfc6455
- **WebRTC**: Uses WebSocket for signaling
- **SIP over WebSocket**: RFC 7118
- **HTTP/2 vs WebSocket**: Different use cases

---

## 🎉 Conclusion

**Using HTTP port URL for relay.py voice streaming would NOT be beneficial.**

The current WebSocket implementation is:
- ✅ Correct for the use case
- ✅ Industry standard
- ✅ Optimal for performance
- ✅ Required for full-duplex audio
- ✅ Lower latency than HTTP

**Keep using WebSocket (`ws://` or `wss://`) for voice streaming in relay.py.**
