# Setup Vast

Config yang **sudah terbukti jalan** per 2026-09-07 (template dibuat baru tiap perubahan,
bukan di-edit - lihat Catatan):

```bash
RAW=https://raw.githubusercontent.com/zakie0161/aken/main
SPEC=https://huggingface.co/zakie0161/cfg-9f3a/resolve/main/spec.json

vastai create template --name "vs-a1 stack" \
  --image vastai/comfy --image_tag v0.34.0-cuda-13.2-py312 \
  --ssh --direct --disk_space 200 \
  --env "-p 1111:1111 -p 8188:8188 -p 18188:18188 -p 18288:18288 \
 -e OPEN_BUTTON_PORT=1111 -e OPEN_BUTTON_TOKEN=1 \
 -e DATA_DIRECTORY=/workspace/ -e JUPYTER_DIR=/ \
 -e PORTAL_CONFIG=\"localhost:1111:11111:/:Instance Portal|localhost:8188:18188:/:ComfyUI|localhost:8080:18080:/:Jupyter|localhost:18288:18288:/:API Wrapper\" \
 -e COMFYUI_ARGS=\"--disable-auto-launch --port 18188 --enable-cors-header\" \
 -e COMFYUI_API_BASE=http://127.0.0.1:18188 \
 -e PROVISIONING_SCRIPT=$RAW/provisioning/bootstrap.sh \
 -e STACK_SPEC_URL=$SPEC -e STACK_JOBS=3 \
 -e PYWORKER_REPO=https://github.com/vast-ai/pyworker.git -e PYWORKER_REF=main -e BACKEND=comfyui-json" \
  --onstart-cmd "entrypoint.sh" \
  --search_params "num_gpus=1 gpu_ram>=32 disk_space>=200 inet_down>=400 verified=true"
```

`geolocode` dan `reliability2` **tidak dikenali** di `search_params` template (beda sama
`search offers`), jadi filter wilayah dipasang di **workergroup**.

Endpoint + workergroup:
```bash
vastai create endpoint --endpoint_name vs-a1 --min_load 0 --min_cold_load 0 \
  --cold_workers 1 --max_workers 2 --target_util 0.9 --cold_mult 2.0 \
  --max_queue_time 900 --target_queue_time 120 --inactivity_timeout 600
vastai create workergroup --template_hash <HASH> --endpoint_name vs-a1 --gpu_ram 32 \
  --search_params "<sama seperti di atas>"
```

## Filter wilayah (WAJIB - syarat lisensi model)
Lisensi bobot mengecualikan **Uni Eropa, Inggris, Korea Selatan, AS** dari hosting/penjualan
bobot maupun output. Autoscaler Vast merekrut host dari pasar global, jadi wilayah harus
disaring di `search_params`.

Yang **tidak** berfungsi: `geolocation='Japan, JP'` (selalu 0 hasil). Yang berfungsi:
`geolocode in [ ... ]` — integer per negara, stabil, dan gagal-tertutup (kode tak dikenal
tidak direkrut). Peta dari pasar 2026-09-07 (kode = geolocode):

| izinkan | kode |
|---|---|
| JP | 57088895 |
| TW | 2068045917 |
| TH | 1346900269 |
| VN | 1895214017 |
| HK | 779321654 |
| CN | 921675020 |
| ID | 363600034 |
| MY | 1205004086 |
| IN | 770864666 |
| AE | 747483493 |
| SA | 326265466 |
| LK | 1455119194 |
| AU | 147759926 |
| NZ | 1627129335 |
| CA | 513588759 |
| MX | 283984549 |
| AR | 1390031285 |
| CL | 916365300 |
| ZA | 2012258411 |
| JO | 955010269 |

Dikeluarkan (teramati di pasar, jangan dimasukkan): US 433199645 · GB 231987552 · KR 296503878 ·
CZ 1924176688 · DE 584345388 · ES 1626687101 · NL 1668726180 · IT 596270903 · FR 1109525496 ·
PL 334059079 · RO 1196447765 · BG 1588650921 · HU 1337047143 · SK 1511643434 · SI 549006444 ·
EE 1917538214 · FI 835923585 · HR 1644823784 · PT 413466546 · SE 189478972 · BE 492020219 ·
IE 1857412896 · LT 746503989 · DK 1755196624 · plus EEA/EFTA/balkan/kaukasus/anatolia yang
kita keluarkan sebagai sikap konservatif: NO 1365332043 · IS 838430027 · CH 646532966 ·
UA 1783234984 · RS 1379428621 · MK 1565616317 · AM 740302200 · TR 1755869950 · AD 369836420.

Dampak ke pool (2026-09-07, `num_gpus=1 gpu_ram>=32 disk_space>=200`): 164 offer tanpa filter
→ **43 offer** dengan allow-list di atas; 17 di antaranya RTX 5090. Masih lega.
Peta ini harus dicek ulang kalau Vast menambah negara — `search offers` lalu cocokkan
`geolocode` vs `geolocation`.

## Catatan yang bikin pusing kalau kelupaan
- **`PORTAL_CONFIG` wajib menyertakan `API Wrapper`.** Kalau tidak, `api-wrapper.sh` nge-grep
  `/etc/portal.yaml`, nggak nemu, lalu **skip dirinya sendiri** secara senyap:
  `Skipping api-wrapper startup (not in /etc/portal.yaml)`.
- **`COMFYUI_API_BASE` wajib diarah ke 18188.** Default wrapper `127.0.0.1:8188` itu jalur caddy
  yang balas **401** → probe backend gagal → token `BACKENDS_READY` tidak pernah tercetak →
  PyWorker comfyui-json diam selamanya di `model_loading` dan `measured_perf` tetap 0.
  Rantai readiness: PyWorker → api-wrapper:18288 → probe ComfyUI → `BACKENDS_READY` → benchmark.
- **`--onstart-cmd` harus `entrypoint.sh`.** Mengisinya script sendiri = *menggantikan* entrypoint
  image, akibatnya provisioning tidak pernah jalan (gejala: folder model kosong, service "RUNNING"
  tapi tidak ada bobot).
- `vastai update template` rapuh (400 kalau payload tidak lengkap; hash berubah tiap edit) →
  lebih aman `create template` baru lalu `delete template --template-id <lama>`.
- `vastai copy <id>:/berkas ./lokal` gagal di image ini (`rsync: Unknown module`) → pakai SSH.
- `vastai set ssh-key` bisa nyimpen **string path**, bukan isi pubkey → SSH `Permission denied`.
  Cek `vastai show ssh-keys --raw`; benerin `vastai update ssh-key <id> "$(cat ~/.ssh/id_ed25519.pub)"`;
  instance lama tidak ikut key baru.
- `stop instance` tetap menagih storage → selalu `destroy`.
- Bandingkan `inet_down_cost` antar host: 0.0026 vs 0.013 $/GB ≈ beda $0.47 per worker boot.
- Atribusi ke pemilik model tetap harus tampil di layanan (syarat lisensi), meskipun repo ini senyap.
