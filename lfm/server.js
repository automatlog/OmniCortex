const express = require('express');
const path = require('path');
const app = express();
const PORT = process.env.PORT || 3000;
const DEFAULT_LFM_BASE_URL = process.env.LFM_BASE_URL || 'https://jwpma2d42856fn-8012.proxy.runpod.net';

// Serve static files from current directory
app.use(express.static(path.join(__dirname)));
app.disable('x-powered-by');

app.get('/config', (req, res) => {
  res.json({
    lfmBaseUrl: DEFAULT_LFM_BASE_URL,
    serverTime: new Date().toISOString(),
  });
});

// Root route serves the HTML file
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'lfm_mic_test.html'));
});

// Start server
app.listen(PORT, '0.0.0.0', () => {
  console.log(`LFM HTML Server running on http://0.0.0.0:${PORT}`);
  console.log(`Public URL: https://jwpma2d42856fn-3000.proxy.runpod.net`);
  console.log(`LFM Base URL: ${DEFAULT_LFM_BASE_URL}`);
});
