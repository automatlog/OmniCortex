# OmniCortex Admin Panel

Modern Next.js admin interface for OmniCortex RAG chatbot system.

## Features

- 🤖 Multi-agent chat interface
- 📄 Document management and upload
- 📊 Real-time analytics and metrics
- 🎨 Modern dark UI with Tailwind CSS
- ⚡ Optimized API client with retry logic
- 🔄 Automatic error recovery

## Quick Start

### Prerequisites

- Node.js 18+ installed
- OmniCortex API running on port 8000

### Installation

```bash
# Install dependencies
npm install

# Create environment file
cp .env.example .env.local

# Start development server
npm run dev
```

### Environment Variables

Create `.env.local` file:

```ini
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Development

```bash
# Start dev server (with hot reload)
npm run dev

# Build for production
npm run build

# Start production server
npm start

# Lint code
npm run lint
```

## API Integration

The admin panel connects to the FastAPI backend with:

- **Automatic retry**: 3 attempts with exponential backoff
- **Long timeout**: 90 seconds for chat requests
- **Error handling**: User-friendly error messages
- **Health checks**: Monitors API availability

### API Client Features

```typescript
// Automatic retry with backoff
await sendMessage(question, agentId);
// Retries: 2s, 4s, 8s delays

// Long timeout for LLM responses
// Total: 90s + retries = ~120s max
```

## Troubleshooting

### "Cannot connect to server"

1. Check if API is running:
   ```bash
   curl http://localhost:8000/
   ```

2. Verify `.env.local`:
   ```ini
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

3. Restart dev server:
   ```bash
   npm run dev
   ```

### Slow responses

- Normal: 2-4 seconds
- First query: 5-10 seconds (model loading)
- If >30 seconds: Check API logs

### Build errors

```bash
# Clear cache and reinstall
rm -rf .next node_modules
npm install
npm run dev
```

## Project Structure

```
admin/
├── src/
│   ├── app/              # Next.js app router pages
│   │   ├── agents/       # Agent management
│   │   ├── analytics/    # Analytics dashboard
│   │   └── settings/     # Settings page
│   ├── components/       # React components
│   │   ├── ui/          # shadcn/ui components
│   │   ├── AgentCard.tsx
│   │   ├── ChatInterface.tsx
│   │   └── Sidebar.tsx
│   └── lib/             # Utilities
│       ├── api.ts       # API client (with retry logic)
│       └── utils.ts     # Helper functions
├── public/              # Static assets
├── .env.local          # Environment variables (create this)
└── package.json        # Dependencies
```

## Configuration

### API Timeouts

Configured in `src/lib/api.ts`:

```typescript
// Chat requests: 90 seconds
// Document uploads: 120 seconds
// Other requests: 10 seconds
```

### Retry Logic

```typescript
// Max retries: 3
// Initial delay: 2 seconds
// Backoff: Exponential (2s, 4s, 8s)
// Total max time: ~120 seconds
```

## Tech Stack

- **Framework**: Next.js 15 (App Router)
- **UI**: Tailwind CSS + shadcn/ui
- **Animations**: Framer Motion
- **Icons**: Lucide React
- **API Client**: Fetch with retry logic
- **TypeScript**: Full type safety

## Performance

- **Initial load**: <1 second
- **Chat response**: 2-4 seconds
- **Page transitions**: Instant (client-side)
- **Bundle size**: Optimized with Next.js

## Production Deployment

### Build

```bash
npm run build
```

### Environment

Update `.env.production.local`:

```ini
NEXT_PUBLIC_API_URL=https://your-api-domain.com
```

### Deploy

Deploy to Vercel, Netlify, or any Node.js host:

```bash
# Vercel
vercel deploy

# Docker
docker build -t omnicortex-admin .
docker run -p 3000:3000 omnicortex-admin
```

## Support

For issues:

1. Check API is running: `curl http://localhost:8000/`
2. Check browser console for errors
3. Review `CONFIGURATION.md` in root directory
4. Restart dev server: `npm run dev`

## License

Part of OmniCortex project.
