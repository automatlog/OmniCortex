# PersonaPlex Voice AI - Complete Workflow & Upgrade Guide

## 🎯 Overview

PersonaPlex is a **React-based full-duplex voice AI system** that enables real-time conversations with AI agents using voice. It integrates with OmniCortex backend for knowledge retrieval (RAG) and agent management.

---

## 📊 System Architecture

```
┌─────────────────┐
│  React UI       │ (Vite + TypeScript + TailwindCSS)
│  Port: 8998     │
└────────┬────────┘
         │ WebSocket
         ↓
┌─────────────────┐
│ PersonaPlex     │ (Python Moshi Server)
│ Server          │
│ Port: 8998      │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ OmniCortex API  │ (FastAPI Backend)
│ Port: 8000      │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ PostgreSQL +    │ (Knowledge Base)
│ pgvector        │
└─────────────────┘
```

---

## 🔄 Complete Workflow

### 1. **User Opens UI** (React Frontend)
- User navigates to `http://localhost:8998`
- UI loads with agent selection, voice options, and text prompt
- TailwindCSS + DaisyUI provides styling

### 2. **Agent Selection & Knowledge Loading**
```typescript
// UI fetches available agents from OmniCortex
GET /api/agents
→ Returns list of agents with their IDs, names, types

// User selects an agent
// UI loads agent's system prompt + RAG context
GET /api/agent-prompt?agent_id=<id>&context_query=<optional>
→ Returns: system_prompt + voice_context (from RAG)
```

### 3. **Knowledge Retrieval (RAG)**
When an agent is selected:
- **System Prompt**: Base instructions for the AI (e.g., "You are a helpful assistant")
- **Voice Context**: Retrieved from pgvector using semantic search
  - Top-K documents (default: 3) are fetched
  - Context is appended to system prompt
  - Uses `context_query` parameter or text_prompt as seed

```python
# Server-side (moshi/server.py)
async def fetch_agent_bootstrap(agent_id, context_query):
    # 1. Get base system prompt
    base_prompt = await get_system_prompt(agent_id)
    
    # 2. Retrieve RAG context
    context = await get_voice_context(agent_id, context_query, top_k=3)
    
    # 3. Combine
    full_prompt = f"{base_prompt}\n\nContext: {context}"
    return full_prompt
```

### 4. **Voice Connection**
```typescript
// WebSocket connection to PersonaPlex
ws://localhost:8998/api/chat?
  agent_id=<id>&
  voice_prompt=NATF0.pt&
  context_query=<text>&
  voice_mode=personaplex
```

### 5. **Real-Time Voice Processing**
```
User speaks → Microphone
    ↓
Opus Encoding (browser)
    ↓
WebSocket → PersonaPlex Server
    ↓
Mimi Audio Encoder (converts to tokens)
    ↓
LLM Generation (with RAG context)
    ↓
Mimi Audio Decoder (tokens to audio)
    ↓
Opus Decoding
    ↓
Speaker Output
```

---

## 🎤 Available Voices

### Natural Voices (Conversational)
```typescript
const NATURAL_VOICES = {
  female: ["NATF0.pt", "NATF1.pt", "NATF2.pt", "NATF3.pt"],
  male: ["NATM0.pt", "NATM1.pt", "NATM2.pt", "NATM3.pt"]
};
```

### Variety Voices (More Varied)
```typescript
const VARIETY_VOICES = {
  female: ["VARF0.pt", "VARF1.pt", "VARF2.pt", "VARF3.pt", "VARF4.pt"],
  male: ["VARM0.pt", "VARM1.pt", "VARM2.pt", "VARM3.pt", "VARM4.pt"]
};
```

**Recommendation**: Use `NATF*` or `NATM*` for English conversations.

---

## 🇮🇳 Hindi Support

### Current Status
- **Officially**: PersonaPlex is optimized for **English only**
- **Experimental**: Hindi can work but is **unofficial/experimental**

### How to Enable Hindi

#### 1. **Text Prompt in Hindi**
```typescript
const hindiPrompt = "आप एक सहायक हैं। हिंदी में बातचीत करें।";
// (You are a helpful assistant. Converse in Hindi.)
```

#### 2. **Detection in UI**
```typescript
const isLikelyHindi = (text: string): boolean => {
  // Detects Devanagari script (U+0900-U+097F)
  return /[\u0900-\u097F]/.test(text) || /\bhindi\b/i.test(text);
};
```

#### 3. **Voice Selection for Hindi**
- Use **NATF*** or **NATM*** voices
- These are more neutral and may handle Hindi better
- **Note**: Voice quality in Hindi is not guaranteed

#### 4. **Server Configuration**
```bash
# No special config needed, but you can:
export PERSONAPLEX_EAGER_VOICE_CONTEXT=true  # Load context eagerly
```

### Limitations
- Voice synthesis quality may be lower
- Pronunciation may not be native
- Better results with English-Hindi code-switching
- Consider using Cascade mode (STT → LLM → TTS) for better Hindi support

---

## 🎨 UI Upgrade Plan

### Current Stack
- React 18.3.1
- TypeScript
- Vite (build tool)
- TailwindCSS 3.4.3
- DaisyUI 4.12.2
- React Router DOM

### Upgrade Approach

#### 1. **Enhanced Homepage Design**
```tsx
// Modern gradient background
<div className="min-h-screen bg-gradient-to-br from-emerald-50 via-white to-blue-50">
  
  // Glassmorphism cards
  <div className="backdrop-blur-lg bg-white/70 rounded-2xl shadow-xl border border-white/20">
    
  // Animated voice visualizer
  <div className="relative">
    <div className="absolute inset-0 bg-gradient-to-r from-emerald-400 to-blue-500 blur-3xl opacity-30 animate-pulse" />
  </div>
</div>
```

#### 2. **Voice Mode Cards**
```tsx
const VOICE_MODES = [
  {
    value: "personaplex",
    label: "PersonaPlex",
    icon: "🎭",
    desc: "Full-duplex with Reasoner",
    color: "from-purple-500 to-pink-500"
  },
  {
    value: "lfm",
    label: "LFM 2.5",
    icon: "🌊",
    desc: "LiquidAI voice model",
    color: "from-blue-500 to-cyan-500"
  },
  {
    value: "cascade",
    label: "Cascade",
    icon: "⚡",
    desc: "STT → RAG → TTS",
    color: "from-emerald-500 to-teal-500"
  }
];
```

#### 3. **Voice Selection Grid**
```tsx
<div className="grid grid-cols-2 md:grid-cols-4 gap-3">
  {VOICES.map(voice => (
    <button className="group relative overflow-hidden rounded-xl p-4 
      bg-gradient-to-br from-white to-gray-50 
      hover:from-emerald-50 hover:to-blue-50
      border-2 border-gray-200 hover:border-emerald-400
      transition-all duration-300 transform hover:scale-105">
      <div className="text-2xl mb-2">{voice.icon}</div>
      <div className="text-sm font-medium">{voice.name}</div>
    </button>
  ))}
</div>
```

#### 4. **Real-time Audio Visualizer**
```tsx
// Waveform visualization during conversation
<canvas className="w-full h-32 rounded-lg bg-gradient-to-r from-emerald-900/10 to-blue-900/10" />

// Pulsing microphone indicator
<div className="relative">
  <div className="absolute inset-0 bg-red-500 rounded-full animate-ping opacity-75" />
  <div className="relative bg-red-500 rounded-full p-4">
    <MicrophoneIcon className="w-6 h-6 text-white" />
  </div>
</div>
```

#### 5. **Agent Cards with Knowledge Preview**
```tsx
<div className="space-y-3">
  {agents.map(agent => (
    <div className="group p-4 rounded-xl border-2 border-gray-200 
      hover:border-emerald-400 hover:shadow-lg transition-all cursor-pointer">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-900">{agent.name}</h3>
          <p className="text-xs text-gray-500">{agent.type}</p>
          <div className="mt-2 flex gap-2">
            <span className="px-2 py-1 text-xs bg-emerald-100 text-emerald-700 rounded-full">
              {agent.document_count} docs
            </span>
            <span className="px-2 py-1 text-xs bg-blue-100 text-blue-700 rounded-full">
              RAG enabled
            </span>
          </div>
        </div>
        <ChevronRightIcon className="w-5 h-5 text-gray-400 group-hover:text-emerald-500" />
      </div>
    </div>
  ))}
</div>
```

---

## 🚀 Implementation Steps

### Step 1: Update Dependencies
```bash
cd personaplex/client
npm install
npm install @heroicons/react  # For icons
```

### Step 2: Create Enhanced Components
```bash
# Create new component files
src/components/VoiceCard/VoiceCard.tsx
src/components/AgentCard/AgentCard.tsx
src/components/AudioVisualizer/AudioVisualizer.tsx
src/components/ModeSelector/ModeSelector.tsx
```

### Step 3: Update Tailwind Config
```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        omni: {
          green: '#76b900',
          dark: '#1a1a1a',
        }
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      }
    }
  }
}
```

### Step 4: Build & Deploy
```bash
npm run build
# Output: personaplex/client/dist/
```

---

## 🔧 Configuration for Hindi

### Environment Variables
```bash
# .env file
VITE_DEFAULT_LANGUAGE=hi  # Hindi
VITE_ENABLE_HINDI_WARNING=true
VITE_HINDI_VOICE_RECOMMENDATION=NATF2.pt
```

### Agent Configuration
```json
{
  "agent_id": "hindi-assistant",
  "system_prompt": "आप एक सहायक हैं। हिंदी में स्पष्ट और सरल भाषा में जवाब दें।",
  "language": "hi",
  "voice_prompt": "NATF2.pt"
}
```

---

## 📝 Testing Hindi Support

### Test Prompts
```typescript
const HINDI_TEST_PROMPTS = [
  "नमस्ते, आप कैसे हैं?",  // Hello, how are you?
  "मुझे हिंदी में मदद चाहिए।",  // I need help in Hindi
  "भारत की राजधानी क्या है?",  // What is the capital of India?
];
```

### Expected Behavior
1. UI detects Hindi script
2. Shows experimental warning
3. Recommends NATF*/NATM* voices
4. Processes voice with Hindi text

---

## 🎯 Key Features to Add

### 1. Language Selector
```tsx
<select className="...">
  <option value="en">English 🇬🇧</option>
  <option value="hi">हिंदी 🇮🇳</option>
  <option value="en-hi">English + हिंदी</option>
</select>
```

### 2. Voice Preview
```tsx
<button onClick={() => playVoiceSample(voice)}>
  🔊 Preview Voice
</button>
```

### 3. Knowledge Context Display
```tsx
<div className="mt-4 p-3 bg-blue-50 rounded-lg">
  <h4 className="text-sm font-medium text-blue-900">Retrieved Context:</h4>
  <p className="text-xs text-blue-700 mt-1">{context.slice(0, 200)}...</p>
</div>
```

### 4. Real-time Transcription
```tsx
<div className="space-y-2">
  <div className="flex gap-2">
    <span className="text-blue-600">You:</span>
    <span>{userTranscript}</span>
  </div>
  <div className="flex gap-2">
    <span className="text-emerald-600">AI:</span>
    <span>{aiTranscript}</span>
  </div>
</div>
```

---

## 🔍 Troubleshooting

### Hindi Not Working?
1. Check if text prompt contains Devanagari characters
2. Verify voice model supports multilingual (NATF*/NATM*)
3. Try Cascade mode instead of PersonaPlex
4. Check server logs for encoding errors

### Voice Quality Issues?
1. Use NATF*/NATM* voices (more stable)
2. Reduce audio temperature (0.6-0.8)
3. Check network latency
4. Verify microphone quality

### RAG Context Not Loading?
1. Verify agent has documents uploaded
2. Check `context_query` parameter
3. Ensure pgvector is running
4. Check OmniCortex API logs

---

## 📚 Resources

- **PersonaPlex Paper**: https://arxiv.org/abs/2602.06053
- **Moshi Architecture**: https://arxiv.org/abs/2410.00037
- **TailwindCSS Docs**: https://tailwindcss.com
- **React Docs**: https://react.dev

---

## 🎉 Summary

PersonaPlex is a powerful voice AI system with:
- ✅ Real-time full-duplex conversations
- ✅ RAG-powered knowledge retrieval
- ✅ Multiple voice options (18 voices)
- ✅ React + TailwindCSS UI
- ⚠️ Experimental Hindi support
- 🚀 Ready for UI upgrades

**Next Steps**: Implement the enhanced UI components with better Tailwind styling and improved Hindi detection/warnings.
