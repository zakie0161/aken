# aken

Bootstrap generik buat worker ComfyUI serverless di Vast.ai: satu spec JSON (ditunjuk
lewat env) menentukan bobot yang diunduh, graph benchmark, dan profil kerja.
**Tidak ada kredensial maupun identitas model di repo ini** - semuanya di spec.

```
provisioning/bootstrap.sh   PROVISIONING_SCRIPT: unduh files[] dari spec, cek byte-size, tulis graph
onstart/worker.sh           onstart: pasang PyWorker + tukar benchmark.json dari spec
tools/stackctl.py           klien: --list / --profile X --local URL | --endpoint NAMA
stack/spec.example.json     bentuk spec (nilai placeholder)
docs/VAST-SETUP.md          perintah vastai + catatan kepatuhan wilayah
```

## Alur
1. Taruh spec aslimu di URL publik tanpa auth (gist = URL acak, isinya bukan rahasia).
2. Set env template: `STACK_SPEC_URL=https://gist.githubusercontent.com/.../spec.json`
3. Worker boot → `bootstrap.sh` sedot `files[]` → `worker.sh` pasang PyWorker + benchmark → engine siap.

```bash
python3 tools/stackctl.py --spec stack/spec.example.json --list
python3 tools/stackctl.py --spec <spec> --profile <nama> --local http://127.0.0.1:18188
```
