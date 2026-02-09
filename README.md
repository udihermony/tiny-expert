# Tiny Expert

Offline-first survival knowledge PWA. Curated knowledge cards with optional on-device AI summarization — no server, no cloud, no hallucination.

## What It Does

- **20 hand-crafted survival cards** across 7 categories: water, fire, shelter, first aid, food, navigation, rescue
- **Fuzzy keyword search** with title/tag boosting
- **Category filtering** for quick browsing
- **Works fully offline** via service worker caching
- **On-device AI answers** (optional) — a small LLM running in the browser summarizes retrieved cards into natural-language responses

## AI Integration (Spike)

Toggle "AI Answer" in the header to enable. The app loads [SmolLM2-360M](https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct) via [WebLLM](https://github.com/mlc-ai/web-llm) directly in the browser using WebGPU.

**Key design:** The LLM never invents survival advice. It only summarizes and reformats the retrieved knowledge cards. If no cards match, it says so.

- Model downloads once (~376MB), then cached in IndexedDB
- Streaming token output for responsive feel
- Send button / Enter key to trigger (no auto-fire while typing)
- Eject button to unload the model and free memory
- Performance metrics (TTFT, tokens/s) available via tap-to-reveal

## Run Locally

```bash
python3 -m http.server 8080
```

Open `http://localhost:8080` in a browser with WebGPU support (Chrome 113+).

## Project Structure

```
index.html      # Entire app — UI, cards database, search engine, AI integration
manifest.json   # PWA manifest
sw.js           # Service worker for offline caching
icon-192.png    # App icon (192x192)
icon-512.png    # App icon (512x512)
```

Single-file architecture — no build step, no dependencies, no bundler.

## Design Principles

1. **Offline-first** — everything works with no network
2. **No hallucination** — the LLM only reformats retrieved cards, never generates knowledge
3. **Warnings are first-class** — always displayed prominently
4. **Source attribution** — every card cites its source

## Roadmap

- [ ] Card generation pipeline (Claude API + source material → structured cards)
- [ ] Semantic search with embeddings (all-MiniLM-L6-v2)
- [ ] Larger on-device models (Gemma 3 1B, Phi-4-mini)
- [ ] Expand card database (200+ cards)

## License

MIT
