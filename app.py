"""app.py - satu titik masuk buat stack serverless (video / image / music).

Jalankan:
    python3 app.py
Konfigurasi lewat environment atau file .env di samping file ini (lihat .env.example).

  VAST_API_KEY         key Vast (wajib, buat manggil endpoint)
  VAST_WEB_URL         URL API/console Vast            (default https://console.vast.ai)
  VAST_AUTOSCALER_URL  URL router serverless Vast      (default https://run.vast.ai)
  STACK_ENDPOINT       nama endpoint serverless        (default vs-a1)
  STACK_SPEC_URL       URL spec (profil + daftar bobot)
  STACK_API_KEY        token buat masuk API ini; kosong = auth MATI (localhost only)
  STACK_HOST/STACK_PORT alamat & port tempel
  STACK_OUT            folder nyimpen hasil

Contoh pakai:
    curl -H "Authorization: Bearer $TOK" localhost:8090/capabilities
    curl -XPOST -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
         localhost:8090/mode -d '{"capability":"image","warm":true}'
    curl -XPOST -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
         localhost:8090/job -d '{"capability":"image","params":{"prompt":"..."}}'
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

# ---------------------------------------------------------------- konfigurasi
def _load_dotenv(path: Path) -> None:
    """Pembaca .env mini - tanpa dependency tambahan. Nilai yang sudah ada di
    environment tidak ditimpa."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(Path(__file__).resolve().parent / ".env")

VAST_WEB_URL = os.environ.get("VAST_WEB_URL", "https://console.vast.ai").rstrip("/")
VAST_AUTOSCALER_URL = os.environ.get("VAST_AUTOSCALER_URL", "https://run.vast.ai").rstrip("/")
STACK_ENDPOINT = os.environ.get("STACK_ENDPOINT", "vs-a1")
SPEC_URL = os.environ.get(
    "STACK_SPEC_URL", "https://huggingface.co/zakie0161/cfg-9f3a/resolve/main/spec.json")
API_KEY = os.environ.get("STACK_API_KEY", "").strip()
HOST = os.environ.get("STACK_HOST", "127.0.0.1")
PORT = int(os.environ.get("STACK_PORT", "8090"))
OUT_DIR = Path(os.environ.get("STACK_OUT", str(Path.home() / "stack-out")))
OUT_DIR.mkdir(parents=True, exist_ok=True)
CAPS = ("video", "image", "music")

app = FastAPI(title="vs-a1 stack", version="1")
_state = {"mode": None, "busy": False, "jobs": {}}


def require_auth(authorization: str = Header(default="")):
    """Semua rute berbayar dikunci bearer token. Tanpa ini, siapa pun yang bisa
    mencapai port ini bisa membakar credit Vast-mu."""
    if not API_KEY:
        return
    tok = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if tok != API_KEY:
        raise HTTPException(401, "token salah/kosong - kirim 'Authorization: Bearer <STACK_API_KEY>'")


def spec() -> dict:
    with urllib.request.urlopen(SPEC_URL, timeout=60) as r:
        return json.load(r)


# ------------------------------------------------------------------- graph
def canvas(aspect: str, megapixels: float, multiple: int = 32):
    w_r, h_r = (float(x) for x in aspect.split(":"))
    area = megapixels * 1_000_000
    h = (area / (w_r / h_r)) ** 0.5
    w = h * (w_r / h_r)
    snap = lambda v: max(multiple, round(v / multiple) * multiple)
    return int(snap(w)), int(snap(h))


def build(s: dict, capability: str, profile: str | None, params: dict) -> dict:
    if capability not in CAPS:
        raise HTTPException(400, "capability harus video|image|music")
    comp = s["components"]

    if capability == "image":
        c = comp["image"]
        w, h = canvas(params.get("aspect", "16:9"), float(params.get("megapixels", 1.0)))
        return {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": c["unet"], "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": c["clip"], "type": c["clip_type"], "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": c["vae"]}},
            "4": {"class_type": c.get("encode_node", "CLIPTextEncode"),
                  "inputs": {"clip": ["2", 0], "text": params.get("prompt", "")}},
            "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
            "6": {"class_type": c.get("latent_node", "EmptyLatentImage"),
                  "inputs": {"width": w, "height": h, "batch_size": 1}},
            "7": {"class_type": "KSampler", "inputs": {
                "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
                "seed": int(params.get("seed", 0)), "steps": int(params.get("steps", 8)),
                "cfg": float(c.get("cfg", 1.0)), "sampler_name": "euler", "scheduler": "simple",
                "denoise": 1.0}},
            "8": {"class_type": c.get("decode_node", "VAEDecode"), "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
            "9": {"class_type": c.get("save_node", "SaveImage"),
                  "inputs": {"images": ["8", 0], "filename_prefix": "job-image"}},
        }

    if capability == "music":
        c = comp["music"]
        secs = float(params.get("seconds", 12))
        return {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": c["unet"], "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": c["clip"], "type": c["clip_type"], "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": c["vae"]}},
            "4": {"class_type": c["encode_node"], "inputs": {
                "clip": ["2", 0], "caption": params.get("caption", ""), "lyrics": params.get("lyrics", ""),
                "seed": int(params.get("seed", 0)), "max_duration": secs,
                "cfg_scale": float(params.get("cfg", 1.7)), "top_k": int(params.get("top_k", 50))}},
            "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
            "6": {"class_type": c["latent_node"], "inputs": {"seconds": secs, "batch_size": 1}},
            "7": {"class_type": "KSampler", "inputs": {
                "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
                "seed": int(params.get("seed", 0)), "steps": int(params.get("steps", 30)),
                "cfg": float(params.get("cfg", 1.7)), "sampler_name": "euler", "scheduler": "simple",
                "denoise": 1.0}},
            "8": {"class_type": c["decode_node"], "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
            "9": {"class_type": c["save_node"], "inputs": {"audio": ["8", 0], "filename_prefix": "job-music"}},
        }

    # video: pakai graph dari spec, ganti parameternya
    name = profile or "t2va-544p"
    if name not in s["profiles"]:
        raise HTTPException(400, f"profil '{name}' tidak ada; pilihan: {', '.join(s['profiles'])}")
    vn = comp["video"]
    g = json.loads(json.dumps(s["profiles"][name]["graph"]))
    for v in g.values():
        ct, i = v.get("class_type"), v.get("inputs", {})
        if ct == vn["image_node"]:
            i["prompt"] = params.get("prompt", i.get("prompt"))
            for k in ("width", "height", "length"):
                if k in params:
                    i[k] = int(params[k])
        elif ct == vn["lora_node"] and params.get("lora"):
            i["lora_name"] = params["lora"]
        elif ct == vn["shift_node"] and params.get("shift"):
            sv, sa = params["shift"].split("/")
            i["shift_video"], i["shift_audio"] = float(sv), float(sa)
        elif ct == vn["sched_node"] and params.get("steps"):
            i["steps"] = int(params["steps"])
        elif ct == vn["noise_node"] and params.get("seed") is not None:
            i["noise_seed"] = int(params["seed"])
    return g


def cost_of(s: dict, capability: str, profile: str | None) -> int:
    key = {"image": "image-t2i", "music": "music-t2m"}.get(capability, profile or "t2va-544p")
    return int(s["profiles"].get(key, {}).get("cost", 100))


# ------------------------------------------------------------------ pemanggilan
async def call_endpoint(graph: dict, cost: int) -> dict:
    from vastai import Serverless
    if not os.environ.get("VAST_API_KEY"):
        raise HTTPException(500, "VAST_API_KEY belum di-set")
    body = {"input": {"request_id": "", "workflow_json": graph, "return_outputs_as_base64": True}}
    client = Serverless(autoscaler_url=VAST_AUTOSCALER_URL, webserver_url=VAST_WEB_URL)
    try:
        ep = await client.get_endpoint(name=STACK_ENDPOINT)
        res = await ep.request("/generate/sync", body, cost=cost)
        return res.get("response") if isinstance(res, dict) and "response" in res else res
    except Exception as e:
        msg = str(e)[:300]
        raise HTTPException(502, f"endpoint '{STACK_ENDPOINT}' gagal: {msg}")
    finally:
        try:
            await client.close()
        except Exception:
            pass


def loudnorm(src: Path, dst: Path, muxed: bool = False) -> bool:
    """-16 LUFS / true-peak -1.5 dBFS. muxed=True: stream video disalin, audio saja."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    cmd += (["-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k"]
            if muxed else ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"])
    cmd.append(str(dst))
    try:
        subprocess.run(cmd, check=True, timeout=300)
        return True
    except Exception:
        return False


def harvest(out: dict, capability: str) -> list[dict]:
    saved = []
    ext_by_mime = {"image/png": ".png", "image/jpeg": ".jpg", "audio/flac": ".flac",
                   "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "video/mp4": ".mp4"}
    for item in (out.get("output") or []):
        blob = item.get("data") or item.get("base64") or item.get("b64")
        name = item.get("filename") or f"{capability}_{int(time.time())}"
        if blob and "." not in name:
            name += ext_by_mime.get((item.get("mimetype") or "").lower(), "")
        p = OUT_DIR / name
        if blob:
            p.write_bytes(base64.b64decode(blob))
        elif item.get("url"):
            with urllib.request.urlopen(item["url"], timeout=300) as r:
                p.write_bytes(r.read())
        else:
            saved.append({"filename": name, "error": "respons tidak berisi data/url",
                          "keys": list(item.keys())})
            continue
        if capability in ("music", "video"):
            pre = p.with_name(p.stem + ".pre" + p.suffix)
            p.replace(pre)
            if loudnorm(pre, p, muxed=(capability == "video")):
                pre.unlink(missing_ok=True)
            else:
                pre.replace(p)
        saved.append({"filename": name, "path": str(p), "bytes": p.stat().st_size})
    return saved


# --------------------------------------------------------------------- rute
class Job(BaseModel):
    capability: str
    profile: str | None = None
    params: dict = {}


class Mode(BaseModel):
    capability: str
    warm: bool = True


@app.get("/health")
async def health():
    return {"ok": True, "mode": _state["mode"], "busy": _state["busy"],
            "endpoint": STACK_ENDPOINT, "auth": bool(API_KEY),
            "vast_web_url": VAST_WEB_URL, "vast_autoscaler_url": VAST_AUTOSCALER_URL}


@app.get("/capabilities", dependencies=[Depends(require_auth)])
async def capabilities():
    s = spec()
    return {"capabilities": s.get("capabilities"),
            "profiles": {k: {"capability": v["capability"], "cost": v["cost"], "label": v.get("label")}
                         for k, v in s["profiles"].items()}}


@app.post("/mode", dependencies=[Depends(require_auth)])
async def set_mode(m: Mode):
    if m.capability not in CAPS:
        raise HTTPException(400, "capability harus video|image|music")
    _state["mode"] = m.capability
    warm = None
    if m.warm:
        s = spec()
        g = build(s, m.capability, None, {"prompt": "warmup", "caption": "warmup", "lyrics": "warmup"})
        t0 = time.time()
        try:
            out = await call_endpoint(g, cost_of(s, m.capability, None))
            warm = {"ok": out.get("status") in ("completed", "done"), "seconds": round(time.time() - t0, 1)}
        except HTTPException as e:
            warm = {"ok": False, "error": str(e.detail)[:200]}
    return {"mode": m.capability, "warmup": warm}


@app.get("/mode", dependencies=[Depends(require_auth)])
async def get_mode():
    return {"mode": _state["mode"]}


@app.post("/job", dependencies=[Depends(require_auth)])
async def job(j: Job):
    if j.capability not in CAPS:
        raise HTTPException(400, "capability harus video|image|music")
    if _state["mode"] and _state["mode"] != j.capability:
        raise HTTPException(409, f"mode aktif = {_state['mode']}; pindah lewat POST /mode dulu")
    if _state["busy"]:
        raise HTTPException(429, "sibuk: satu worker mengerjakan satu job (max_workers=1)")
    _state["busy"] = True
    jid = f"{j.capability}-{int(time.time())}"
    try:
        s = spec()
        g = build(s, j.capability, j.profile, j.params)
        t0 = time.time()
        out = await call_endpoint(g, cost_of(s, j.capability, j.profile))
        rec = {"id": jid, "capability": j.capability, "status": out.get("status"),
               "wall_seconds": round(time.time() - t0, 1), "timings": out.get("timings"),
               "files": harvest(out, j.capability)}
        _state["jobs"][jid] = rec
        return rec
    finally:
        _state["busy"] = False


@app.get("/job/{jid}", dependencies=[Depends(require_auth)])
async def get_job(jid: str):
    return _state["jobs"].get(jid) or {"error": "job tidak ditemukan"}


if __name__ == "__main__":
    import uvicorn
    if not API_KEY:
        print("[app] PERINGATAN: STACK_API_KEY kosong -> auth MATI. Hanya aman di localhost.")
    print(f"[app] {HOST}:{PORT} -> endpoint '{STACK_ENDPOINT}' via {VAST_AUTOSCALER_URL}")
    uvicorn.run(app, host=HOST, port=PORT)
