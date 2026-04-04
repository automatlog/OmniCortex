# PersonaPlex UI Upgrade - Quick Start Guide

## 🚀 5-Minute Setup

### Prerequisites
- Node.js 18+ installed
- Python 3.9+ installed
- PersonaPlex repository cloned
- OmniCortex API running (port 8000)

---

## Step 1: Navigate to Client Directory
```bash
cd personaplex/client
```

## Step 2: Install Dependencies
```bash
npm install
```

## Step 3: Copy New Components

The following components have been created for you:

```
src/components/
├── EnhancedVoiceCard/
│   └── EnhancedVoiceCard.tsx
├── VoiceModeSelector/
│   └── VoiceModeSelector.tsx
├── AgentCard/
│   └── AgentCard.tsx
├── LanguageSelector/
│   └── LanguageSelector.tsx
└── HindiWarning/
    └── HindiWarning.tsx
```

## Step 4: Test Build
```bash
npm run build
```

If successful, you'll see:
```
✓ built in XXXms
```

## Step 5: Start Development Server
```bash
npm run dev
```

Access at: `http://localhost:5173`

---

## 🎨 Quick UI Integration

### Minimal Integration (5 minutes)

Add to your `Queue.tsx`:

```typescript
import { EnhancedVoiceCard } from "../../components/EnhancedVoiceCard/EnhancedVoiceCard";
import { AgentCard } from "../../components/AgentCard/AgentCard";

// In your render:
<div className="grid grid-cols-2 md:grid-cols-4 gap-3">
  {VOICE_OPTIONS.map(voice => (
    <EnhancedVoiceCard
      key={voice}
      voice={voice}
      isSelected={voicePrompt === voice}
      onSelect={setVoicePrompt}
      category={voice.startsWith("NAT") ? "natural" : "variety"}
      gender={voice.includes("F") ? "female" : "male"}
    />
  ))}
</div>

<div className="space-y-3">
  {agents.map(agent => (
    <AgentCard
      key={agent.id}
      agent={agent}
      isSelected={selectedAgentId === agent.id}
      onSelect={setSelectedAgentId}
    />
  ))}
</div>
```

---

## 🇮🇳 Quick Hindi Setup (2 minutes)

### Add Language State
```typescript
const [selectedLanguage, setSelectedLanguage] = useLocalStorage<string>(
  "omnicortex_language",
  "en"
);
```

### Add Hindi Detection
```typescript
const isHindi = /[\u0900-\u097F]/.test(textPrompt) || 
                /\bhindi\b/i.test(textPrompt) ||
                selectedLanguage === "hi";
```

### Show Warning
```typescript
import { HindiWarning } from "../../components/HindiWarning/HindiWarning";

{isHindi && <HindiWarning selectedVoice={voicePrompt} />}
```

---

## 🎤 Voice Configuration

### Available Voices

```typescript
// Natural (Recommended for Hindi)
const NATURAL_VOICES = {
  female: ["NATF0.pt", "NATF1.pt", "NATF2.pt", "NATF3.pt"],
  male: ["NATM0.pt", "NATM1.pt", "NATM2.pt", "NATM3.pt"]
};

// Variety
const VARIETY_VOICES = {
  female: ["VARF0.pt", "VARF1.pt", "VARF2.pt", "VARF3.pt", "VARF4.pt"],
  male: ["VARM0.pt", "VARM1.pt", "VARM2.pt", "VARM3.pt", "VARM4.pt"]
};
```

### Voice Modes

```typescript
type VoiceMode = "personaplex" | "lfm" | "cascade";

// For Hindi, use:
voiceMode = "cascade"  // Better multilingual support
```

---

## 🧪 Quick Test

### 1. Test English Conversation
```typescript
const englishPrompt = "You are a helpful assistant. Answer questions clearly.";
const voice = "NATF0.pt";
const mode = "personaplex";
```

### 2. Test Hindi Conversation
```typescript
const hindiPrompt = "आप एक सहायक हैं। हिंदी में जवाब दें।";
const voice = "NATF2.pt";
const mode = "cascade";  // Better for Hindi
```

### 3. Test Bilingual
```typescript
const bilingualPrompt = `
You are a helpful assistant. Respond in the user's language.
आप एक सहायक हैं। उपयोगकर्ता की भाषा में जवाब दें।
`;
const voice = "NATF2.pt";
const mode = "cascade";
```

---

## 🔧 Environment Setup

### Client Environment
Create `.env` in `personaplex/client/`:

```bash
VITE_ENV=development
VITE_DEFAULT_LANGUAGE=en
VITE_ENABLE_HINDI_WARNING=true
```

### Server Environment
```bash
# OmniCortex integration
export OMNICORTEX_BASE_URL=http://localhost:8000
export OMNICORTEX_API_KEY=your_api_key_here

# Voice settings
export PERSONAPLEX_EAGER_VOICE_CONTEXT=true
export OMNICORTEX_CONTEXT_TOP_K=3
```

---

## 🚦 Start Everything

### Terminal 1: PostgreSQL
```bash
# If using Docker
docker start postgres-container

# Or native
pg_ctl start
```

### Terminal 2: OmniCortex API
```bash
cd /path/to/omnicortex
source venv/bin/activate
python api.py
```

### Terminal 3: PersonaPlex Server
```bash
cd /path/to/personaplex
python -m moshi.server --ssl /tmp/ssl
```

### Terminal 4: React Dev Server (Optional)
```bash
cd personaplex/client
npm run dev
```

---

## ✅ Verification Checklist

### UI Loads
- [ ] Navigate to `http://localhost:8998`
- [ ] See OmniCortex header
- [ ] See agent selection area
- [ ] See voice cards
- [ ] See connect button

### Agent Loading
- [ ] Click "Refresh Agents"
- [ ] See list of agents
- [ ] Click an agent
- [ ] Agent card highlights
- [ ] Click "Load Selected Agent Prompt"
- [ ] Prompt appears in textarea

### Voice Selection
- [ ] Click different voice cards
- [ ] Selected voice highlights
- [ ] Natural/Variety sections visible
- [ ] Icons display correctly

### Hindi Support
- [ ] Type Hindi text in prompt
- [ ] Hindi warning appears
- [ ] Voice recommendations show
- [ ] Tips display

### Connection
- [ ] Click "Connect"
- [ ] Microphone permission requested
- [ ] WebSocket connects
- [ ] Status indicator turns green
- [ ] Can speak and hear response

---

## 🐛 Common Issues

### Issue: Components Not Found
```bash
# Solution: Ensure files are in correct locations
ls -la src/components/EnhancedVoiceCard/
ls -la src/components/AgentCard/
ls -la src/components/VoiceModeSelector/
ls -la src/components/LanguageSelector/
ls -la src/components/HindiWarning/
```

### Issue: Build Fails
```bash
# Solution: Check TypeScript errors
npm run build 2>&1 | grep error

# Fix import paths
# Fix type definitions
```

### Issue: Styles Not Applying
```bash
# Solution: Verify TailwindCSS config
cat tailwind.config.js

# Ensure content paths include components
content: [
  "./index.html",
  "./src/**/*.{js,ts,jsx,tsx}",
]
```

### Issue: WebSocket Connection Fails
```bash
# Solution: Check server is running
curl http://localhost:8998/health

# Check WebSocket URL
# Verify CORS settings
```

### Issue: No Agents Loading
```bash
# Solution: Check OmniCortex API
curl http://localhost:8000/agents

# Check bearer token
# Check database connection
```

### Issue: Hindi Not Detected
```typescript
// Solution: Check regex pattern
const isHindi = /[\u0900-\u097F]/.test(text);

// Test with:
console.log(isHindi("नमस्ते")); // Should be true
console.log(isHindi("Hello"));  // Should be false
```

---

## 📚 Next Steps

### After Basic Setup Works:

1. **Customize Styling**
   - Update colors in `tailwind.config.js`
   - Modify component styles
   - Add your branding

2. **Add Features**
   - Voice preview
   - Audio visualizer
   - Conversation history
   - Settings panel

3. **Optimize Performance**
   - Code splitting
   - Lazy loading
   - Image optimization
   - Bundle size reduction

4. **Deploy**
   - Build for production: `npm run build`
   - Copy `dist/` to server
   - Configure nginx/Caddy
   - Set up SSL

---

## 🎯 Success Indicators

You'll know it's working when:

✅ UI loads without errors
✅ Agents display in cards
✅ Voice selection works
✅ Hindi warning shows for Hindi text
✅ WebSocket connects successfully
✅ You can have a voice conversation
✅ Audio quality is good
✅ Latency is acceptable (<500ms)

---

## 📞 Getting Help

### Check Logs

```bash
# Browser console
F12 → Console tab

# Server logs
tail -f /path/to/personaplex/logs/server.log

# OmniCortex logs
tail -f /path/to/omnicortex/storage/logs/query_trace.log
```

### Debug Mode

```typescript
// Add to Queue.tsx
useEffect(() => {
  console.log("Selected Agent:", selectedAgentId);
  console.log("Voice Prompt:", voicePrompt);
  console.log("Voice Mode:", voiceMode);
  console.log("Language:", selectedLanguage);
}, [selectedAgentId, voicePrompt, voiceMode, selectedLanguage]);
```

---

## 🎉 You're Ready!

If you've completed all steps:
1. ✅ Components are created
2. ✅ Build succeeds
3. ✅ UI loads
4. ✅ Agents display
5. ✅ Voice works
6. ✅ Hindi detection works

**Congratulations!** Your PersonaPlex UI is upgraded and ready to use.

---

## 📖 Full Documentation

For detailed information, see:
- `PERSONAPLEX_WORKFLOW.md` - Complete system workflow
- `PERSONAPLEX_UI_UPGRADE_GUIDE.md` - Detailed UI upgrade steps
- `PERSONAPLEX_SUMMARY.md` - Quick reference
- `ARCHITECTURE_DIAGRAM.md` - System architecture
- `IMPLEMENTATION_CHECKLIST.md` - Full checklist

---

**Estimated Setup Time**: 10-15 minutes
**Difficulty**: Beginner to Intermediate
**Support**: Check documentation files for detailed help

Happy coding! 🚀
