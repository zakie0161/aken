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
# hash template aktif: lihat `vastai search templates` / notes lokal (hash berubah tiap edit template)
HASH=$(cut -d' ' -f2 /tmp/finaltpl.txt 2>/dev/null || echo <HASH>)

vastai create endpoint --endpoint_name vs-a1 --min_load 0 --min_cold_load 0 \
  --cold_workers 1 --max_workers 1 --target_util 0.9 --cold_mult 2.0 \
  --max_queue_time 900 --target_queue_time 120 --inactivity_timeout 600

vastai create workergroup --template_hash $HASH --endpoint_name vs-a1 --gpu_ram 32 \
  --search_params "num_gpus=1 gpu_name=RTX_5090 compute_cap>=890 disk_space>=250 inet_down>=500 \
    verified=true cuda_max_good>=12.9 storage_cost<=0.2 \
    geolocation in [JP,TW,TH,VN,HK,CN,ID,MY,IN,AE,SA,LK,AU,NZ,CA,MX,AR,CL,ZA,JO,SG]"
```

### Kenapa tiap syarat itu ada (semua terukur 2026-09-08, pool = offer 5090 di allow-list)
| syarat | tanpa | dengan | alasan |
|---|---|---|---|
| `storage_cost<=0.2` | 15 offer, idle 140GB $0.87–2.23/h | **12 offer, idle $0.83–0.93/h** | tarif storage beda 5–7× antar host |
| `storage_cost<=0.15` | | 4 offer, idle $0.62/h | lebih hemat tapi **pool tipis** — risiko starve saat worker daur ulang |
| `compute_cap>=890` | `gpu_ram>=32` meloloskan **Tesla V100 cc7** $0.173/j | | V100 nggak punya FP8/FP4; jalur music saja sudah mati karena CUDA |
| `cuda_max_good>=12.9` | host CUDA 12.9 bikin ComfyUI `driver too old` | | dan **music** tetap butuh ≥13.0 |
| `gpu_name=RTX_5090` | longgar → dapat kartu tak layak | 11–12 offer | satu-satunya kelas yang sudah terbukti ngejalanin H3 |

`--disk_space` template sekarang **140 GB** (bobot 71.5 GB + output + slack). Ini yang menentukan biaya idle,
bukan `disk_space>=250` di search_params (itu syarat kapasitas host, gratis).

Perkiraan biaya idle cold worker sekarang: **±$0.85/hari** (sebelumnya $2.23).

## Filter wilayah (WAJIB - syarat lisensi model)
Lisensi bobot mengecualikan **Uni Eropa, Inggris, Korea Selatan, AS** dari hosting/penjualan
bobot maupun output. Autoscaler Vast merekrut host dari pasar global, jadi wilayah harus
disaring di `search_params`.

Yang **tidak** berfungsi di `search offers`: `geolocation='Japan, JP'` / `Japan_JP` (0 hasil).
Yang berfungsi di `search offers`: `geolocode in [ ... ]` (integer per negara — peta di bawah).
Tapi lihat kotak berikutnya: **untuk workergroup field-nya beda.**

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
→ **43 offer** dengan allow-list; 17 di antaranya RTX 5090. Masih lega.
Tabel integer di atas cuma buat **cross-check** hasil `search offers`, bukan buat `search_params`.

### ⚠️ Field geo yang benar di workergroup: `geolocation`, bukan `geolocode`
Mesin autoscaling **mengabaikan** `geolocode` — nilainya cuma tersimpan di `search_query` tanpa
ditegakkan. Buktinya di sesi ini: worker pertama mendarat di Malaysia (benar), lalu setelah daur
ulang mendarat di `North Carolina, US` — padahal allow-list nggak menyebut US.

Yang ditegakkan: **kode negara 2 huruf** di `geolocation` (SDK meng-hash-nya ke geolocode sendiri).
```bash
vastai create workergroup --template_hash <HASH> --endpoint_name vs-a1 --gpu_ram 32 \
  --search_params "num_gpus=1 gpu_name=RTX_5090 disk_space>=200 inet_down>=500 verified=true \
    geolocation in [JP,TW,TH,VN,HK,CN,ID,MY,IN,AE,SA,LK,AU,NZ,CA,MX,AR,CL,ZA,JO,SG]"
```
`geolocation notin [US,GB,KR,...]` juga jalan, tapi **allow-list lebih aman**: fail-closed, jadi
negara baru yang belum dipetakan nggak akan pernah direkrut.

Verifikasi query sebelum percaya (harus nol US/GB/KR):
```bash
vastai search offers "gpu_name=RTX_5090 num_gpus=1 rentable=true geolocation in [JP,TW,MY]" --raw \
  | python3 -c "import json,sys,collections;d=json.load(sys.stdin);\
print(collections.Counter((x['geolocation'] or '').split(',')[-1].strip() for x in d))"
```
Dan verifikasi **tersimpan** sebagai constraint setelah create:
`vastai show workergroups --raw` → `search_query.geolocation = {'in': [...]}`.

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
