# PersonaPlex UI Upgrade - Implementation Checklist

## ✅ Phase 1: Setup & Preparation

- [ ] Navigate to personaplex/client directory
- [ ] Run `npm install` to ensure all dependencies are installed
- [ ] Verify TailwindCSS and DaisyUI are configured
- [ ] Check that the project builds: `npm run build`
- [ ] Review existing Queue.tsx structure

## ✅ Phase 2: Create New Components

### Voice Components
- [x] Create `EnhancedVoiceCard.tsx` component
  - Location: `src/components/EnhancedVoiceCard/`
  - Features: Gender icons, category colors, animations
  
- [x] Create `VoiceModeSelector.tsx` component
  - Location: `src/components/VoiceModeSelector/`
  - Features: 3 modes with icons and descriptions

### Agent Components
- [x] Create `AgentCard.tsx` component
  - Location: `src/components/AgentCard/`
  - Features: Type icons, badges, hover effects

### Language Components
- [x] Create `LanguageSelector.tsx` component
  - Location: `src/components/LanguageSelector/`
  - Features: English, Hindi, Bilingual options

- [x] Create `HindiWarning.tsx` component
  - Location: `src/components/HindiWarning/`
  - Features: Experimental warning, tips, recommendations

## ✅ Phase 3: Update Queue.tsx

### Import New Components
- [ ] Import EnhancedVoiceCard
- [ ] Import VoiceModeSelector
- [ ] Import AgentCard
- [ ] Import LanguageSelector
- [ ] Import HindiWarning

### Add State Management
- [ ] Add `selectedLanguage` state with localStorage
- [ ] Add Hindi detection logic
- [ ] Add voice recommendation logic

### Update UI Sections

#### Header Section
- [ ] Update header with gradient text
- [ ] Add subtitle and description
- [ ] Improve spacing and typography

#### Agent Section
- [ ] Replace agent dropdown with AgentCard components
- [ ] Add loading skeleton for agents
- [ ] Add error state display
- [ ] Add refresh button with loading state

#### Language Section
- [ ] Add LanguageSelector component
- [ ] Add conditional HindiWarning display
- [ ] Connect language selection to state

#### Voice Mode Section
- [ ] Replace dropdown with VoiceModeSelector
- [ ] Add mode descriptions
- [ ] Style selected state

#### Voice Selection Section
- [ ] Group voices by category (Natural/Variety)
- [ ] Replace options with EnhancedVoiceCard grid
- [ ] Add section headers
- [ ] Implement responsive grid layout

#### Text Prompt Section
- [ ] Update textarea styling
- [ ] Add character counter
- [ ] Add preset buttons with better styling
- [ ] Add Hindi detection indicator

#### Connect Button
- [ ] Update button with gradient background
- [ ] Add icon
- [ ] Add hover effects
- [ ] Add loading state

## ✅ Phase 4: Styling Enhancements

### Global Styles
- [ ] Update background with gradient
- [ ] Add glassmorphism effects to cards
- [ ] Implement consistent spacing
- [ ] Add smooth transitions

### Responsive Design
- [ ] Test on mobile (< 768px)
- [ ] Test on tablet (768px - 1024px)
- [ ] Test on desktop (> 1024px)
- [ ] Adjust grid layouts for each breakpoint

### Animations
- [ ] Add hover scale effects
- [ ] Add pulse animations for selected states
- [ ] Add slide-in animations for notifications
- [ ] Add loading spinners

## ✅ Phase 5: Hindi Support Integration

### Detection
- [ ] Implement Hindi script detection (Devanagari)
- [ ] Add keyword detection ("hindi", "हिंदी")
- [ ] Show warning when Hindi detected

### Recommendations
- [ ] Suggest NATF2/NATM1 voices for Hindi
- [ ] Recommend Cascade mode for Hindi
- [ ] Display tips for Hindi conversations

### Testing
- [ ] Test with Hindi text prompts
- [ ] Test with bilingual prompts
- [ ] Test voice quality with different voices
- [ ] Test Cascade mode vs PersonaPlex mode

## ✅ Phase 6: Testing

### Functionality Testing
- [ ] Agent selection works
- [ ] Agent prompt loading works
- [ ] Voice selection updates state
- [ ] Voice mode selection works
- [ ] Language selection works
- [ ] Context query input works
- [ ] Connect button initiates WebSocket
- [ ] Hindi warning displays correctly

### UI/UX Testing
- [ ] All animations are smooth
- [ ] Hover effects work on all interactive elements
- [ ] Selected states are clearly visible
- [ ] Loading states display properly
- [ ] Error states display properly
- [ ] Mobile layout is usable
- [ ] Touch targets are adequate on mobile

### Browser Testing
- [ ] Chrome/Edge (Chromium)
- [ ] Firefox
- [ ] Safari (if available)
- [ ] Mobile browsers

## ✅ Phase 7: Build & Deploy

### Build Process
- [ ] Run `npm run build`
- [ ] Check for TypeScript errors
- [ ] Check for build warnings
- [ ] Verify output in `dist/` folder

### Server Testing
- [ ] Start Moshi server: `python -m moshi.server --ssl /tmp/ssl`
- [ ] Access UI at `http://localhost:8998`
- [ ] Test WebSocket connection
- [ ] Test voice conversation
- [ ] Test agent switching
- [ ] Test Hindi prompts

### Performance
- [ ] Check page load time
- [ ] Check WebSocket latency
- [ ] Check audio quality
- [ ] Check memory usage during long conversations

## ✅ Phase 8: Documentation

- [x] Create PERSONAPLEX_WORKFLOW.md
- [x] Create PERSONAPLEX_UI_UPGRADE_GUIDE.md
- [x] Create PERSONAPLEX_SUMMARY.md
- [x] Create IMPLEMENTATION_CHECKLIST.md
- [ ] Update README.md with new features
- [ ] Document environment variables
- [ ] Create user guide for Hindi support

## ✅ Phase 9: Optional Enhancements

### Advanced Features
- [ ] Add voice preview functionality
- [ ] Add real-time audio visualizer
- [ ] Add conversation history display
- [ ] Add settings persistence
- [ ] Add keyboard shortcuts
- [ ] Add dark mode toggle

### Analytics
- [ ] Track voice mode usage
- [ ] Track language selection
- [ ] Track agent usage
- [ ] Track conversation duration

### Accessibility
- [ ] Add ARIA labels
- [ ] Test with screen readers
- [ ] Ensure keyboard navigation
- [ ] Add focus indicators
- [ ] Test color contrast ratios

## 📝 Notes

### Common Issues & Solutions

**Issue**: Components not rendering
- **Solution**: Check import paths, ensure files are in correct locations

**Issue**: Styles not applying
- **Solution**: Verify TailwindCSS is configured, check className syntax

**Issue**: Hindi not detected
- **Solution**: Check regex pattern, ensure Devanagari range is correct

**Issue**: WebSocket connection fails
- **Solution**: Verify server is running, check CORS settings, check URL

**Issue**: Voice quality poor
- **Solution**: Try different voice, check network, use Cascade mode

### Environment Variables to Set

```bash
# Client (.env)
VITE_ENV=production
VITE_DEFAULT_LANGUAGE=en
VITE_ENABLE_HINDI_WARNING=true

# Server
export OMNICORTEX_BASE_URL=http://localhost:8000
export OMNICORTEX_API_KEY=your_key
export PERSONAPLEX_EAGER_VOICE_CONTEXT=true
export OMNICORTEX_CONTEXT_TOP_K=3
```

### Quick Commands

```bash
# Development
cd personaplex/client
npm run dev

# Build
npm run build

# Lint
npm run lint

# Format
npm run prettier

# Start server
cd ..
python -m moshi.server --ssl /tmp/ssl
```

## 🎯 Success Criteria

- ✅ All new components render correctly
- ✅ UI is responsive on all screen sizes
- ✅ Hindi detection and warnings work
- ✅ Voice selection is intuitive
- ✅ Agent cards display properly
- ✅ WebSocket connection succeeds
- ✅ Voice conversations work smoothly
- ✅ No console errors
- ✅ Build completes without errors
- ✅ Performance is acceptable

## 🎉 Completion

Once all items are checked:
1. Take screenshots of the new UI
2. Test with real users
3. Gather feedback
4. Iterate on improvements
5. Deploy to production

---

**Estimated Time**: 4-6 hours for full implementation
**Difficulty**: Intermediate
**Prerequisites**: React, TypeScript, TailwindCSS knowledge

Good luck! 🚀
