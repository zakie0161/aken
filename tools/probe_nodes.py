import json
import sys
import urllib.request

d = json.load(urllib.request.urlopen("http://127.0.0.1:18188/object_info", timeout=40))
WANT = ["Krea2ImageNode", "ModelMergeKrea2", "Krea2StyleReferenceNode", "LoadImage",
        "MiniMaxMusic3TextEncode", "EmptyMiniMaxMusic3LatentAudio", "SaveAudio",
        "CreateAudio", "VAELoader", "UNETLoader", "CLIPLoader", "KSampler", "VAEDecode",
        "VAEDecodeAudio", "SaveImage"]


def fmt(items):
    out = []
    for k, v in items.items():
        t = v[0]
        if isinstance(t, list):
            t = "CHOICE[" + ",".join(str(x)[:28] for x in t[:10]) + "]"
        out.append(f"{k}:{t}")
    return ", ".join(out)


print("total nodes:", len(d))
for n in WANT:
    if n not in d:
        print(f"\n### {n}: TIDAK ADA")
        continue
    i = d[n].get("input", {})
    print(f"\n### {n}")
    print("   req:", fmt(i.get("required", {}))[:420])
    if i.get("optional"):
        print("   opt:", fmt(i.get("optional", {}))[:300])
    print("   ret:", d[n].get("output"), "|", d[n].get("output_name"))

clip = d.get("CLIPLoader", {}).get("input", {}).get("required", {}).get("type", [[]])[0]
print("\nCLIPLoader types:", [c for c in clip if any(x in c.lower() for x in ("krea", "music", "minimax"))])
print("UNETLoader unet choices:", [c for c in d["UNETLoader"]["input"]["required"]["unet_name"][0]])
print("VAELoader vae choices:", [c for c in d["VAELoader"]["input"]["required"]["vae_name"][0]])
