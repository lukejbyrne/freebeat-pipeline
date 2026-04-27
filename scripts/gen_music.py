#!/usr/bin/env python3
"""Generate one music track via KIE (Suno) and save it to disk.

Usage:
    python scripts/gen_music.py --prompt "study lofi, 72 BPM, ..." --out output/demo/music.mp3

Reads KIE_API_KEY from .env. Idempotent: if --out already exists, exits 0.

KIE Suno API:
  POST https://api.kie.ai/api/v1/generate
       body: {prompt, model, customMode, instrumental, callBackUrl}
       returns: data.taskId
  GET  https://api.kie.ai/api/v1/generate/record-info?taskId=<id>
       returns: data.status in {PENDING, TEXT_GENERATE, FIRST_SUCCESS, SUCCESS, ...}
                data.response.sunoData[] — Suno returns 2 clips per task; each has audioUrl.
"""
import argparse, json, pathlib, sys, time
import requests

API = "https://api.kie.ai"
SUBMIT = f"{API}/api/v1/generate"
POLL = f"{API}/api/v1/generate/record-info"
ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"

DEFAULT_MODEL = "V4_5PLUS"  # also valid: V4_5, V4, V3_5

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

DONE_STATES = {"SUCCESS", "FIRST_SUCCESS"}
FAIL_STATES = {
    "CREATE_TASK_FAILED", "GENERATE_AUDIO_FAILED",
    "CALLBACK_EXCEPTION", "SENSITIVE_WORD_ERROR",
}


def load_key():
    if not ENV.exists():
        sys.exit("missing .env — copy .env.example to .env and fill in KIE_API_KEY")
    for line in ENV.read_text().splitlines():
        if line.startswith("KIE_API_KEY="):
            v = line.split("=", 1)[1].strip()
            if v:
                return v
    sys.exit("KIE_API_KEY not set in .env")


def submit(headers, model, prompt, instrumental):
    body = {
        "prompt": prompt,
        "model": model,
        "customMode": False,
        "instrumental": instrumental,
        # KIE requires this field but we poll instead of using it.
        "callBackUrl": "https://example.com/noop",
    }
    r = requests.post(SUBMIT, headers=headers, json=body, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 200:
        sys.exit(f"KIE submit failed: {j}")
    return j["data"]["taskId"]


def first_audio_url(data):
    clips = (data.get("response") or {}).get("sunoData") or []
    for c in clips:
        url = c.get("audioUrl")
        if url:
            return url
    return None


def poll(headers, task_id, timeout=600):
    start = time.time()
    delay = 6
    last = None
    while time.time() - start < timeout:
        time.sleep(delay)
        try:
            r = requests.get(POLL, params={"taskId": task_id}, headers=headers, timeout=30)
            d = r.json().get("data", {})
        except Exception as e:
            print(f"  poll err: {e}", file=sys.stderr)
            continue
        status = d.get("status")
        if status != last:
            print(f"  {int(time.time()-start)}s status={status}", file=sys.stderr)
            last = status
        if status in DONE_STATES:
            url = first_audio_url(d)
            if url:
                return url
        if status in FAIL_STATES:
            sys.exit(f"KIE task failed: {status} {d.get('errorMessage')}")
        delay = min(delay + 2, 15)
    sys.exit(f"KIE task {task_id} timed out after {timeout}s")


def download(url, dest):
    r = requests.get(url, headers=UA, stream=True, timeout=300)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 16):
            f.write(chunk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--instrumental", default="true")
    args = ap.parse_args()

    out = args.out
    if out.exists() and out.stat().st_size > 0:
        print(f"already exists, skip: {out}")
        return
    out.parent.mkdir(parents=True, exist_ok=True)

    key = load_key()
    headers = {"Authorization": f"Bearer {key}"}
    headers_json = {**headers, "Content-Type": "application/json"}

    print(f"submitting to {args.model}")
    task_id = submit(headers_json, args.model, args.prompt,
                     args.instrumental.lower() == "true")
    print(f"task_id={task_id}")
    url = poll(headers, task_id)
    print(f"downloading {url}")
    download(url, out)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
