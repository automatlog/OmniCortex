# LFM HTML Server

Simple Node.js Express server to serve the LFM Mic Test HTML interface on port 3000.

## Setup

1. Install dependencies:
```bash
cd ~/OmniCortex/lfm
npm install
```

2. Start the server:
```bash
cd ~/OmniCortex/lfm
npm start
```

Or for development:
```bash
cd ~/OmniCortex/lfm
npm run dev
```

The server will start on:
- Local: http://0.0.0.0:3000
- Public URL: https://jwpma2d42856fn-3000.proxy.runpod.net

## Optional: configure LFM target URL

The HTML app reads LFM URL from:
1. saved browser value
2. server `/config` response (`LFM_BASE_URL` env)
3. hardcoded fallback

Start with explicit LFM target:
```bash
cd ~/OmniCortex/lfm
LFM_BASE_URL="https://jwpma2d42856fn-8012.proxy.runpod.net" npm start
```

## Configuration

The HTML file automatically connects to the LFM server at:
```
https://jwpma2d42856fn-8012.proxy.runpod.net
```

You can override the LFM base URL in the web interface by modifying the "LFM Base URL" input field.

## If you see `Failed to fetch` on `/stt` or `/respond`

1. Verify LFM is running and reachable:
```bash
curl -i https://jwpma2d42856fn-8012.proxy.runpod.net/health
```
2. If health shows `"loaded": false`, click **Warm Model** in UI (or start LFM with preload).
3. Confirm the RunPod public endpoint is exposed for port `8012`.
4. Keep both UI and LFM URLs on HTTPS when opening from public browser.

## Files

- `server.js` - Express server that serves the HTML
- `lfm_mic_test.html` - Web UI for testing LFM endpoints
- `package.json` - Node.js dependencies and scripts
