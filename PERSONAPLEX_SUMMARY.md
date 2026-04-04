# PersonaPlex Voice AI - Complete Summary

## 📋 Quick Overview

**PersonaPlex** is a full-duplex voice AI system built with:
- **Frontend**: React 18 + TypeScript + Vite + TailwindCSS
- **Backend**: Python Moshi Server (PersonaPlex model)
- **Integration**: OmniCortex API for RAG and agent management
- **Port**: 8998 (both UI and WebSocket server)

---

## 🔄 How It Works - Complete Flow

### 1. **User Opens UI** → `http://localhost:8998`

### 2. **Agent Selection**
```
User clicks "Refresh Agents"
  ↓
UI → GET /api/agents (Moshi Server)
  ↓
Moshi Server → GET /agents (OmniCortex API)
  ↓
Returns: List of agents with IDs, names, types
  ↓
User selects an agent
```

### 3. **Knowledge Loading (RAG)**
```
User clicks "Load Selected Agent Prompt"
  ↓
UI → GET /api/agent-prompt?agent_id=X&context_query=Y
  ↓
Moshi Server fetches:
  1. System prompt from /agents/{id}/system-prompt
  2. Voice context from /agents/{id}/voice-context (RAG retrieval)
  ↓
Server combines:
  - Base system prompt
  - Retrieved documents (top-k=3 from pgvector)
  - Initial greeting
  ↓
Returns combined prompt to UI
```

### 4. **Voice Connection**
```
User clicks "Connect"
  ↓
WebSocket opens: ws://localhost:8998/api/chat
  ↓
Parameters sent:
  - agent_id
  - voice_prompt (e.g., NATF0.pt)
  - context_query
  - voice_mode (personaplex/lfm/cascade)
  ↓
Server loads voice embeddings and system prompt
```

### 5. **Real-Time Conversation**
```
User speaks into microphone
  ↓
Browser: Audio → Opus encoding
  ↓
WebSocket: Binary frame (0x01 + opus data)
  ↓
Moshi Server:
  1. Opus decode → PCM audio
  2. Mimi encoder → Audio tokens
  3. LLM generation (with RAG context)
  4. Mimi decoder → Audio tokens → PCM
  5. Opus encode
  ↓
WebSocket: Binary frame (0x01 + opus data)
  ↓
Browser: Opus decode → Speaker output
  ↓
Also: Text tokens sent as 0x02 frames for transcription
```

---

## 🎤 Available Voices (18 Total)

### Natural Voices (Recommended)
| Voice | Gender | Best For |
|-------|--------|----------|
| NATF0 | Female | General conversations |
| NATF1 | Female | Professional tone |
| NATF2 | Female | **Hindi (experimental)** |
| NATF3 | Female | Warm, friendly |
| NATM0 | Male | General conversations |
| NATM1 | Male | **Hindi (experimental)** |
| NATM2 | Male | Professional tone |
| NATM3 | Male | Deep, authoritative |

### Variety Voices
| Voice | Gender | Best For |
|-------|--------|----------|
| VARF0-4 | Female | Varied expressions |
| VARM0-4 | Male | Varied expressions |

**Recommendation**: Use NATF*/NATM* for stable, natural conversations.

---

## 🇮🇳 Hindi Support - Complete Guide

### ✅ What Works
- Hindi text prompts (Devanagari script)
- Hindi speech recognition (experimental)
- Hindi text-to-speech (experimental)
- English-Hindi code-switching

### ⚠️ Limitations
- **Not officially supported** by PersonaPlex
- Voice quality may be lower than English
- Pronunciation may not be native-level
- Better results with Cascade mode

### 🔧 How to Use Hindi

#### Option 1: Direct Hindi Prompt
```typescript
const hindiPrompt = `
आप एक सहायक हैं। 
हिंदी में स्पष्ट और सरल भाषा में जवाब दें।
उपयोगकर्ता के सवालों का विनम्रता से उत्तर दें।
`;
```

#### Option 2: Bilingual Prompt
```typescript
const bilingualPrompt = `
You are a helpful assistant. / आप एक सहायक हैं।
Respond in Hindi when the user speaks Hindi.
जब उपयोगकर्ता हिंदी में बोले तो हिंदी में जवाब दें।
`;
```

#### Option 3: Use Cascade Mode
```typescript
// Better for Hindi
voiceMode = "cascade"  // STT → LLM → TTS
// Instead of
voiceMode = "personaplex"  // Full-duplex (English-optimized)
```

### 🎯 Best Practices for Hindi
1. **Voice Selection**: Use NATF2 or NATM1
2. **Mode**: Prefer Cascade over PersonaPlex
3. **Speech**: Speak clearly, moderate pace
4. **Vocabulary**: Use common Hindi words
5. **Testing**: Start with short phrases

### 📝 Hindi Test Prompts
```typescript
const testPrompts = [
  "नमस्ते, आप कैसे हैं?",           // Hello, how are you?
  "मुझे मदद चाहिए।",                // I need help
  "भारत की राजधानी क्या है?",       // What is capital of India?
  "आज का मौसम कैसा है?",            // How is the weather today?
  "मुझे हिंदी में जानकारी दें।",    // Give me info in Hindi
];
```

---

## 🎨 UI Components Created

### 1. **EnhancedVoiceCard**
- Visual voice selection with icons
- Gender and category indicators
- Hover animations
- Selected state highlighting

### 2. **VoiceModeSelector**
- 3 modes: PersonaPlex, LFM, Cascade
- Icon-based representation
- Gradient backgrounds
- Descriptive tooltips

### 3. **AgentCard**
- Type-based emoji icons
- Document/message count badges
- Smooth animations
- Responsive design

### 4. **LanguageSelector**
- English, Hindi, Bilingual options
- Recommended/Experimental badges
- Flag icons
- Clear selection state

### 5. **HindiWarning**
- Experimental status warning
- Voice recommendations
- Usage tips
- Conditional display

---

## 🚀 How to Update the UI

### Step 1: Navigate to Client
```bash
cd personaplex/client
```

### Step 2: Install Dependencies (if needed)
```bash
npm install
```

### Step 3: Import New Components
```typescript
// In Queue.tsx
import { EnhancedVoiceCard } from "../../components/EnhancedVoiceCard/EnhancedVoiceCard";
import { VoiceModeSelector } from "../../components/VoiceModeSelector/VoiceModeSelector";
import { AgentCard } from "../../components/AgentCard/AgentCard";
import { LanguageSelector } from "../../components/LanguageSelector/LanguageSelector";
import { HindiWarning } from "../../components/HindiWarning/HindiWarning";
```

### Step 4: Add Language State
```typescript
const [selectedLanguage, setSelectedLanguage] = useLocalStorage<string>(
  "omnicortex_language", 
  "en"
);
```

### Step 5: Replace UI Sections
See `PERSONAPLEX_UI_UPGRADE_GUIDE.md` for detailed code examples.

### Step 6: Build
```bash
npm run build
```

### Step 7: Test
```bash
# Start server
cd ..
python -m moshi.server --ssl /tmp/ssl

# Open browser
# http://localhost:8998
```

---

## 📊 Voice Modes Explained

### 1. PersonaPlex (Default)
- **Type**: Full-duplex
- **How**: Direct audio-to-audio with LLM
- **Latency**: Lowest (~200ms)
- **Best For**: English conversations
- **Hindi**: Experimental

### 2. LFM 2.5
- **Type**: Interleaved voice model
- **How**: LiquidAI's voice model
- **Latency**: Low
- **Best For**: Alternative to PersonaPlex
- **Hindi**: Experimental

### 3. Cascade
- **Type**: Pipeline (STT → LLM → TTS)
- **How**: Speech-to-Text → RAG+LLM → Text-to-Speech
- **Latency**: Higher (~500ms)
- **Best For**: Multilingual, Hindi
- **Hindi**: Better support

---

## 🔍 Knowledge Retrieval (RAG) Details

### How RAG Works in Voice

1. **Agent has documents** uploaded to OmniCortex
2. **Documents are chunked** and embedded in pgvector
3. **When voice session starts**:
   ```python
   # Server fetches context
   context = await get_voice_context(
       agent_id=agent_id,
       query=context_query,  # User's query or text prompt
       top_k=3               # Top 3 relevant documents
   )
   ```
4. **Context is appended** to system prompt:
   ```python
   full_prompt = f"""
   {base_system_prompt}
   
   Use the following retrieved context when relevant:
   {context}
   """
   ```
5. **LLM uses context** during conversation

### Context Query Options

```typescript
// Option 1: Explicit context query
contextQuery = "Tell me about product pricing"

// Option 2: Use text prompt as seed
contextQuery = textPrompt  // If not filename-like

// Option 3: Empty (uses base prompt)
contextQuery = ""
```

### Environment Variables
```bash
# Eager context loading (fetch even without query)
export PERSONAPLEX_EAGER_VOICE_CONTEXT=true

# Top-K documents to retrieve
export OMNICORTEX_CONTEXT_TOP_K=3  # Default: 3
```

---

## 🛠️ Configuration Files

### Client Environment
```bash
# personaplex/client/.env
VITE_ENV=production
VITE_DEFAULT_LANGUAGE=en
VITE_ENABLE_HINDI_WARNING=true
```

### Server Environment
```bash
# OmniCortex integration
export OMNICORTEX_BASE_URL=http://localhost:8000
export OMNICORTEX_API_KEY=your_api_key
export OMNICORTEX_USER_ID=default_user

# Voice settings
export PERSONAPLEX_EAGER_VOICE_CONTEXT=true
export OMNICORTEX_CONTEXT_TOP_K=3

# Hindi support
export PERSONAPLEX_TEXT_PROMPT_CONTEXT_FALLBACK=true
```

---

## 📱 Responsive Design

All components are mobile-responsive:

```tsx
// Responsive grid
className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3"

// Responsive text
className="text-3xl md:text-4xl lg:text-5xl"

// Responsive padding
className="p-4 md:p-6 lg:p-8"

// Responsive layout
className="flex flex-col lg:flex-row gap-4"
```

---

## 🎯 Key Takeaways

### ✅ What PersonaPlex Does Well
- Real-time full-duplex voice conversations
- Low latency (~200ms)
- Natural voice quality
- RAG integration for knowledge
- Multiple voice options
- React-based modern UI

### ⚠️ Current Limitations
- English-optimized (Hindi is experimental)
- Requires good network connection
- Voice quality varies by model
- Limited to 18 pre-trained voices

### 🚀 Upgrade Benefits
- Modern, professional UI
- Better voice selection UX
- Hindi language support (experimental)
- Improved agent management
- Responsive mobile design
- Enhanced visual feedback

---

## 📚 Documentation Files Created

1. **PERSONAPLEX_WORKFLOW.md** - Complete system workflow
2. **PERSONAPLEX_UI_UPGRADE_GUIDE.md** - Step-by-step UI upgrade
3. **PERSONAPLEX_SUMMARY.md** - This file (quick reference)

---

## 🎉 Final Notes

PersonaPlex is a powerful voice AI system with React frontend. The UI can be significantly enhanced with the provided TailwindCSS components. Hindi support is experimental but functional with the right configuration.

**For best results**:
- Use NATF*/NATM* voices
- Enable Cascade mode for Hindi
- Test with short phrases first
- Provide clear system prompts
- Ensure good microphone quality

**Next steps**:
1. Implement the new UI components
2. Test voice modes
3. Configure Hindi support
4. Deploy and iterate based on user feedback

Good luck with your PersonaPlex upgrade! 🚀
