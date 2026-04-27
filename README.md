# Faceless YouTube pipeline

The whole setup is a visual walkthrough — open `guide/index.html` in your browser and follow along with the video.

```
freebeat/
├── guide/index.html   ← open this first
├── CLAUDE.md          orchestrator instructions Claude reads
├── .mcp.json          registers the Freebeat MCP server
├── prompts/           music + video prompt templates
├── tracks.csv         batch input
├── scripts/           gen_music.py, run_one.py, run_batch.py
└── output/<id>/       music.mp3, video.mp4, meta.json
```

Quick start:
```bash
cp .env.example .env   # fill in KIE_API_KEY
npx -y freebeat-mcp config
claude                  # then: "run the pipeline"
```
