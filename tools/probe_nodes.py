"""Cetak signature node ComfyUI dari /object_info.

Node mana yang mau dilihat diambil dari argumen atau dari spec (biar repo ini
nggak perlu menyebut model apa pun).

  python3 tools/probe_nodes.py --base http://127.0.0.1:18188 --spec <spec-url-atau-file>
  python3 tools/probe_nodes.py --nodes Foo,Bar
"""
import argparse
import json
import urllib.request


def load_spec(src):
    if src.startswith("http"):
        with urllib.request.urlopen(src, timeout=60) as r:
            return json.load(r)
    with open(src) as f:
        return json.load(f)


def names_from_spec(spec):
    out = set()
    for prof in (spec.get("profiles") or {}).values():
        for node in (prof.get("graph") or {}).values():
            if isinstance(node, dict) and node.get("class_type"):
                out.add(node["class_type"])
    for node in (spec.get("benchmark") or {}).values():
        if isinstance(node, dict) and node.get("class_type"):
            out.add(node["class_type"])
    return sorted(out)


def fmt(items):
    parts = []
    for k, v in (items or {}).items():
        t = v[0]
        if isinstance(t, list):
            t = "CHOICE[" + ",".join(str(x)[:24] for x in t[:8]) + "]"
        parts.append(f"{k}:{t}")
    return ", ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:18188")
    ap.add_argument("--spec")
    ap.add_argument("--nodes", help="pisahkan dengan koma")
    a = ap.parse_args()

    if a.nodes:
        want = [n for n in a.nodes.split(",") if n]
    elif a.spec:
        want = names_from_spec(load_spec(a.spec))
        print(f"dari spec: {len(want)} class_type")
    else:
        raise SystemExit("butuh --nodes atau --spec")

    with urllib.request.urlopen(f"{a.base}/object_info", timeout=60) as r:
        info = json.load(r)
    print("total node terdaftar:", len(info))
    for n in want:
        if n not in info:
            print(f"\n### {n}: TIDAK ADA (butuh custom node / versi ComfyUI lebih baru)")
            continue
        inp = info[n].get("input", {})
        print(f"\n### {n}")
        print("   req:", fmt(inp.get("required"))[:400])
        if inp.get("optional"):
            print("   opt:", fmt(inp.get("optional"))[:260])
        print("   ret:", info[n].get("output"), "|", info[n].get("output_name"))


if __name__ == "__main__":
    main()
