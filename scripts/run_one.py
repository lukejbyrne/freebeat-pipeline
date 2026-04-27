#!/usr/bin/env python3
"""Generate music for one track and queue the video step for Claude.

The Freebeat MCP runs inside Claude Code, not in plain Python — so this script
does the music half itself, then drops a marker file telling Claude to pick up
the video half. Claude (with this folder's CLAUDE.md) sweeps `output/*/needs_video`
and calls the MCP tool for each.

Usage:
    python scripts/run_one.py --id rainy_desk \
        --music-prompt "..." --video-prompt "..."
"""
import argparse, json, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--music-prompt", required=True)
    ap.add_argument("--video-prompt", required=True)
    args = ap.parse_args()

    out = ROOT / "output" / args.id
    out.mkdir(parents=True, exist_ok=True)
    music = out / "music.mp3"
    video = out / "video.mp4"

    if video.exists() and video.stat().st_size > 0:
        print(f"[{args.id}] video already exists, skip")
        return

    started = time.time()
    if not (music.exists() and music.stat().st_size > 0):
        subprocess.check_call([
            sys.executable, str(ROOT / "scripts" / "gen_music.py"),
            "--prompt", args.music_prompt,
            "--out", str(music),
        ])

    # Drop a marker for Claude. CLAUDE.md tells Claude to sweep these and
    # call the Freebeat MCP video tool with the audio + visual prompt.
    marker = out / "needs_video"
    marker.write_text(json.dumps({
        "id": args.id,
        "audio": str(music),
        "video_out": str(video),
        "video_prompt": args.video_prompt,
        "music_seconds": time.time() - started,
    }, indent=2))
    print(f"[{args.id}] music ready, queued video at {marker}")


if __name__ == "__main__":
    main()
