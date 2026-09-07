#!/usr/bin/env python3
"""Klien generik buat stack spec: daftar profil, cek spec, kirim satu profil.

    python3 tools/stackctl.py --spec stack/spec.example.json --list
    python3 tools/stackctl.py --spec <spec> --profile small --local http://127.0.0.1:18188
    python3 tools/stackctl.py --spec <spec> --profile small --endpoint vs-a1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path


def load(path: str) -> dict:
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text())
    if path.startswith("http"):
        with urllib.request.urlopen(path, timeout=60) as r:
            return json.loads(r.read().decode())
    raise SystemExit(f"spec tidak ketemu: {path}")


def validate(spec: dict) -> list[str]:
    err = []
    for k in ("files", "profiles"):
        if k not in spec:
            err.append(f"field wajib hilang: {k}")
    for i, f in enumerate(spec.get("files", []) or []):
        for k in ("repo", "rev", "path", "subdir"):
            if not f.get(k):
                err.append(f"files[{i}].{k} kosong")
    if not spec.get("benchmark"):
        err.append("field benchmark kosong - measured_perf tidak akan representatif")
    return err


def post_local(base: str, graph: dict, timeout_s: int = 1800) -> dict:
    base = base.rstrip("/")
    req = urllib.request.Request(
        f"{base}/prompt",
        data=json.dumps({"prompt": graph, "client_id": "stackctl"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        pid = json.load(r)["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(1)
        with urllib.request.urlopen(f"{base}/history/{pid}", timeout=60) as r:
            hist = json.load(r)
        if pid in hist:
            st = (hist[pid].get("status") or {})
            files = [f for o in (hist[pid].get("outputs") or {}).values()
                     for f in (o.get("images") or []) + (o.get("videos") or []) + (o.get("gifs") or [])]
            return {"ok": st.get("completed", False), "seconds": round(time.time() - t0, 1),
                    "prompt_id": pid, "files": files, "status": st.get("status_str")}
    return {"ok": False, "seconds": timeout_s, "prompt_id": pid, "error": "timeout"}


def post_endpoint(name: str, graph: dict) -> dict:
    import asyncio

    from vastai import Serverless  # SDK pip install vastai

    async def go():
        async with Serverless() as client:
            ep = await client.get_endpoint(name=name)
            r = await ep.request("/generate/sync", {"input": {"workflow_json": graph}}, cost=100)
            body = r["response"] if isinstance(r, dict) and "response" in r else r
            return {"ok": str(body.get("status")) in ("completed", "done"),
                    "files": body.get("output"), "raw": str(body)[:400]}

    return asyncio.run(go())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--profile")
    ap.add_argument("--local", help="URL ComfyUI (bring-up)")
    ap.add_argument("--endpoint", help="nama endpoint serverless")
    a = ap.parse_args()

    spec = load(a.spec)
    err = validate(spec)
    if err:
        print("SPEC INVALID:\n  " + "\n  ".join(err), file=sys.stderr)
        return 2
    profiles = spec["profiles"]
    if a.list or not a.profile:
        print(f"stack: {spec.get('id','(tanpa id)')} | {len(spec['files'])} file | "
              f"total ~{sum(int(f.get('size',0)) for f in spec['files'])/1e9:.1f} GB")
        for k, v in profiles.items():
            print(f"  {k:14} {v.get('label','')}")
        return 0
    if a.profile not in profiles:
        print(f"profil '{a.profile}' tidak ada. pilihan: {', '.join(profiles)}", file=sys.stderr)
        return 2

    graph = profiles[a.profile]["graph"]
    if a.local:
        print(json.dumps(post_local(a.local, graph), indent=1))
    elif a.endpoint:
        print(json.dumps(post_endpoint(a.endpoint, graph), indent=1, default=str))
    else:
        print("pilih --local <url> atau --endpoint <nama>", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
