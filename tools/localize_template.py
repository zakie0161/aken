"""Ambil workflow template resmi ComfyUI (format UI) lalu ubah jadi graph API
lewat route /workflow/convert yang disediakan image, dengan penyesuaian generik:
  - ganti nilai input apa pun (kunci=nilai)
  - buang node berdasarkan class_type (mis. LoRA yang filenya tidak kita unduh)
  - paksa semua node switch ke cabang false (cabang "tanpa prompt-rewrite")

Hasilnya dicetak ke stdout sebagai JSON graph API, siap masuk spec.profiles.

  python3 tools/localize_template.py --base http://127.0.0.1:18188 \
      --template <nama-template> --drop LoraLoaderModelOnly --switch-off \
      --set unet_name=<file.yg.kita.punya>
"""
import argparse
import json
import sys
import urllib.request

REPO = "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/{}.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:18188")
    ap.add_argument("--template", required=True, help="nama file template tanpa .json")
    ap.add_argument("--set", action="append", default=[], metavar="K=V")
    ap.add_argument("--drop", action="append", default=[], metavar="CLASS_TYPE")
    ap.add_argument("--switch-off", action="store_true")
    ap.add_argument("--out", help="tuliss ke file (default stdout)")
    a = ap.parse_args()

    ui = json.load(urllib.request.urlopen(REPO.format(a.template), timeout=60))
    req = urllib.request.Request(f"{a.base}/workflow/convert",
                                 data=json.dumps(ui).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"convert gagal {e.code}: {e.read().decode()[:300]}")
    g = out.get("prompt") or out

    patches = {}
    for kv in a.set:
        k, _, v = kv.partition("=")
        patches[k] = v
    for v in g.values():
        inp = v.get("inputs") or {}
        for k in patches:
            if k in inp:
                inp[k] = patches[k]
        if a.switch_off and v.get("class_type") == "ComfySwitchNode":
            inp["switch"] = False

    for ct in a.drop:
        doomed = [k for k, v in g.items() if v.get("class_type") == ct]
        for k in doomed:
            for other in g.values():
                inp = other.get("inputs") or {}
                for name, val in list(inp.items()):
                    if isinstance(val, list) and val and val[0] == k:
                        src = g[k].get("inputs") or {}
                        first_link = next((v2 for v2 in src.values() if isinstance(v2, list)), None)
                        inp[name] = first_link if first_link else val
            for k2 in doomed:
                g.pop(k2, None)

    txt = json.dumps(g, indent=1)
    if a.out:
        open(a.out, "w").write(txt + "\n")
        print(f"{len(g)} node -> {a.out}", file=sys.stderr)
    else:
        print(txt)


if __name__ == "__main__":
    main()
