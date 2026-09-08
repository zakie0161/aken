"""Bangun profil text->image dan text->music, lalu tulis ke spec.

Semua nama class node dan nama file bobot dibaca dari `components` di spec —
repo ini sengaja tidak menyebut produk/model apa pun.

  python3 tools/add_profiles.py            # regenerasi profil di spec.local.json
  python3 tools/add_profiles.py --upload   # + hf upload
"""
import argparse
import json
import subprocess
from pathlib import Path

# Nama file bobot & class node TIDAK ada di sini - keduanya datang dari spec.components
# (spec di-host di URL yang tidak bisa ditebak; lihat notes lokal).
SPEC = Path(__file__).resolve().parent.parent / "stack" / "spec.local.json"


def canvas(aspect, megapixels, multiple=32):
    """Ubah rasio + megapixel jadi WxH kelipatan `multiple`."""
    w_r, h_r = (float(x) for x in aspect.split(":"))
    area = megapixels * 1_000_000
    h = (area / (w_r / h_r)) ** 0.5
    w = h * (w_r / h_r)
    snap = lambda v: max(multiple, round(v / multiple) * multiple)
    return int(snap(w)), int(snap(h))


def t2i_graph(comp, prompt, aspect="16:9", megapixels=1.0, seed=0, steps=8):
    """Rantai text->image standar: unet + clip + vae -> sampler -> simpan."""
    w, h = canvas(aspect, megapixels)
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": comp["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": comp["clip"], "type": comp["clip_type"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": comp["vae"]}},
        "4": {"class_type": comp.get("encode_node", "CLIPTextEncode"), "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": comp.get("latent_node", "EmptyLatentImage"),
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
            "seed": seed, "steps": steps, "cfg": float(comp.get("cfg", 1.0)), "sampler_name": "euler",
            "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": comp.get("decode_node", "VAEDecode"), "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": comp.get("save_node", "SaveImage"),
              "inputs": {"images": ["8", 0], "filename_prefix": "job-image"}},
    }


def t2m_graph(comp, caption, lyrics, seconds=12.0, seed=0, steps=30, cfg=1.7, top_k=50):
    """Rantai text->music: encoder khusus membawa caption + lyrics + durasi."""
    enc = comp["encode_node"]
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": comp["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": comp["clip"], "type": comp["clip_type"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": comp["vae"]}},
        "4": {"class_type": enc, "inputs": {
            "clip": ["2", 0], "caption": caption, "lyrics": lyrics, "seed": seed,
            "max_duration": float(seconds), "cfg_scale": cfg, "top_k": top_k}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": comp["latent_node"], "inputs": {"seconds": float(seconds), "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
            "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
            "denoise": 1.0}},
        "8": {"class_type": comp["decode_node"], "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": comp["save_node"], "inputs": {"audio": ["8", 0], "filename_prefix": "job-music"}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    spec = json.loads(SPEC.read_text())
    comp = spec["components"]

    spec["profiles"]["image-t2i"] = {
        "label": "text->image 16:9 1MP 8-step", "capability": "image",
        "graph": t2i_graph(comp["image"], "<prompt>"), "cost": 25, "output_kind": "image",
        "params": {"prompt": "<prompt>", "aspect": "16:9", "megapixels": 1.0},
    }
    spec["profiles"]["music-t2m"] = {
        "label": "text->music 12s 30-step", "capability": "music",
        "graph": t2m_graph(comp["music"], "<caption>", "<lyrics>"), "cost": 40, "output_kind": "audio",
        "params": {"caption": "<caption>", "lyrics": "<lyrics>", "seconds": 12.0},
    }
    for k, v in spec["profiles"].items():
        v.setdefault("capability", "video")
        v.setdefault("cost", 100)
        v.setdefault("output_kind", "video")
        v.setdefault("params", {})
    spec["capabilities"] = {
        "video": {"profiles": [k for k, v in spec["profiles"].items() if v["capability"] == "video"]},
        "image": {"profiles": ["image-t2i"]}, "music": {"profiles": ["music-t2m"]},
    }
    SPEC.write_text(json.dumps(spec, indent=1) + "\n")
    print(f"spec: {len(spec['profiles'])} profil | {len(spec['files'])} file "
          f"{sum(f['size'] for f in spec['files'])/1e9:.1f} GB")
    for k, v in spec["profiles"].items():
        print(f"   {k:12} {v['capability']:6} cost={v['cost']:4} {v['label']}")
    if a.upload:
        r = subprocess.run(["hf", "upload", "cfg-9f3a", str(SPEC), "spec.json",
                            "--commit-message", "spec: node class names moved into components"],
                           capture_output=True, text=True, timeout=180)
        print((r.stdout or r.stderr).strip()[-140:])


if __name__ == "__main__":
    main()
