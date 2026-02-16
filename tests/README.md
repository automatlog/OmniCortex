# Tests Directory

This directory now keeps only phase-focused backend tests.

## Active Tests

- `tests/test_phase1.py` - Agent model/API enhancements (role type, industry, URLs, starters, media links, scraped data, limits, scraper behavior)
- `tests/test_phase2.py` - Channels/tools core checks
- `tests/test_phase3.py` - Document/session/reporting checks
- `tests/test_phase4.py` - Realtime/security/RAG checks
- `tests/test_phase4_auth.py` - API key auth flow regression
- `tests/test_phase4_status.py` - Phase 4 status checks

## Run

```bash
uv run pytest tests/test_phase1.py -q
uv run python tests/test_phase4_auth.py
```

## Notes

- Startup dependency hooks are disabled inside tests that should not depend on live Ollama/vLLM.
- Keep test files ASCII-only where possible to avoid Windows console encoding issues.
