"""Bangun + kirim graph Krea2 (T2I) dan MiniMax-Music3 (T2M) ke ComfyUI lokal.
Dipakai buat ukur waktu per kemampuan di worker yang sama.
"""
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18188"

# Krea2ImageNode pakai dynamic combo: `model` adalah NAMA (bukan link UNETLoader),
# dan membawa aspect_ratio / resolution / creativity sendiri. "Krea 2 Medium Turbo"
# = jalur 8-step yang cocok sama bobot krea2_turbo_nvfp4.
KREA = {
    "1": {"class_type": "Krea2ImageNode",
          "inputs": {"prompt": "a weathered lighthouse on a basalt cliff at blue hour, single warm beam, "
                               "wet rock reflections, fine mist, photorealistic, no text",
                     "model": "Krea 2 Medium Turbo", "aspect_ratio": "16:9",
                     "resolution": "1K", "creativity": "medium", "seed": 77}},
    "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "bench-krea"}},
}

MUSIC = {
    "1": {"class_type": "UNETLoader",
          "inputs": {"unet_name": "minimax_music3_dit_int8_convrot.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader",
          "inputs": {"clip_name": "minimax_music3_text_encoder_pruned_int8_convrot.safetensors",
                     "type": "minimax", "device": "default"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_music3_dav.safetensors"}},
    "4": {"class_type": "MiniMaxMusic3TextEncode",
          "inputs": {"clip": ["2", 0],
                     "caption": "dreamy synth-pop, female vocals, 96 bpm, wide reverb, clean master",
                     "lyrics": "[verse]\nneon on the water, I am learning how to stay\n",
                     "seed": 5, "max_duration": 12.0, "cfg_scale": 2.0, "top_k": 50}},
    "5": {"class_type": "EmptyMiniMaxMusic3LatentAudio", "inputs": {"seconds": 12.0, "batch_size": 1}},
    "6": {"class_type": "KSampler",
          "inputs": {"model": ["1", 0], "seed": 5, "steps": 8, "cfg": 2.0, "sampler_name": "euler",
                     "scheduler": "simple", "positive": ["4", 0], "negative": ["4", 0],
                     "latent_image": ["5", 0], "denoise": 1.0}},
    "7": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
    "8": {"class_type": "SaveAudio", "inputs": {"audio": ["7", 0], "filename_prefix": "bench-music"}},
}


def post(graph, label):
    req = urllib.request.Request(f"{BASE}/prompt",
                                 data=json.dumps({"prompt": graph, "client_id": label}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            pid = json.load(r)["prompt_id"]
    except urllib.error.HTTPError as e:
        print(f"{label}: DITOLAK {e.code} {e.read().decode()[:700]}")
        return None
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(2)
        with urllib.request.urlopen(f"{BASE}/history/{pid}", timeout=60) as r:
            h = json.load(r)
        if pid in h:
            st = h[pid].get("status") or {}
            files = [f for o in (h[pid].get("outputs") or {}).values()
                     for f in (o.get("images") or []) + (o.get("gifs") or []) + (o.get("audio") or [])]
            ok = bool(st.get("completed"))
            print(f"{label}: {'OK' if ok else 'GAGAL'} wall={time.time()-t0:.1f}s files={files[:2]}"
                  + ("" if ok else f" status={json.dumps(st)[:500]}"))
            return time.time() - t0
    print(f"{label}: TIMEOUT")
    return None


if __name__ == "__main__":
    which = sys.argv[2] if len(sys.argv) > 2 else "both"
    if which in ("krea", "both"):
        post(KREA, "krea-t2i")
    if which in ("music", "both"):
        post(MUSIC, "music-t2m")
