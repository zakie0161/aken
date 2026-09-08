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

## Jalankan
```bash
cp .env.example .env      # isi VAST_API_KEY, STACK_API_KEY, STACK_ENDPOINT
python3 app.py            # http://127.0.0.1:8090
```
Atau docker: `docker build -t vs-a1-facade . && docker run --env-file .env -p 8090:8090 vs-a1-facade`

```bash
H=localhost:8090; TOK=<STACK_API_KEY>
curl -s $H/health
curl -s -H "Authorization: Bearer $TOK" $H/capabilities
curl -s -XPOST $H/mode -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
     -d '{"capability":"image","warm":true}'
curl -s -XPOST $H/job   -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
     -d '{"capability":"image","params":{"prompt":"a red bicycle by a white wall, noon, no text"}}'
```
Rute: `POST /job` (satu-satunya pintu kerja) · `POST/GET /mode` · `GET /capabilities` ·
`GET /job/{id}` · `GET /health` (tanpa token, liveness). Semua berbayar butuh bearer token;
kalau `STACK_API_KEY` kosong auth mati - hanya boleh localhost. Dibuka ke jaringan wajib TLS.

### Angka terukur (1x RTX 5090; worker ter-park lalu dibangunkan)
| kapabilitas | bangun/ganti mode | job | keluaran |
|---|---|---|---|
| image | 50.7 s | 10.9 s | PNG 16:9 1 MP |
| music | 25.3 s (swap) | 21.1 s | FLAC, loudness sudah normal |
| video | 78.2 s (swap) | 62.4 s | MP4 960x544 5.2 dtk + audio |

Build terverifikasi: image 761 MB, container jalan, auth 401/200 sesuai.
