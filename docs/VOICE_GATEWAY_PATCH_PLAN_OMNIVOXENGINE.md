# Voice Gateway Patch Plan (One Sprint)

## File Path
`c:\Users\AMAN\Downloads\MetaCortex\OmniCortex\docs\VOICE_GATEWAY_PATCH_PLAN_OMNIVOXENGINE.md`

## Goal
Integrate telecom voice from FreeSWITCH (OmniVoxEngine.UI) to OmniCortex Moshi WebSocket (`/voice/ws`) using a media gateway, with per-call context (`agent_id`, bearer token, user id), clean lifecycle handling, and production-grade observability.

## Scope
1. FreeSWITCH call control remains in `OmniVoxEngine.UI`.
2. AI media streaming handled by a new Voice Gateway layer.
3. OmniCortex remains Moshi proxy (`/voice/ws`) with bearer auth.
4. No Liquid/TTS-only fallback in this sprint.

## Target Architecture
1. FreeSWITCH answers call.
2. FreeSWITCH forks call media to Voice Gateway (RTP/WebSocket media module).
3. Voice Gateway opens WS to OmniCortex `/voice/ws?agent_id=...`.
4. Voice Gateway forwards caller audio to OmniCortex (binary frames).
5. OmniCortex returns AI audio frames; Voice Gateway injects back into call leg.
6. On hangup, all resources are closed and metrics flushed.

## Current Code Anchors (Ln)
Use these line anchors (`Ln`) as primary insertion points.

1. `api.py:2233` - `_authenticate_voice_websocket(...)`
2. `api.py:2255` - `@app.websocket("/voice/ws")`
3. `api.py:2374` - `POST /voice/transcribe` disabled in Moshi-only mode
4. `api.py:2403` - `POST /voice/chat` disabled in Moshi-only mode
5. `core/auth.py:26` - `verify_bearer_token(...)`
6. `personaplex/moshi/moshi/server.py:135` - `handle_chat(...)` websocket entrypoint
7. `personaplex/moshi/moshi/server.py:202` - inbound audio frame kind (`0x01`)
8. `personaplex/moshi/moshi/server.py:262` - outbound audio frame kind (`0x01`)
9. `OmniVoxEngine.UI/Program.cs:146` - existing service registrations start
10. `OmniVoxEngine.UI/Program.cs:187` - hosted services registration block
11. `OmniVoxEngine.UI/appsettings.json:38` - `OutboundSocket` section (add `VoiceGateway` nearby)
12. `OmniVoxEngine.UI/Core/Services/VoiceOutboundIVRService.cs:48` - `HandleSessionAsync(...)`
13. `OmniVoxEngine.UI/Core/CallFlow/DefaultVoiceCallFlowService.cs:1534` - webhook node handler
14. `OmniVoxEngine.UI/Core/CallFlow/DefaultVoiceCallFlowService.cs:1627` - TTS handler (current dynamic audio logic)
15. `OmniVoxEngine.UI/Core/Fs/FsVoiceBlaster.cs:367` - `BuildOriginate(...)`
16. `OmniVoxEngine.UI/Core/Fs/FsVoiceBlaster.cs:392` - `execute_on_answer='socket ...'`
17. `OmniVoxEngine.UI/Core/MinimulAPICode/CallRequestEndpoints.cs:20` - `/api/ogcall/call`
18. `DotNetFreeSwitch/Handlers/outbound/OutboundSession.cs:41` - outbound session core (add media helper extensions near command APIs)

## Insert-After Ln Map (Exact Patch Entry)
Use this when implementing patches so edits are deterministic.

### OmniCortex (Python) - Insert After
1. `api.py` after `Ln 2254`:
   add optional helper utilities for voice bridge context (`call_uuid`, `agent_id`, `session_id`) normalization before `@app.websocket("/voice/ws")`.
2. `api.py` after `Ln 2276`:
   read and validate additional query params (`call_uuid`, `session_id`) and attach to structured logs.
3. `api.py` after `Ln 2319`:
   add a structured connect log with `call_uuid`, `agent_id`, upstream URL (without secrets), and request correlation id.
4. `api.py` after `Ln 2353`:
   add a session-close summary log (duration, bytes in/out, close reason).
5. `core/auth.py` after `Ln 67`:
   add optional claim extraction helper for downstream voice tracing (no auth behavior change).
6. `personaplex/moshi/moshi/server.py` after `Ln 146`:
   add connect metadata logging hooks (`call_uuid`, `agent_id`) if present in query/header.

### OmniVoxEngine (C#) - Insert After
1. `OmniVoxEngine.UI/Program.cs` after `Ln 190`:
   register `VoiceGatewayOptions`, `IVoiceAiBridgeService`, `IFreeSwitchMediaForkService`, `IVoiceGatewaySessionStore`.
2. `OmniVoxEngine.UI/appsettings.json` after `Ln 40`:
   add `"VoiceGateway"` configuration block.
3. `OmniVoxEngine.UI/Core/Services/VoiceOutboundIVRService.cs` after `Ln 48`:
   start/stop AI bridge lifecycle in `HandleSessionAsync(...)`.
4. `OmniVoxEngine.UI/Core/CallFlow/DefaultVoiceCallFlowService.cs` after `Ln 1534`:
   add conversational AI node handler and routing.
5. `OmniVoxEngine.UI/Core/Fs/FsVoiceBlaster.cs` after `Ln 392`:
   replace hardcoded socket host/port with config-based value.
6. `OmniVoxEngine.UI/Core/MinimulAPICode/CallRequestEndpoints.cs` after `Ln 20`:
   validate and map AI payload fields (`AgentId`, token key, prompts, session).
7. `DotNetFreeSwitch/Handlers/outbound/OutboundSession.cs` after `Ln 41`:
   add reusable wrappers for media-fork start/stop and `uuid_*` helpers.

## Patch Plan by Class/File

### A) OmniVoxEngine.UI

#### 1) `OmniVoxEngine.UI/Program.cs`
Add DI registrations and config binding.

```csharp
builder.Services.Configure<VoiceGatewayOptions>(
    builder.Configuration.GetSection("VoiceGateway"));
builder.Services.AddSingleton<IVoiceAiBridgeService, VoiceAiBridgeService>();
builder.Services.AddSingleton<IFreeSwitchMediaForkService, FreeSwitchMediaForkService>();
builder.Services.AddSingleton<IVoiceGatewaySessionStore, VoiceGatewaySessionStore>();
```

#### 2) `OmniVoxEngine.UI/appsettings.json`
Add new section:

```json
"VoiceGateway": {
  "Enabled": true,
  "BaseUrl": "ws://127.0.0.1:8099",
  "ConnectTimeoutMs": 3000,
  "ReadTimeoutMs": 15000,
  "KeepAliveSeconds": 20,
  "AudioCodec": "pcm16",
  "SampleRate": 8000,
  "ChannelName": "VOICE"
}
```

#### 3) New file: `OmniVoxEngine.UI/Core/Models/VoiceGatewayOptions.cs`
```csharp
public sealed class VoiceGatewayOptions
{
    public bool Enabled { get; set; } = true;
    public string BaseUrl { get; set; } = "";
    public int ConnectTimeoutMs { get; set; } = 3000;
    public int ReadTimeoutMs { get; set; } = 15000;
    public int KeepAliveSeconds { get; set; } = 20;
    public string AudioCodec { get; set; } = "pcm16";
    public int SampleRate { get; set; } = 8000;
    public string ChannelName { get; set; } = "VOICE";
}
```

#### 4) New file: `OmniVoxEngine.UI/Core/Services/IVoiceAiBridgeService.cs`
```csharp
public interface IVoiceAiBridgeService
{
    Task StartAsync(VoiceBridgeStartRequest request, CancellationToken ct);
    Task StopAsync(string callUuid, string reason, CancellationToken ct);
    bool IsActive(string callUuid);
}
```

#### 5) New file: `OmniVoxEngine.UI/Core/Models/VoiceBridgeStartRequest.cs`
```csharp
public sealed class VoiceBridgeStartRequest
{
    public string CallUuid { get; init; } = "";
    public string AgentId { get; init; } = "";
    public string BearerToken { get; init; } = "";
    public string? UserId { get; init; }
    public string? VoicePrompt { get; init; }
    public string? TextPrompt { get; init; }
    public string? SessionId { get; init; }
    public string ChannelName { get; init; } = "VOICE";
    public string ChannelType { get; init; } = "UTILITY";
}
```

#### 6) New file: `OmniVoxEngine.UI/Core/Services/IFreeSwitchMediaForkService.cs`
```csharp
public interface IFreeSwitchMediaForkService
{
    Task StartForkAsync(OutboundSocket session, string callUuid, string forkUrl, CancellationToken ct);
    Task StopForkAsync(OutboundSocket session, string callUuid, CancellationToken ct);
}
```

#### 7) New file: `OmniVoxEngine.UI/Core/Services/FreeSwitchMediaForkService.cs`
Implementation wrapper around FreeSWITCH media-fork commands (module-specific command text hidden here).

```csharp
public sealed class FreeSwitchMediaForkService : IFreeSwitchMediaForkService
{
    public Task StartForkAsync(OutboundSocket session, string callUuid, string forkUrl, CancellationToken ct);
    public Task StopForkAsync(OutboundSocket session, string callUuid, CancellationToken ct);
}
```

#### 8) New file: `OmniVoxEngine.UI/Core/Services/VoiceAiBridgeService.cs`
Orchestrates per-call bridge lifecycle.

```csharp
public sealed class VoiceAiBridgeService : IVoiceAiBridgeService
{
    public Task StartAsync(VoiceBridgeStartRequest request, CancellationToken ct);
    public Task StopAsync(string callUuid, string reason, CancellationToken ct);
    public bool IsActive(string callUuid);
}
```

#### 9) New file: `OmniVoxEngine.UI/Core/Services/IVoiceGatewaySessionStore.cs`
```csharp
public interface IVoiceGatewaySessionStore
{
    bool TryAdd(VoiceGatewaySession session);
    bool TryGet(string callUuid, out VoiceGatewaySession session);
    bool TryRemove(string callUuid, out VoiceGatewaySession session);
}
```

#### 10) New file: `OmniVoxEngine.UI/Core/Models/VoiceGatewaySession.cs`
```csharp
public sealed class VoiceGatewaySession
{
    public string CallUuid { get; init; } = "";
    public string AgentId { get; init; } = "";
    public DateTimeOffset StartedAt { get; init; } = DateTimeOffset.UtcNow;
    public string Status { get; set; } = "starting";
    public string? Error { get; set; }
}
```

#### 11) `OmniVoxEngine.UI/Core/Services/VoiceOutboundIVRService.cs`
Hook bridge start/stop in `HandleSessionAsync(...)`.

Add methods:

```csharp
private VoiceBridgeStartRequest BuildBridgeRequest(OutboundSocket session, string uuid, VoiceApiRequestData callData);
private Task StartAiBridgeAsync(OutboundSocket session, string uuid, VoiceApiRequestData callData, CancellationToken ct);
private Task StopAiBridgeAsync(string uuid, string reason, CancellationToken ct);
```

Integration points:
1. After callData cache load success -> `StartAiBridgeAsync(...)`.
2. On hangup path and `finally` -> `StopAiBridgeAsync(...)`.

#### 12) `OmniVoxEngine.UI/Core/CallFlow/DefaultVoiceCallFlowService.cs`
Add optional conversational node handler for dynamic AI mode:

```csharp
public Task HandleAiConversationalNodeAsync(
    string logPrefix,
    string uuid,
    OutboundSocket session,
    FlowDataNode flowData,
    VoiceApiRequestData callData,
    CancellationToken ct);
```

Use when campaign flow requires live AI rather than static playback.

#### 13) `OmniVoxEngine.UI/Core/MinimulAPICode/CallRequestEndpoints.cs`
Validate and pass AI fields from API payload:

```csharp
private static bool ValidateVoiceAiFields(VoiceApiRequestData req, out string error);
```

Required when AI mode enabled:
1. `AgentId`
2. `BearerToken` (or secure lookup key)

#### 14) `OmniVoxEngine.UI/Core/Models` / request DTO
Extend `VoiceApiRequestData` with:

```csharp
public string? AgentId { get; set; }
public string? OmniAuthToken { get; set; }
public string? OmniUserId { get; set; }
public string? VoicePrompt { get; set; }
public string? TextPrompt { get; set; }
public string? SessionId { get; set; }
public bool EnableAiBridge { get; set; }
```

---

### B) DotNetFreeSwitch

#### 15) New extension wrappers (recommended)
File: `DotNetFreeSwitch/Handlers/outbound/OutboundSession.cs` (or helper extension file)

```csharp
public Task<ApiResponse> UuidSetVarAsync(string uuid, string key, string value);
public Task<ApiResponse> UuidGetVarAsync(string uuid, string key);
public Task<ApiResponse> UuidBreakAsync(string uuid);
public Task<ApiResponse> StartMediaForkAsync(string uuid, string targetUrl);
public Task<ApiResponse> StopMediaForkAsync(string uuid);
```

This avoids command strings scattered across services.

---

### C) OmniCortex (already mostly ready)

#### 16) `api.py`
No major API change required for MVP. Existing `/voice/ws` already supports:
1. Bearer auth
2. `x-user-id`
3. query params (`agent_id`, `text_prompt`, `voice_prompt`, `seed`)

Recommended optional enhancement:
1. Add structured session logs for telecom call UUID + WS session status.

## Voice Gateway Service (separate process)
If media-fork module emits RTP/PCM and not Moshi packet format directly, implement a dedicated service:
1. Inbound from FreeSWITCH media stream.
2. Convert telecom audio to Moshi expected frame protocol.
3. Maintain WS to OmniCortex `/voice/ws`.
4. Return AI audio back to FreeSWITCH media leg.

Interface contract:
```text
POST /sessions/start
POST /sessions/{callUuid}/stop
GET  /sessions/{callUuid}
```

## One Sprint Breakdown (5 Days)
1. Day 1: Config + DTO + DI + request validation.
2. Day 2: `IVoiceAiBridgeService` + session store + lifecycle wiring in `VoiceOutboundIVRService`.
3. Day 3: `IFreeSwitchMediaForkService` + DotNetFreeSwitch wrappers + command hardening.
4. Day 4: End-to-end call test with one FreeSWITCH server + one agent.
5. Day 5: Retry/timeouts, metrics, failure handling, runbook.

## Acceptance Criteria
1. Live call connects and AI responds within target latency.
2. On hangup, bridge and fork always stop (no leaked sessions).
3. Invalid token/agent blocks bridge safely and call degrades gracefully.
4. Per-call logs include `call_uuid`, `agent_id`, `bridge_status`, error reason.
5. Concurrent calls stable for agreed CPS/load target.

## Risks and Controls
1. Codec mismatch (8k telephony vs model/audio path) -> explicit transcoding in gateway.
2. Token handling in payload -> use secure retrieval/store, avoid plain logging.
3. Media-fork module differences per FS build -> isolate in `FreeSwitchMediaForkService`.
4. Backpressure during bursts -> bounded queues and timeout policy.

## Minimal Test Matrix
1. Outbound answered call, no DTMF, full AI conversation.
2. Early hangup before AI start.
3. Token invalid / auth unavailable.
4. Agent not found.
5. FreeSWITCH node failover.
6. 20 concurrent calls smoke test.
