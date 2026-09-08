"""Tambahkan profil T2I (Krea turbo) dan T2M (MiniMax Music 3) ke spec.

Graph-nya dirakit dari signature node yang sudah diverifikasi lewat /object_info
di worker (lihat notes), jadi tidak perlu menyalakan mesin untuk membangkitkannya.

  python3 tools/add_profiles.py            # tulis ke spec.local.json
  python3 tools/add_profiles.py --upload   # + hf upload
"""
import argparse
import json
import subprocess
from pathlib import Path

# Nama file bobot TIDAK ada di repo ini - semuanya dibaca dari `components` di spec
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


def krea_graph(comp, prompt, aspect="16:9", megapixels=1.0, seed=0, steps=8):
    w, h = canvas(aspect, megapixels)
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": comp["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": comp["clip"], "type": comp["clip_type"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": comp["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
            "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
            "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 1], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "job-image"}},
    }


def music_graph(comp, caption, lyrics, seconds=12.0, seed=0, steps=30, cfg=1.7, top_k=50):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": comp["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": comp["clip"], "type": comp["clip_type"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": comp["vae"]}},
        "4": {"class_type": "MiniMaxMusic3TextEncode", "inputs": {
            "clip": ["2", 0], "caption": caption, "lyrics": lyrics, "seed": seed,
            "max_duration": float(seconds), "cfg_scale": cfg, "top_k": top_k}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyMiniMaxMusic3LatentAudio", "inputs": {"seconds": float(seconds), "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
            "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
            "denoise": 1.0}},
        "8": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["7", 1], "vae": ["3", 0]}},
        "9": {"class_type": "SaveAudio", "inputs": {"audio": ["8", 0], "filename_prefix": "job-music"}},
    }


PROMPT = json.loads  # alias biar terbaca jelas di bawah


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    spec = json.loads(SPEC.read_text())
    comp = spec["components"]

    spec["profiles"]["image-t2i"] = {
        "label": "text->image 16:9 1MP 8-step",
        "capability": "image",
        "graph": krea_graph(comp["image"], "<prompt>"),
        "cost": 25,
        "output_kind": "image",
        "params": {"prompt": "<prompt>", "aspect": "16:9", "megapixels": 1.0},
    }
    spec["profiles"]["music-t2m"] = {
        "label": "text->music 12s 30-step",
        "capability": "music",
        "graph": music_graph(comp["music"], "<caption>", "<lyrics>"),
        "cost": 40,
        "output_kind": "audio",
        "params": {"caption": "<caption>", "lyrics": "<lyrics>", "seconds": 12.0},
    }
    # tandai profil video yang sudah ada
    for k, v in spec["profiles"].items():
        v.setdefault("capability", "video")
        v.setdefault("cost", 100)
        v.setdefault("output_kind", "video")
        v.setdefault("params", {})
    spec["capabilities"] = {
        "video": {"profiles": [k for k, v in spec["profiles"].items() if v["capability"] == "video"]},
        "image": {"profiles": ["image-t2i"]},
        "music": {"profiles": ["music-t2m"]},
    }
    SPEC.write_text(json.dumps(spec, indent=1) + "\n")
    print(f"spec: {len(spec['profiles'])} profil | {len(spec['files'])} file "
          f"{sum(f['size'] for f in spec['files'])/1e9:.1f} GB")
    for k, v in spec["profiles"].items():
        print(f"   {k:14} {v['capability']:6} cost={v['cost']:4} {v['label']}")
    if a.upload:
        r = subprocess.run(["hf", "upload", "cfg-9f3a", str(SPEC), "spec.json",
                            "--commit-message", "spec: +image/music profiles +capabilities"],
                           capture_output=True, text=True, timeout=180)
        print((r.stdout or r.stderr).strip()[-160:])


if __name__ == "__main__":
    main()
