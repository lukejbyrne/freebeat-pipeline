#!/usr/bin/env python3
"""Iterate tracks.csv and call run_one.py per row, with bounded concurrency.

Music generations run in parallel (KIE handles concurrency fine). Each row
finishes by writing `output/<id>/needs_video` — Claude then sweeps those and
runs the Freebeat MCP video step.

Usage:
    python scripts/run_batch.py            # all rows
    python scripts/run_batch.py --max 3    # only first 3
    python scripts/run_batch.py --concurrency 2
"""
import argparse, concurrent.futures as cf, csv, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def run(row):
    cmd = [
        sys.executable, str(ROOT / "scripts" / "run_one.py"),
        "--id", row["id"],
        "--music-prompt", row["music_prompt"],
        "--video-prompt", row["video_prompt"],
    ]
    print(f"[{row['id']}] start")
    subprocess.check_call(cmd)
    print(f"[{row['id']}] done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(ROOT / "tracks.csv"))
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--max", type=int, default=None)
    args = ap.parse_args()

    with open(args.csv) as f:
        rows = list(csv.DictReader(f))
    if args.max:
        rows = rows[: args.max]

    print(f"running {len(rows)} tracks, concurrency={args.concurrency}")
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(run, r) for r in rows]
        for fut in cf.as_completed(futs):
            try:
                fut.result()
            except subprocess.CalledProcessError as e:
                print(f"row failed: {e}", file=sys.stderr)

    pending = list((ROOT / "output").glob("*/needs_video"))
    print(f"\n{len(pending)} tracks queued for video — ask Claude to run the Freebeat MCP step.")


if __name__ == "__main__":
    main()
