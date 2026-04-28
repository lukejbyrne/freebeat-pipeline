#!/usr/bin/env python3
"""Freebeat Studio backend — drives KIE (Suno) + Freebeat HTTP APIs from the browser.

    pip install flask requests   # both already available
    python scripts/studio_server.py
    open http://127.0.0.1:5050

Reads KIE_API_KEY and FREEBEAT_API_KEY from .env. Saves outputs under output/<track_id>/.
"""
import json
import mimetypes
import os
import pathlib
import time
import uuid
from typing import Any

import requests
from flask import Flask, jsonify, request, send_from_directory, abort

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
STUDIO = ROOT / "studio"
OUTPUT = ROOT / "output"

KIE_BASE = "https://api.kie.ai"
FB_BASE = os.environ.get("FREEBEAT_API_HOST", "https://api.freebeatfit.com")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

KIE_DONE = {"SUCCESS", "FIRST_SUCCESS"}
KIE_FAIL = {"CREATE_TASK_FAILED", "GENERATE_AUDIO_FAILED", "CALLBACK_EXCEPTION", "SENSITIVE_WORD_ERROR"}


def load_env() -> dict[str, str]:
    if not ENV.exists():
        raise SystemExit("missing .env — add KIE_API_KEY and FREEBEAT_API_KEY")
    out: dict[str, str] = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    for k in ("KIE_API_KEY", "FREEBEAT_API_KEY"):
        if not out.get(k):
            raise SystemExit(f"{k} missing in .env")
    return out


KEYS = load_env()
KIE_HEADERS = {"Authorization": f"Bearer {KEYS['KIE_API_KEY']}"}
FB_HEADERS = {"Authorization": KEYS["FREEBEAT_API_KEY"], "Content-Type": "application/json"}

app = Flask(__name__, static_folder=None)


def _fb_post(path: str, body: dict[str, Any]) -> Any:
    r = requests.post(f"{FB_BASE}{path}", json=body, headers=FB_HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"freebeat {path} failed: {j}")
    return j.get("data")


def _ext(p: pathlib.Path) -> str:
    return p.suffix.lstrip(".").lower() or "mp3"


# ---------- static ----------

@app.get("/")
def index():
    return send_from_directory(STUDIO, "index.html")


@app.get("/<path:filename>")
def studio_static(filename: str):
    path = STUDIO / filename
    if path.is_file():
        return send_from_directory(STUDIO, filename)
    abort(404)


@app.get("/output/<path:filename>")
def output_static(filename: str):
    return send_from_directory(OUTPUT, filename)


# ---------- music (KIE Suno) ----------

@app.post("/api/music")
def music_submit():
    j = request.get_json(force=True)
    prompt = (j.get("prompt") or "").strip()
    if not prompt:
        return jsonify(error="prompt required"), 400
    track_id = j.get("track_id") or f"studio_{int(time.time())}"
    body = {
        "prompt": prompt,
        "model": j.get("model") or "V4_5PLUS",
        "customMode": False,
        "instrumental": bool(j.get("instrumental", True)),
        "callBackUrl": "https://example.com/noop",
    }
    r = requests.post(f"{KIE_BASE}/api/v1/generate", headers=KIE_HEADERS, json=body, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 200:
        return jsonify(error=payload), 502
    (OUTPUT / track_id).mkdir(parents=True, exist_ok=True)
    return jsonify(task_id=payload["data"]["taskId"], track_id=track_id)


@app.get("/api/music/status")
def music_status():
    task_id = request.args.get("task_id")
    track_id = request.args.get("track_id")
    if not task_id or not track_id:
        return jsonify(error="task_id and track_id required"), 400
    r = requests.get(
        f"{KIE_BASE}/api/v1/generate/record-info",
        headers=KIE_HEADERS, params={"taskId": task_id}, timeout=30,
    )
    d = r.json().get("data") or {}
    status = d.get("status") or "PENDING"
    resp = {"status": status, "raw_status": status}
    if status in KIE_FAIL:
        resp["error"] = d.get("errorMessage") or status
        return jsonify(resp), 200
    if status in KIE_DONE:
        clips = (d.get("response") or {}).get("sunoData") or []
        url = next((c.get("audioUrl") for c in clips if c.get("audioUrl")), None)
        if url:
            dest = OUTPUT / track_id / "music.mp3"
            if not (dest.exists() and dest.stat().st_size > 0):
                dl = requests.get(url, headers=UA, stream=True, timeout=300)
                dl.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in dl.iter_content(1 << 16):
                        f.write(chunk)
            resp["audio_url"] = f"/output/{track_id}/music.mp3"
            resp["remote_url"] = url
            resp["status"] = "COMPLETED"
    return jsonify(resp)


# ---------- video (Freebeat) ----------

@app.post("/api/video")
def video_submit():
    j = request.get_json(force=True)
    track_id = j.get("track_id")
    if not track_id:
        return jsonify(error="track_id required"), 400
    music_path = OUTPUT / track_id / "music.mp3"
    if not music_path.exists():
        return jsonify(error=f"missing {music_path}"), 400

    # 1. presigned upload URL
    filename = music_path.name
    key = f"dance/music/{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}.{_ext(music_path)}"
    pre_list = _fb_post("/v1/mcp/agent/genUploadSignUrl", {
        "reqList": [{"key": key, "fileName": filename, "bucketName": "freebeat-static"}],
    })
    sign_url = pre_list[0]["signURL"]
    final_url = pre_list[0]["finalStaticUrl"]

    # 2. PUT to S3
    upload_headers = {"Content-Type": mimetypes.guess_type(filename)[0] or "audio/mpeg"}
    from urllib.parse import urlparse, parse_qs
    signed_headers = parse_qs(urlparse(sign_url).query).get("X-Amz-SignedHeaders", [""])[0]
    if "x-amz-acl" in signed_headers.lower().split(";"):
        upload_headers["x-amz-acl"] = "public-read"
    with open(music_path, "rb") as f:
        put = requests.put(sign_url, data=f.read(), headers=upload_headers, timeout=300)
    put.raise_for_status()

    # 3. saveMusicV3 → music_id (number)
    music_id = _fb_post("/v1/mcp/agent/saveMusicV3", {"copyUrl": final_url})

    # 4. createSession (music video)
    aspect = j.get("aspect_ratio") or "16:9"
    resolution = int(j.get("resolution") or 1080)
    body = {
        "type": 0,
        "mvMode": "fast",
        "mvType": j.get("mv_type") or "abstract",
        "style": j.get("style"),
        "musicId": music_id,
        "prompt": j.get("prompt"),
        "aspectRatio": aspect,
        "resolution": resolution,
        "watermark": bool(j.get("watermark", False)),
    }
    body = {k: v for k, v in body.items() if v is not None}
    sess = _fb_post("/v1/mcp/openMv/createSession", body)
    return jsonify(task_id=sess["trackId"], music_id=music_id)


@app.get("/api/video/status")
def video_status():
    task_id = request.args.get("task_id")
    if not task_id:
        return jsonify(error="task_id required"), 400
    d = _fb_post("/v1/mcp/openMv/querySessionStatus", {"trackId": task_id}) or {}
    return jsonify(d)


@app.get("/api/video/result")
def video_result():
    task_id = request.args.get("task_id")
    track_id = request.args.get("track_id")
    if not task_id or not track_id:
        return jsonify(error="task_id and track_id required"), 400
    d = _fb_post("/v1/mcp/openMv/querySessionResult", {"trackId": task_id}) or {}
    status = (d.get("status") or "").strip().lower()
    if status == "failed":
        return jsonify(status="failed", error=d.get("errorMsg") or "failed"), 200
    if status != "completed":
        return jsonify(status=d.get("status"), pending=True), 200
    raw = d.get("resultPayload")
    if not raw:
        return jsonify(error="missing resultPayload", raw=d), 502
    payload = json.loads(raw)
    video_url = payload.get("video_url")
    if not video_url:
        return jsonify(error="missing video_url", payload=payload), 502
    dest = OUTPUT / track_id / "video.mp4"
    if not (dest.exists() and dest.stat().st_size > 0):
        dl = requests.get(video_url, headers=UA, stream=True, timeout=600)
        dl.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in dl.iter_content(1 << 16):
                f.write(chunk)
    meta = OUTPUT / track_id / "meta.json"
    meta.write_text(json.dumps({
        "track_id": track_id,
        "freebeat_task_id": task_id,
        "video_url": video_url,
        "cover_url": payload.get("cover_url"),
        "saved_at": int(time.time()),
    }, indent=2))
    return jsonify(
        status="completed",
        video_url=f"/output/{track_id}/video.mp4",
        cover_url=payload.get("cover_url"),
        remote_url=video_url,
        size_bytes=dest.stat().st_size,
    )


if __name__ == "__main__":
    OUTPUT.mkdir(exist_ok=True)
    print(f"Freebeat Studio running at http://127.0.0.1:5050")
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5050")), debug=False)
