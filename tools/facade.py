"""Façade lokal buat stack serverless: SATU titik masuk, satu kapabilitas aktif.

  POST /job        {"capability":"image|video|music", "params":{...}, "profile":"..."}
  GET  /job/<id>                   status hasil (kalau async)
  GET  /mode     ;  POST /mode {"capability":"image","warm":true}
  GET  /capabilities               profil + biaya per kapabilitas
  GET  /health

Kebijakan "satu-satu" ditegakkan di sini (mutex), jadi butuh sisi server:
workergroup harus max_workers=1, kalau tidak dua worker bisa memegang model berbeda.

Jalankan:  uvicorn facade:app --host 127.0.0.1 --port 8090
"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

SPEC_URL = os.environ.get("STACK_SPEC_URL", "https://huggingface.co/zakie0161/cfg-9f3a/resolve/main/spec.json")
ENDPOINT = os.environ.get("STACK_ENDPOINT", "vs-a1")
OUT_DIR = Path(os.environ.get("STACK_OUT", str(Path.home() / "stack-out")))
# Kalau kosong, auth DIMATIKAN (cuma buat development di localhost!).
API_KEY = os.environ.get("STACK_API_KEY", "").strip()
OUT_DIR.mkdir(parents=True, exist_ok=True)


def require_auth(authorization: str = Header(default="")):
    """Semua endpoint berbayar dikunci bearer token - kalau tidak, siapa pun yang bisa
    mencapai port ini bisa membakar credit Vast-mu."""
    if not API_KEY:
        return
    tok = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if tok != API_KEY:
        raise HTTPException(401, "token salah/kosong - kirim 'Authorization: Bearer <STACK_API_KEY>'")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_profiles import t2i_graph, t2m_graph  # noqa: E402  (satu sumber kebenaran graph)

app = FastAPI(title="vs-a1 facade")
_state = {"mode": None, "lock": asyncio.Lock(), "busy": False, "jobs": {}}


def spec():
    with urllib.request.urlopen(SPEC_URL, timeout=60) as r:
        return json.load(r)


def build_graph(s, capability, profile, params):
    """Graph API-format + substitusi parameter, per kapabilitas."""
    if capability == "image":
        c = s["components"]["image"]
        return t2i_graph(c, params.get("prompt", ""), params.get("aspect", "16:9"),
                          float(params.get("megapixels", 1.0)), int(params.get("seed", 0)),
                          int(params.get("steps", 8)))
    if capability == "music":
        c = s["components"]["music"]
        return t2m_graph(c, params.get("caption", ""), params.get("lyrics", ""),
                           float(params.get("seconds", 12)), int(params.get("seed", 0)),
                           int(params.get("steps", 30)), float(params.get("cfg", 1.7)))
    name = profile or "t2va-544p"
    vn = s["components"]["video"]
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


def cost_of(s, capability, profile):
    if capability in ("image", "music"):
        return s["profiles"]["image-t2i" if capability == "image" else "music-t2m"]["cost"]
    return s["profiles"][profile or "t2va-544p"]["cost"]


def loudnorm(src, dst, muxed=False):
    """Normalkan loudness (temuan QC: musik peak 0.0 dBFS, audio video mean -30 dB).

    muxed=True -> file video: stream video disalin apa adanya, hanya audionya yang diolah.
    Target -16 LUFS dengan true-peak -1.5 dBFS.
    """
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    if muxed:
        cmd += ["-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    cmd.append(str(dst))
    try:
        subprocess.run(cmd, check=True, timeout=300)
        return True
    except Exception:
        return False


async def call_endpoint(graph, cost):
    from vastai import Serverless  # SDK-nya sama yang dipakai CLI
    s = spec()
    body = {"input": {"request_id": "", "workflow_json": graph, "return_outputs_as_base64": True}}
    client = Serverless()
    try:
        ep = await client.get_endpoint(name=ENDPOINT)
        res = await ep.request("/generate/sync", body, cost=cost)
        out = res.get("response") if isinstance(res, dict) and "response" in res else res
        return out
    finally:
        await client.close()


def harvest(out, capability):
    """Simpan keluaran ke disk lokal; kembalikan daftar file."""
    saved = []
    for item in (out.get("output") or []):
        blob = item.get("data") or item.get("base64") or item.get("b64")
        name = item.get("filename") or f"{capability}_{int(time.time())}"
        # wrapper mengirim base64 di "data" + "mimetype"; pastikan ekstensi cocok
        mime = (item.get("mimetype") or "").lower()
        if blob and "." not in name:
            ext = {"image/png": ".png", "image/jpeg": ".jpg", "audio/flac": ".flac",
                   "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "video/mp4": ".mp4"}.get(mime, "")
            name += ext
        p = OUT_DIR / name
        if blob:
            p.write_bytes(base64.b64decode(blob))
        elif item.get("url"):
            with urllib.request.urlopen(item["url"], timeout=300) as r:
                p.write_bytes(r.read())
        else:
            saved.append({"filename": name, "error": "respons nggak berisi data/base64/url",
                          "keys": list(item.keys())})
            continue
        if capability in ("music", "video"):
            # tuker di tempat; kalau ffmpeg gagal, simpan versi mentah daripada kehilangan hasil
            pre = p.with_name(p.stem + ".pre" + p.suffix)
            p.replace(pre)
            if loudnorm(pre, p, muxed=(capability == "video")):
                pre.unlink(missing_ok=True)
            else:
                pre.replace(p)
        saved.append({"filename": name, "path": str(p), "bytes": p.stat().st_size})
    return saved


class Job(BaseModel):
    capability: str
    profile: str | None = None
    params: dict = {}


class Mode(BaseModel):
    capability: str
    warm: bool = True


@app.get("/health")
async def health():
    return {"ok": True, "mode": _state["mode"], "busy": _state["busy"], "endpoint": ENDPOINT,
            "auth": bool(API_KEY)}


@app.get("/capabilities", dependencies=[Depends(require_auth)])
async def capabilities():
    s = spec()
    return {"capabilities": s.get("capabilities"),
            "profiles": {k: {"capability": v["capability"], "cost": v["cost"], "label": v.get("label")}
                         for k, v in s["profiles"].items()}}


@app.post("/mode", dependencies=[Depends(require_auth)])
async def set_mode(m: Mode):
    if m.capability not in ("video", "image", "music"):
        raise HTTPException(400, "capability harus video|image|music")
    async with _state["lock"]:
        _state["mode"] = m.capability
        warm = None
        if m.warm:
            s = spec()
            g = build_graph(s, m.capability, None, {"prompt": "warmup", "caption": "warmup", "lyrics": "warmup"})
            t0 = time.time()
            try:
                out = await call_endpoint(g, cost_of(s, m.capability, None))
                warm = {"ok": out.get("status") in ("completed", "done"), "seconds": round(time.time() - t0, 1)}
            except Exception as e:
                warm = {"ok": False, "error": str(e)[:200]}
        return {"mode": m.capability, "warmup": warm}


@app.get("/mode", dependencies=[Depends(require_auth)])
async def get_mode():
    return {"mode": _state["mode"]}


@app.post("/job", dependencies=[Depends(require_auth)])
async def job(j: Job):
    if j.capability not in ("video", "image", "music"):
        raise HTTPException(400, "capability harus video|image|music")
    if _state["mode"] and _state["mode"] != j.capability:
        raise HTTPException(409, f"mode aktif = {_state['mode']}; pindah dulu lewat POST /mode")
    if _state["busy"]:
        raise HTTPException(429, "worker sedang mengerjakan satu job (max_workers=1)")
    _state["busy"] = True
    jid = f"{j.capability}-{int(time.time())}"
    try:
        s = spec()
        g = build_graph(s, j.capability, j.profile, j.params)
        t0 = time.time()
        out = await call_endpoint(g, cost_of(s, j.capability, j.profile))
        wall = round(time.time() - t0, 1)
        files = harvest(out, j.capability)
        rec = {"id": jid, "capability": j.capability, "status": out.get("status"),
               "wall_seconds": wall, "files": files}
        _state["jobs"][jid] = rec
        return rec
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"endpoint gagal: {str(e)[:300]}")
    finally:
        _state["busy"] = False


@app.get("/job/{jid}", dependencies=[Depends(require_auth)])
async def get_job(jid: str):
    return _state["jobs"].get(jid) or {"error": "tidak ada job dengan id itu"}
