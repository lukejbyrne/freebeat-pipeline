# Faceless YouTube pipeline — orchestrator instructions

You are the orchestrator. The viewer opens Claude Code in this folder and types
*"run the pipeline"* — that is your cue.

## Stack

1. **KIE (Suno)** — music generation via REST API. Helper: `scripts/gen_music.py`.
2. **Freebeat MCP** — video generation. Server is registered in `.mcp.json`.
   The MCP exposes these tools (see https://freebeat.ai/mcp-doc):
   - `upload_audio(url | file)` → returns `music_id`
   - `upload_image(file)` → returns `image_id` (only needed for effect mode / reference)
   - `list_effects()` → list effect templates (only for effect mode)
   - `generate_music_video(music_id, prompt, ...)` → returns `task_id`
   - `generate_effect(effect_id, music_id, prompt, reference_image_urls)` → returns `task_id`
   - `get_task_status(task_id)`
   - `get_task_result(task_id)` → returns the final video URL

If `/mcp` shows the server isn't connected, tell the user to add
`FREEBEAT_API_KEY=...` to `.env` and reconnect — `scripts/freebeat-mcp.sh` reads
it from there.

## Single-track flow

When the user asks to run the pipeline (single track):

1. Pick or accept a `<track_id>` (default: `demo`).
2. Read `prompts/music.txt` and `prompts/video.txt` — or use whatever the user
   typed in chat instead.
3. `mkdir -p output/<track_id>/`.
4. Generate music (blocks until mp3 lands):
   ```
   python scripts/gen_music.py \
     --prompt "$(cat prompts/music.txt)" \
     --out output/<track_id>/music.mp3
   ```
5. Call `freebeat.upload_audio` with `file=output/<track_id>/music.mp3`.
   Capture the returned `music_id`.
6. Call `freebeat.generate_music_video` with that `music_id` and the visual
   prompt. Capture `task_id`. Sensible defaults: `aspect_ratio=16:9`,
   `resolution=1080p`, `watermark=false`.
7. Poll `freebeat.get_task_status(task_id)` until it's done (the MCP may also
   expose a blocking variant — use that if available).
8. Call `freebeat.get_task_result(task_id)`. Download the returned video URL
   (use `requests` with a Mozilla UA — Suno CDN style trap may apply) and save
   to `output/<track_id>/video.mp4`.
9. Write `output/<track_id>/meta.json` with: prompts used, KIE task id,
   Freebeat `music_id` + `task_id`, total wall time.
10. Report the final mp4 path so the user can drag it into YouTube Studio.

## Batch flow

```
python scripts/run_batch.py
```

That parallelises the music half and writes `output/<id>/needs_video` markers.
Sweep those: for each marker, do steps 5–9 above, then delete the marker.

## Rules

- Idempotent: skip any track where `output/<id>/video.mp4` exists and is non-zero.
- Don't silently swap models. Surface KIE / Freebeat error messages verbatim.
- The user is filming this. Be terse. Run commands. Don't narrate.
