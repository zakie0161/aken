# aken

Bootstrap generik buat worker ComfyUI serverless di Vast.ai: satu spec JSON (ditunjuk
lewat env) menentukan bobot yang diunduh, graph benchmark, dan profil kerja.
**Tidak ada kredensial maupun identitas model di repo ini** - semuanya di spec.

```
provisioning/bootstrap.sh   PROVISIONING_SCRIPT: unduh files[] dari spec, cek byte-size,
                            pasang PyWorker + tulis benchmark.json ke tree-nya
tools/stackctl.py           klien: --list / --profile X --local URL | --endpoint NAMA
stack/spec.example.json     bentuk spec (nilai placeholder)
docs/VAST-SETUP.md          perintah vastai + catatan kepatuhan wilayah
```

## Alur
1. Taruh spec aslimu di URL publik tanpa auth (repo HF bernama netral, atau gist).
2. Env template: `STACK_SPEC_URL=<url spec>` + `PROVISIONING_SCRIPT=<url bootstrap.sh>`,
   dan **`--onstart-cmd entrypoint.sh`** — jangan diganti, kalau diganti provisioning tidak jalan.
3. Worker boot: `entrypoint.sh` → provisioning unduh bobot + pasang PyWorker/benchmark →
   ComfyUI start → api-wrapper start → `BACKENDS_READY` → PyWorker benchmark → siap melayani.

Rantai readiness harus utuh (putus satu = worker diam di `model_loading`):
`PORTAL_CONFIG` memuat `API Wrapper` → api-wrapper hidup di 18288 → `COMFYUI_API_BASE`
menunjuk 18188 (bukan 8188 yang kena 401 caddy) → `BACKENDS_READY` tercetak → benchmark jalan.

```bash
python3 tools/stackctl.py --spec stack/spec.example.json --list
python3 tools/stackctl.py --spec <spec> --profile <nama> --local http://127.0.0.1:18188
```

## Façade lokal (satu titik masuk, satu kapabilitas aktif)
```bash
pip install -r requirements.txt
cd tools && uvicorn facade:app --port 8090
curl -s localhost:8090/capabilities
curl -s -XPOST localhost:8090/mode -d '{"capability":"image","warm":true}' -H 'content-type: application/json'
curl -s -XPOST localhost:8090/job   -d '{"capability":"image","params":{"prompt":"...","aspect":"16:9"}}' -H 'content-type: application/json'
```
`POST /job {capability: video|image|music}` — satu-satunya titik masuk. Mutex mode ada di façade,
jadi **sisi server wajib `max_workers=1`** kalau tidak, dua worker bisa memegang model berbeda.
Output audio dilewatkan `loudnorm` (temuan QC: peak mentok 0 dBFS).
