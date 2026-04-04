# PersonaPlex UI Upgrade Guide

## 🎨 Modern UI Enhancement with TailwindCSS

This guide provides step-by-step instructions to upgrade the PersonaPlex React UI with modern design patterns.

---

## 📦 New Components Created

### 1. EnhancedVoiceCard
**Location**: `personaplex/client/src/components/EnhancedVoiceCard/EnhancedVoiceCard.tsx`

**Features**:
- Gender-based icons (👩/👨)
- Category-based gradient colors
- Hover animations with scale effect
- Selected state with pulse animation
- Natural vs Variety visual distinction

**Usage**:
```tsx
<EnhancedVoiceCard
  voice="NATF0.pt"
  isSelected={selectedVoice === "NATF0.pt"}
  onSelect={setSelectedVoice}
  category="natural"
  gender="female"
/>
```

### 2. VoiceModeSelector
**Location**: `personaplex/client/src/components/VoiceModeSelector/VoiceModeSelector.tsx`

**Features**:
- 3 voice modes: PersonaPlex, LFM, Cascade
- Icon-based visual representation
- Gradient backgrounds for selected state
- Descriptive tooltips

**Usage**:
```tsx
<VoiceModeSelector
  selectedMode={voiceMode}
  onSelectMode={setVoiceMode}
/>
```

### 3. AgentCard
**Location**: `personaplex/client/src/components/AgentCard/AgentCard.tsx`

**Features**:
- Type-based emoji icons
- Document/message count badges
- Gradient background when selected
- Smooth hover animations
- Responsive design

**Usage**:
```tsx
<AgentCard
  agent={agent}
  isSelected={selectedAgentId === agent.id}
  onSelect={setSelectedAgentId}
/>
```

---

## 🚀 Implementation Steps

### Step 1: Install Dependencies (if needed)
```bash
cd personaplex/client
npm install
```

### Step 2: Update Queue.tsx to Use New Components

Replace the voice selection section:

```tsx
import { EnhancedVoiceCard } from "../../components/EnhancedVoiceCard/EnhancedVoiceCard";
import { VoiceModeSelector } from "../../components/VoiceModeSelector/VoiceModeSelector";
import { AgentCard } from "../../components/AgentCard/AgentCard";

// In the Homepage component:

// Voice Mode Selection
<VoiceModeSelector
  selectedMode={voiceMode}
  onSelectMode={setVoiceMode}
/>

// Voice Selection Grid
<div className="w-full">
  <label className="block text-left text-base font-medium text-gray-700 mb-3">
    Select Voice:
  </label>
  
  {/* Natural Voices */}
  <div className="mb-4">
    <h3 className="text-sm font-medium text-gray-600 mb-2">Natural (Recommended)</h3>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {["NATF0.pt", "NATF1.pt", "NATF2.pt", "NATF3.pt"].map(voice => (
        <EnhancedVoiceCard
          key={voice}
          voice={voice}
          isSelected={voicePrompt === voice}
          onSelect={setVoicePrompt}
          category="natural"
          gender="female"
        />
      ))}
      {["NATM0.pt", "NATM1.pt", "NATM2.pt", "NATM3.pt"].map(voice => (
        <EnhancedVoiceCard
          key={voice}
          voice={voice}
          isSelected={voicePrompt === voice}
          onSelect={setVoicePrompt}
          category="natural"
          gender="male"
        />
      ))}
    </div>
  </div>
  
  {/* Variety Voices */}
  <div>
    <h3 className="text-sm font-medium text-gray-600 mb-2">Variety</h3>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {["VARF0.pt", "VARF1.pt", "VARF2.pt", "VARF3.pt", "VARF4.pt"].map(voice => (
        <EnhancedVoiceCard
          key={voice}
          voice={voice}
          isSelected={voicePrompt === voice}
          onSelect={setVoicePrompt}
          category="variety"
          gender="female"
        />
      ))}
      {["VARM0.pt", "VARM1.pt", "VARM2.pt", "VARM3.pt", "VARM4.pt"].map(voice => (
        <EnhancedVoiceCard
          key={voice}
          voice={voice}
          isSelected={voicePrompt === voice}
          onSelect={setVoicePrompt}
          category="variety"
          gender="male"
        />
      ))}
    </div>
  </div>
</div>

// Agent Selection
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

### Step 3: Enhanced Homepage Layout

Update the main container:

```tsx
<div className="min-h-screen w-screen bg-gradient-to-br from-emerald-50 via-white to-blue-50">
  <div className="max-w-6xl mx-auto p-6">
    {/* Header */}
    <div className="text-center mb-8">
      <div className="inline-block">
        <h1 className="text-5xl font-bold bg-gradient-to-r from-emerald-600 to-teal-600 
          bg-clip-text text-transparent tracking-tight">
          OmniCortex
        </h1>
        <div className="h-1 bg-gradient-to-r from-emerald-500 to-teal-500 rounded-full mt-2" />
      </div>
      <p className="text-gray-600 mt-3">PersonaPlex Voice Gateway</p>
      <p className="text-sm text-gray-500 mt-1">
        Full-duplex conversational AI with multi-mode voice pipeline
      </p>
    </div>

    {/* Main Content */}
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Left Column - Agent & Settings */}
      <div className="lg:col-span-1 space-y-6">
        {/* Agent Selection Card */}
        <div className="backdrop-blur-lg bg-white/70 rounded-2xl shadow-xl 
          border border-white/20 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            🤖 Select Agent
          </h2>
          {/* Agent cards here */}
        </div>
        
        {/* Settings Card */}
        <div className="backdrop-blur-lg bg-white/70 rounded-2xl shadow-xl 
          border border-white/20 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            ⚙️ Settings
          </h2>
          {/* Settings inputs here */}
        </div>
      </div>

      {/* Right Column - Voice & Prompt */}
      <div className="lg:col-span-2 space-y-6">
        {/* Voice Mode Card */}
        <div className="backdrop-blur-lg bg-white/70 rounded-2xl shadow-xl 
          border border-white/20 p-6">
          <VoiceModeSelector
            selectedMode={voiceMode}
            onSelectMode={setVoiceMode}
          />
        </div>

        {/* Voice Selection Card */}
        <div className="backdrop-blur-lg bg-white/70 rounded-2xl shadow-xl 
          border border-white/20 p-6">
          {/* Voice cards here */}
        </div>

        {/* Text Prompt Card */}
        <div className="backdrop-blur-lg bg-white/70 rounded-2xl shadow-xl 
          border border-white/20 p-6">
          {/* Prompt textarea here */}
        </div>
      </div>
    </div>

    {/* Connect Button */}
    <div className="mt-8 text-center">
      <button
        onClick={startConnection}
        className="group relative px-8 py-4 bg-gradient-to-r from-emerald-500 to-teal-500 
          text-white font-semibold rounded-xl shadow-lg hover:shadow-xl
          transform hover:scale-105 transition-all duration-300"
      >
        <span className="relative z-10 flex items-center gap-2">
          🎤 Start Conversation
        </span>
        <div className="absolute inset-0 bg-gradient-to-r from-emerald-600 to-teal-600 
          rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
      </button>
    </div>
  </div>
</div>
```

---

## 🇮🇳 Hindi Support Enhancement

### Add Language Selector Component

```tsx
// src/components/LanguageSelector/LanguageSelector.tsx
import { FC } from "react";

interface LanguageSelectorProps {
  selectedLanguage: string;
  onSelectLanguage: (lang: string) => void;
}

export const LanguageSelector: FC<LanguageSelectorProps> = ({
  selectedLanguage,
  onSelectLanguage,
}) => {
  const languages = [
    { code: "en", label: "English", flag: "🇬🇧", recommended: true },
    { code: "hi", label: "हिंदी", flag: "🇮🇳", experimental: true },
    { code: "en-hi", label: "English + हिंदी", flag: "🌐", experimental: true },
  ];

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-gray-700">
        Language
      </label>
      <div className="grid grid-cols-1 gap-2">
        {languages.map((lang) => (
          <button
            key={lang.code}
            onClick={() => onSelectLanguage(lang.code)}
            className={`flex items-center justify-between p-3 rounded-lg border-2 
              transition-all duration-200
              ${selectedLanguage === lang.code
                ? "border-emerald-500 bg-emerald-50"
                : "border-gray-200 hover:border-emerald-300"
              }`}
          >
            <div className="flex items-center gap-2">
              <span className="text-2xl">{lang.flag}</span>
              <span className="font-medium text-gray-900">{lang.label}</span>
            </div>
            <div className="flex gap-2">
              {lang.recommended && (
                <span className="px-2 py-1 text-xs bg-emerald-100 text-emerald-700 rounded-full">
                  Recommended
                </span>
              )}
              {lang.experimental && (
                <span className="px-2 py-1 text-xs bg-amber-100 text-amber-700 rounded-full">
                  Experimental
                </span>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
};
```

### Hindi Warning Component

```tsx
// src/components/HindiWarning/HindiWarning.tsx
import { FC } from "react";

export const HindiWarning: FC = () => {
  return (
    <div className="mt-4 p-4 bg-amber-50 border-l-4 border-amber-500 rounded-r-lg">
      <div className="flex items-start gap-3">
        <span className="text-2xl">⚠️</span>
        <div>
          <h4 className="font-semibold text-amber-900 mb-1">
            Hindi Support is Experimental
          </h4>
          <p className="text-sm text-amber-800">
            PersonaPlex is officially optimized for English. Hindi support is experimental 
            and may have lower voice quality. For better Hindi results, consider using 
            Cascade mode (STT → LLM → TTS).
          </p>
          <div className="mt-2">
            <p className="text-xs text-amber-700 font-medium">
              Recommended voices for Hindi: NATF2, NATM1
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
```

---

## 🎨 Additional UI Enhancements

### 1. Loading States

```tsx
// Loading skeleton for agents
<div className="space-y-3">
  {[1, 2, 3].map((i) => (
    <div key={i} className="animate-pulse">
      <div className="h-20 bg-gray-200 rounded-xl" />
    </div>
  ))}
</div>
```

### 2. Error States

```tsx
{agentsError && (
  <div className="p-4 bg-red-50 border-l-4 border-red-500 rounded-r-lg">
    <div className="flex items-start gap-3">
      <span className="text-xl">❌</span>
      <div>
        <h4 className="font-semibold text-red-900">Error Loading Agents</h4>
        <p className="text-sm text-red-800 mt-1">{agentsError}</p>
      </div>
    </div>
  </div>
)}
```

### 3. Success Notifications

```tsx
{connectStatus && (
  <div className="fixed bottom-4 right-4 max-w-sm">
    <div className="backdrop-blur-lg bg-white/90 rounded-xl shadow-2xl 
      border border-white/20 p-4 animate-slide-up">
      <div className="flex items-center gap-3">
        <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
        <p className="text-sm text-gray-800">{connectStatus}</p>
      </div>
    </div>
  </div>
)}
```

### 4. Add Custom Animations to Tailwind

```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      keyframes: {
        'slide-up': {
          '0%': { transform: 'translateY(100%)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
      animation: {
        'slide-up': 'slide-up 0.3s ease-out',
      },
    },
  },
};
```

---

## 🧪 Testing the Upgrades

### 1. Build the UI
```bash
cd personaplex/client
npm run build
```

### 2. Start the Server
```bash
cd personaplex
python -m moshi.server --ssl /tmp/ssl
```

### 3. Test Features
- ✅ Voice card selection with animations
- ✅ Agent card selection with badges
- ✅ Voice mode switching
- ✅ Hindi detection and warning
- ✅ Responsive design on mobile
- ✅ Loading and error states

---

## 📱 Mobile Responsiveness

All components are mobile-responsive:

```tsx
// Responsive grid
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">

// Responsive text
<h1 className="text-3xl md:text-4xl lg:text-5xl">

// Responsive padding
<div className="p-4 md:p-6 lg:p-8">
```

---

## 🎯 Next Steps

1. ✅ Implement new components
2. ✅ Update Queue.tsx with enhanced layout
3. ✅ Add Hindi language selector
4. ✅ Test on different screen sizes
5. 🔄 Add voice preview functionality
6. 🔄 Implement real-time audio visualizer
7. 🔄 Add conversation history display
8. 🔄 Create settings persistence

---

## 📚 Resources

- **TailwindCSS**: https://tailwindcss.com/docs
- **DaisyUI**: https://daisyui.com
- **React**: https://react.dev
- **Vite**: https://vitejs.dev

---

## 🎉 Result

After implementing these upgrades, you'll have:
- ✨ Modern, glassmorphic UI design
- 🎨 Smooth animations and transitions
- 📱 Fully responsive layout
- 🇮🇳 Hindi support with warnings
- 🎤 Enhanced voice selection
- 🤖 Beautiful agent cards
- ⚡ Better user experience

The UI will be production-ready with a professional, modern look!
