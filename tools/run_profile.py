"""Kirim salah satu profil dari spec ke ComfyUI lokal dan ukur waktunya.

Graph TIDAK ditulis di sini — semuanya diambil dari spec (satu sumber kebenaran),
jadi repo ini nggak menyebut model apa pun.

  python3 tools/run_profile.py --spec <spec-url-atau-file> --list
  python3 tools/run_profile.py --spec <spec> --profile <nama> --base http://127.0.0.1:18188
"""
import argparse
import json
import time
import urllib.error
import urllib.request


def load_spec(src):
    if src.startswith("http"):
        with urllib.request.urlopen(src, timeout=60) as r:
            return json.load(r)
    with open(src) as f:
        return json.load(f)


def run(base, graph, label, timeout_s=900, poll=2):
    req = urllib.request.Request(
        f"{base}/prompt",
        data=json.dumps({"prompt": graph, "client_id": label}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            pid = json.load(r)["prompt_id"]
    except urllib.error.HTTPError as e:
        print(f"{label}: DITOLAK {e.code} {e.read().decode()[:700]}")
        return None
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(poll)
        with urllib.request.urlopen(f"{base}/history/{pid}", timeout=60) as r:
            h = json.load(r)
        if pid in h:
            st = h[pid].get("status") or {}
            files = [f for o in (h[pid].get("outputs") or {}).values()
                     for f in (o.get("images") or []) + (o.get("videos") or [])
                     + (o.get("gifs") or []) + (o.get("audio") or [])]
            ok = bool(st.get("completed"))
            wall = time.time() - t0
            print(f"{label}: {'OK' if ok else 'GAGAL'} wall={wall:.1f}s files={files[:2]}")
            if not ok:
                err = [m for m in st.get("messages", []) if m[0] == "execution_error"]
                print("   error:", json.dumps(err)[:600])
            return wall
    print(f"{label}: TIMEOUT {timeout_s}s")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--base", default="http://127.0.0.1:18188")
    ap.add_argument("--profile")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--repeat", type=int, default=1, help=">1 = ukur warm juga")
    a = ap.parse_args()

    spec = load_spec(a.spec)
    prof = spec.get("profiles") or {}
    if a.list or not a.profile:
        print(f"stack: {spec.get('id','(tanpa id)')} | {len(spec.get('files',[]))} file | "
              f"total {sum(f.get('size',0) for f in spec.get('files',[]))/1e9:.1f} GB")
        for k, v in prof.items():
            print(f"  {k:16} {v.get('label','')}")
        return
    if a.profile not in prof:
        raise SystemExit(f"profil '{a.profile}' tidak ada; pilihan: {', '.join(prof)}")
    graph = prof[a.profile]["graph"]
    for i in range(a.repeat):
        run(a.base, graph, f"{a.profile}#{i+1}")


if __name__ == "__main__":
    main()
