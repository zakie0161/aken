# Setup Vast

Konfigurasi yang **terbukti jalan** per 2026-09-10 (template selalu dibuat baru, tidak diedit
- lihat Catatan). Topologinya **satu endpoint per kapabilitas** - dan itu bukan selera, itu
paksaan arsitektur Vast (lihat "perutean" di bawah):

```
vs-a1   endpoint 36613 | workergroup 46456 | template 717951  STACK_ONLY=music  TER-PIN, melayani musik
vs-i1   (belum ada endpoint - tergerbang kredit, lihat di bawah)
vs-v1   (belum ada endpoint)
```

## Perutean: kapabilitas TIDAK BISA dipisah lewat workergroup dalam satu endpoint
Ini salah paham yang mahal, dan salahku sendiri. Bukti dari dua arah:

1. **Permukaan API.** Body `/route/` (satu-satunya panggilan penentu worker) hanya berisi
   `endpoint, api_key, cost, request_idx, replay_timeout` - **tidak** ada `template_id` /
   `template_hash`. SDK juga tidak memilih grup di sisi klien (`_route` -> `refresh` -> selesai).
   Jadi autoscaler *tidak mungkin* tahu sebuah request itu musik, image, atau video.
2. **Dokumen Vast sendiri**: "Multiple Workergroups can exist within a single Endpoint...
   Advanced use cases such as **mixed-model serving** ... please **contact Vast** for
   assistance", dan artikelnya menjelaskan grup berbeda itu untuk **jenis GPU berbeda**,
   dilayani "whichever Workergroup is most cost-effective".

Konsekuensinya keras: kalau satu endpoint menaungi grup musik + grup image, request musik bisa
dijawab worker image yang ComfyUI-nya tidak punya node musik - gagal, setelah kita membayar
unduh 13 GB. Yang boleh berbagi endpoint hanyalah grup dengan **template identik** (bedanya
pool hardware/kelas GPU). Irisan bobot per kapabilitas = endpoint berbeda. Grup lama `46116`
(stack penuh, 71,5 GB terunduh) dihapus pemiliknya 2026-09-10, dan itu bukan kerugian: worker
stack-penuh butuh ±33 menit unduh (71,5 GB @ ±36 MB/s) sementara `model_loading` Vast pernah
kelihatan dibunuh setelah ±900-1200 dtk - jadi cold start stack-penuh **tidak akan pernah siap**.
Satu grup untuk semua hanya sah bila workernya diparkir permanen, dan 71,5 GB parkir = ±$14/bln.

## Kenapa dipisah per kapabilitas (terukur 2026-09-09)
| | satu grup untuk semua | endpoint per kapabilitas |
|---|---|---|
| unduh worker baru | 71,5 GB = **12-22 menit** | musik 11,9 GB = **2 mnt 50 dtk** (terbukti) |
| kelas GPU | dipaksa >=32 GB Blackwell | musik cukup 16 GB cc>=8.9 -> **24 host di zona lisensi**, median **$0,224/jam** vs 5090 $0,868 |
| ganti kapabilitas | worker harus memuat bobot lain (5-90 dtk) | tidak ada - endpoint berbeda |

Yang TIDAK bisa diturunkan kelasnya: bobot video & image memakai format **NVFP4** (butuh tensor
core Blackwell, `compute_cap>=1200`) dan video menyentuh **peak VRAM 31,95 GB** (terukur). Jadi
fallback GPU murah hanya sah untuk musik.

### Gerbang kredit saat `create endpoint` - aturannya sudah terkodekan (terukur 2026-09-10)
```
403: error: insufficient credit $7.49. You need an additional $2.51 to create endpoint # 2.
403: error: insufficient credit $10.32. You need an additional $4.68      <- saat endpoint #3
```
Aturannya **bukan** harga offer termahal (dugaanku kemarin, salah - dua datapoin membantahnya):
saldo minimum = **$5 x jumlah endpoint sesudah dibuat**. Endpoint #2 minta $10,00 tepat
($7,49 + $2,51), endpoint #3 minta $15,00 tepat ($10,32 + $4,68). `create endpoint` juga
**tidak punya** flag query/harga - jadi cadangan ini tidak bisa dikecilkan dengan memperketat
filter; satu-satunya tuas adalah saldo. Kerja berurutan yang benar: endpoint musik dulu (sudah
ada), lalu image ($10), lalu video ($15).

### Filter yang benar-benar diterima `workergroup --search_params`
`geolocation in [...]` **bekerja**; `reliability2>=0.99` **bekerja** di workergroup (keduanya
ditolak di `search_params` *template*). Verifikasi selalu dengan `vastai show workergroups --raw`
lalu baca `search_query` - jangan berasumsi filtermu masuk.

Dua hal yang membuat filter kita **tidak pernah mendarat** sampai 2026-09-11 siang:
1. `vastai update workergroup <id> --search_params "..."` menjawab `Failed with error 400: error:
   Missing endpoint ID` kalau `--endpoint_id` tidak ikut diserahkan. Kegagalannya senyap di
   skrip yang hanya melihat exit code pipeline, jadi catatan "sudah dipasang" bisa salah selama
   berminggu-minggu sementara server hidup dengan **tanpa filter apa pun**.
2. Karena itu satu-satunya pembatas yang benar-benar aktif adalah yang terbaca di server. Baca
   balik selalu: `vastai show workergroups --raw | grep -A20 46456`.

Kondisi aktif sekarang (grup musik 46456, terbaca balik dari server):
```
direct_port_count>0  disk_space>=40  dph_total<=0.30  gpu_ram>=16  num_gpus=1
inet_down_cost<=0.005  rentable  rented=false  verified
```
`inet_down_cost` adalah **harga bandwidth masuk per GB** dan ia sah di workergroup maupun
`search offers` - field yang tampak mirip, `internet_down_cost_per_tb`, **tidak** bisa difilter
(selalu 0 offer). Kenapa penting: tagihan asliku menunjukkan tarif yang muncul $0,001-$0,042/GB
untuk pekerjaan yang sama, dan `bwd` adalah 39% dari seluruh belanja endpoint (973,8 GB = $4,57
dari $11,61). Satu-satunya cara memilih harga itu adalah filter ini. `disk_space>=40` menjaga agar
host yang tidak muat menampung image + bobot tidak direkrut sama sekali; `direct_port_count>0`
menjaga host yang port-nya tidak bisa dicapai tidak direkrut.

### ⚠️ Benchmark worker: jangan sodorkan graph bobot penuh (akar "unavailable" yang sesungguhnya)
Terukur 2026-09-11, worker 50486887. Log container worker:

```
11:50:51 Queued synchronous request test-38661        <- probe benchmark dari autoscaler
         ComfyUI ready after 0.0s -> Submitted -> WebSocket connected
         Model ...TEModel prepared for dynamic VRAM loading. 8758MB Staged
11:50:53 Worker Status: max_perf=0.0 cur_perf=0        <- belum selesai, belum dinilai
(autoslacer) error message: No successful responses from benchmark -> rebooting
```

Jendela probe-nya **±11 detik** antara `model_loading (first load)` dan vonis. Vast mengulang
reboot tiap ±50 detik tanpa henti. Selama worker terjebak di sini endpoint tidak punya siapa-siapa,
gejala di sisi klien: `no workers available` - persis keluhan yang dok `quickstart#troubleshooting`
jawab dengan "cek VRAM / nama model / HF_TOKEN". Untuk kasus kami ketiganya tidak bersalah:
yang bersalah adalah **kami sendiri**, karena `bootstrap.sh` memasang graph kapabilitas (yang harus
memuat bobot belasan GB ke VRAM) sebagai `benchmark.json`. Tidak ada graph bobot penuh yang bisa
lulus 11 detik, di host mana pun, selamanya.

Aturan sekarang:
1. **Worker memakai benchmark bawaan image** (SD1.5, hitungan detik). `bootstrap.sh` tidak
   memasang `benchmark.json` lagi secara diam-diam, dan menghapus sisa lama di disk worker.
2. `STACK_BENCH=spec|slice` mengembalikan perilaku lama kalau suatu hari jendela probe Vast
   melebar atau kita benar-benar butuh `measured_perf` yang representatif. Defaultnya aman.
3. Konsekuensi yang diterima sadar: `measured_perf` diukur dari SD1.5, jadi terlalu optimis untuk
   bobot kita. Karena `min_load=0` dan `max_workers` kecil, autoscaler tidak pakai angka itu untuk
   menahan kapasitas kita; yang perlu dijaga justru `target_util`/`max_queue_time`.
4. Kalau muncul `No successful responses from benchmark` di `get wrkgrp-logs`: **jangan** perbesar
   `BENCHMARK_TEST_STEPS` (itu memperpanjang, bukan memperpendek) - pastikan worker jatuh ke
   benchmark bawaan image.

## ⚠️ Vast mengenali "worker siap" dari BARIS LOG - jangan pernah pakai tag image melayang
Terukur 2026-09-10. Dari log autoscaler sendiri:

```
[DEBUG] Got log line indicating model is loaded: INFO:main:BACKENDS_READY: 1 backend(s) ready to serve
```

Kesiapan worker adalah **pencocokan teks log**, bukan health check. Hari itu Vast mempush image
ComfyUI versi baru; template yang berte-tag `@vastai-automatic-tag` (= "selalu tag terbaru")
langsung memakainya, format log berubah, pencocok tidak pernah kena - worker **selamanya**
`model_loading` dan endpoint hanya mengulang `failed to find rdy worker`. Tanpa error, tanpa
/tagihan berarti, tanpa knob yang memperbaiki. Lima host berbeda gagal persis sama.

Aturan yang berlaku sekarang:
1. **Pin tag image** (`--image_tag v0.34.0-cuda-12.9-py312`). Jangan `@vastai-automatic-tag`.
   Upgrade image harus jadi keputusan kita, bukan kejutan di tengah produksi.
2. **`--disk` wajib**, dan ia hanya ada di dalam `--launch_args`: `--launch_args "--disk 24"`.
   Tanpa reservasi disk provisioning berhenti diam-diam: `model_loading` selamanya dengan
   **nol byte terunduh** (kredit flat, `disk_usage 0`). Ini bukan kegagalan host - ini konfigurasi.
3. **`dph_total<=X` wajib.** Serverless tidak punya knob harga; query workergroup satu-satunya
   tempat harga bisa dibatasi. Musik: `dph_total<=0.30` tetap 57-64 host (median $0,171/jam);
   tanpanya aku membayar host ~$1/jam untuk kerja yang sama. Kunci yang diterima `dph_total`;
   `price` / `max_price` / `reliability2` **tidak** dikenal `search offers`.
4. Jangan lewat query lewat shell tanpa kutip: `>=` adalah **redirect**, filtermu hilang tanpa
   suara dan tampak seperti "0 offer".

### Cold path terukur, setelah ketiganya benar
| fase | waktu | bytes |
|---|---|---|
| rekrut host | 12 dtk | - |
| tarik image (host sudah ber-cache) | ±90 dtk | - |
| tarik image (host kosong) | 212 dtk | 8,2 GB @ 38,7 MB/s |
| unduh satu irisan bobot | ±4 menit | 11,9 GB @ ±36 MB/s |
| **worker `ready`** | **403 dtk** | seluruhnya **$0,04** |

Vast menyerah di ±300 dtk pada fase `creating` dan ±1200 dtk total, jadi provisioning harus muat
di dalamnya - itulah alasan sesungguhnya untuk irisan per kapabilitas (`STACK_ONLY`), bukan
sekadar hemat bandwidth. Registry Vast dan Hugging Face ternyata secepat-sama (38,7 vs 36 MB/s),
jadi membake bobot ke image sendiri **tidak menghemat waktu**.

> Koreksi 2026-09-11: yang tidak kuhitung waktu itu adalah **siapa yang ditagih**. `show
> invoices-v1 -f tree -v` memecah tagihan menjadi `gpu / disk / bwd / bwu`, dan GB pada baris
> `bwd` selalu sama persis dengan bobot yang kuunduh sendiri (25,3 vs 25,1; 13,3 vs 13,2) -
> image ComfyUI ±18 GB yang di-`docker pull` **tidak pernah masuk tagihan**. Kesimpulan "bake"
> tidak menghemat apa pun masih benar untuk *kecepatan*, tapi untuk *biaya* ia menghapus baris
> `bwd` seluruhnya. Jalur `vastai take snapshot` tetap mati (bukti di notes), jadi jalurnya
> build-di-VM-Vast -> push registry, dan itu belum diuji.

### Volume vs instance diparkir — terukur 2026-09-10 di host nyata
Vast punya *volume*, tapi volumenya **terikat fisik ke satu mesin** (docs: "can only be attached
to instances running on the same physical machine"), dan pasar storage lintas-host
(`search network-volumes`) kosong. Jadi volume tidak menyelamatkan kita dari unduh ulang ketika
worker berpindah host. Yang menyelamatkan adalah hal lain: **storage container instance yang
di-`stop` juga bertahan** — dan itu jauh lebih murah daripada kelihatannya:

| kejadian | terukur di RTX PRO 4000 ($0,2185/jam) |
|---|---|
| unduh irisan image 13,2 GB (sekali, host baru) | 175 dtk = **75 MB/s** |
| bootstrap ulang di disk yang sama | **4,5 dtk** (semua `skip`) |
| `stop instance` → `start instance` | **12 dtk → 12 dtk**, host sama, bobot utuh |
| render image 1344×736 8 steps | **31,85 dtk**, VRAM 12,3 GiB |
| biaya seluruh rangkaian tes | **$0,188** |

Rumusnya: parkir = `GB × storage_cost × 720 jam`. Di host contoh ($0,333/GB-bulan) itu $4,33/bulan
untuk 13,2 GB dan $10-14/bulan untuk 44,4 GB, sementara unduh ulang cuma $0,17. **Kesimpulan:**
irisan kecil (≤15 GB) lebih baik dingin; irisan besar (≥40 GB) lebih baik diparkir, karena unduhnya
sendiri tidak muat di tenggat `model_loading` Vast. Sewa instance 24/7 tidak pernah masuk akal:
$0,20/jam = $144/bulan.

Catatan penting untuk mode instance biasa: ComfyUI image Vast berada di
`/opt/workspace-internal/ComfyUI` dengan venv `/venv/main` (bukan `/workspace/ComfyUI` seperti di
worker serverless - gerbangnya env `SERVERLESS`), dan image sudah menjalankan ComfyUI lewat
supervisor. Image itu juga membawa `/opt/comfyui-api-wrapper` yang melayani **`/generate/sync`**,
rute yang sama dengan yang dipakai worker - jadi memanggil instance langsung tidak memerlukan
klien baru, hanya URL + SSH tunnel.

### Gotcha graph: index output link
Link input di graph API berbentuk `[id_node, index_output]`. Node dengan satu output
(mis. `KSampler`) **hanya** punya index 0; menulis index 1 membuat ComfyUI menolak seluruh graph
dengan `Exception when validating inner node: tuple index out of range` - pesan yang sama sekali
tidak menyebut node yang salah, dan mudah disalahartikan sebagai kegagalan GPU/worker. Node
bermulti-output (`SamplerCustomAdvanced`: MODEL di 0, LATENT di 1) memang butuh index 1. Selalu
validasi graph ke `/prompt` sekali sebelum sebuah profil dimasukkan ke spec.

### Watchdog readiness di API
`higgsgen-api` mengambil snapshot worker tiap 30 dtk (dipantik dari `/health`, bukan dari
startup hook - lihat komentar `_ensure_watchdog`) dan menyoraki worker yang terjebak
`creating/loading/model_loading` lebih dari `HIGGSGEN_WORKER_STALL=480` dtk. Gejala insiden ini
tadinya cuma "request menggantung sampai timeout"; sekarang jadi satu baris peringatan di log
plus `workers` yang jujur di `/api/health`.

```bash
RAW=https://raw.githubusercontent.com/zakie0161/aken/main
SPEC=https://huggingface.co/zakie0161/cfg-9f3a/resolve/main/spec.json

vastai create template --name "vs-a1 stack" \
  --image vastai/comfy --image_tag @vastai-automatic-tag \
  --ssh --direct --disk_space 100 \
  --env "-p 1111:1111 -p 8188:8188 -p 18188:18188 -p 18288:18288 \
 -e OPEN_BUTTON_PORT=1111 -e OPEN_BUTTON_TOKEN=1 \
 -e DATA_DIRECTORY=/workspace/ -e JUPYTER_DIR=/ \
 -e PORTAL_CONFIG=\"localhost:1111:11111:/:Instance Portal|localhost:8188:18188:/:ComfyUI|localhost:8080:18080:/:Jupyter|localhost:18288:18288:/:API Wrapper\" \
 -e COMFYUI_ARGS=\"--disable-auto-launch --port 18188 --enable-cors-header\" \
 -e COMFYUI_API_BASE=http://127.0.0.1:18188 \
 -e PROVISIONING_SCRIPT=$RAW/provisioning/bootstrap.sh \
 -e STACK_SPEC_URL=$SPEC -e STACK_JOBS=4 \
 -e PYWORKER_REPO=https://github.com/vast-ai/pyworker.git -e PYWORKER_REF=main -e BACKEND=comfyui-json" \
  --onstart-cmd "entrypoint.sh" \
  --search_params "num_gpus=1 gpu_ram>=32 disk_space>=110 cpu_ram>=48 disk_bw>=1200 storage_cost<=0.20 inet_down>=500 verified=true cuda_max_good>=13.0 geolocation in [JP,TW,TH,VN,HK,CN,ID,MY,IN,AE,SA,LK,AU,NZ,CA,MX,AR,CL,ZA,JO,SG]"
```

`geolocode` dan `reliability2` **tidak dikenali** di `search_params` template (beda sama
`search offers`), jadi filter wilayah dipasang di **workergroup**.

`storage_cost` (USD/GB/bulan) **bisa** dan sebaiknya dipakai: ia mengubah tarif penyimpanan yang
dicadangkan worker. Tapi jangan tertipu — bagian terbesar biaya idle itu **GPU-nya**, bukan storage:
lihat tabel "Biaya idle sungguhnya" di bawah.

Endpoint + workergroup:
```bash
# hash template aktif: lihat `vastai search templates` / notes lokal (hash berubah tiap edit template)
HASH=$(cut -d' ' -f2 /tmp/finaltpl.txt 2>/dev/null || echo <HASH>)

vastai create endpoint --endpoint_name vs-a1 --min_load 0 --min_cold_load 0 \
  --cold_workers 1 --max_workers 1 --target_util 0.9 --cold_mult 2.0 \
  --max_queue_time 900 --target_queue_time 120 --inactivity_timeout 600

vastai create workergroup --template_hash $HASH --endpoint_name vs-a1 --gpu_ram 32 \
  --search_params "num_gpus=1 gpu_name=RTX_5090 compute_cap>=890 disk_space>=110 cpu_ram>=48 \
    disk_bw>=1200 storage_cost<=0.20 inet_down>=500 verified=true cuda_max_good>=13.0 \
    geolocation in [JP,TW,TH,VN,HK,CN,ID,MY,IN,AE,SA,LK,AU,NZ,CA,MX,AR,CL,ZA,JO,SG]"
```

### Kenapa tiap syarat itu ada (semua terukur 2026-09-08, pool = offer 5090 di allow-list)
| syarat | tanpa | dengan | alasan |
|---|---|---|---|
| `storage_cost<=0.20` | 17 offer, median $0.47/h | **9 offer**, termurah $0.41/h | tarif storage beda sampai **5×** antar host |
| `storage_cost<=0.10` | | **0 offer (2026-09-08)** | pernah dipakai di template — query ini yang bikin worker **tidak bisa terekrut sama sekali** (1 offer kalau filter wilayah dilepas). Jangan diulang. |
| `compute_cap>=890` | `gpu_ram>=32` meloloskan **Tesla V100 cc7** $0.173/j | | V100 nggak punya FP8/FP4; jalur music saja sudah mati karena CUDA |
| `cuda_max_good>=12.9` | host CUDA 12.9 bikin ComfyUI `driver too old` | | dan **music** tetap butuh ≥13.0 |
| `gpu_name=RTX_5090` | longgar → dapat kartu tak layak | 11–12 offer | satu-satunya kelas yang terbukti memuat bobot terbesar di spec |

`--disk_space` template sekarang **100 GB** (sebelumnya 140). Yang ditagih Vast adalah **disk yang dicadangkan**
(`--disk_space`), bukan pemakaian nyata; `disk_space>=110` di search_params cuma syarat kapasitas host.
Simpanan dari 140→100 GB: ±$0.011/jam worker hidup ($0.20/GB/bln).

### Berapa besar storage sebenarnya (terukur 2026-09-08, pool 5090 dalam allow-list)
| reservasi | tarif storage median | per jam worker | per hari (24 j)
|---|---|---|---|
| 140 GB | $0.33/GB/bln | $0.051 | $1.53 |
| **100 GB (aktif)** | $0.28/GB/bln | $0.028 | $0.83 |
| 40 GB (bobot image saja) | $0.20/GB/bln | $0.011 | $0.32 |

`dph_total` median pool ini **$0.47/jam** → jadi storage itu **±6%** dari biaya worker. Output generasi
(1,6–6 MB) dihapus atau tidak di worker = tidak terasa secara uang; yang membuat disk penuh itu
*bobot*, dan bobot tidak tinggal permanen di Vast (volume & snapshot tidak tersedia untuk kita —
lihat notes/STORAGE.md). Setiap cold start men-download lagi dari nol.

Ukuran bobot per kapabilitas (spec 12 file / 71,5 GB):

| kapabilitas | bobot | cukup disk |
|---|---|---|
| video | 46,4 GB | ~71 GB |
| image | 13,2 GB | ~38 GB |
| music | 11,9 GB | ~36 GB |
| **semua (sekarang)** | **71,5 GB** | 100 GB |

Kalau worker hanya menarik bobot kapabilitas aktif (`STACK_ONLY` di `provisioning/bootstrap.sh` —
sudah dipasang), disk bisa turun ke ~40 GB **dan** cold wake jauh lebih cepat: 13 GB vs 71,5 GB unduhan.

### Biaya idle yang sungguhnya (terukur 2026-09-08, kredit dibaca tiap 30 detik)
| kondisi worker | tagihan nyata | sebab |
|---|---|---|
| `idle` dengan `cold_workers=1` | **$0.507/jam = $12/hari** | GPU + disk dicadangkan, worker hidup terus |
| `stopped`, bobot masih di disk (`cold_workers=0`) | **$0.024/jam = $0.57/hari** | hanya reservasi storage 100 GB yang tertagih; wake ±90 detik |
| ~~workergroup dihapus~~ | $0 | **DILARANG** - lihat aturan di bawah |

`cold_workers=1` pada dasarnya **menyewa satu RTX 5090 permanen**, jadi endpoint ini dijalankan
dengan `cold_workers=0`: worker padam sendiri ±70 detik setelah sepi, request berikutnya bangun
±90 detik karena bobotnya masih di disk.

### ATURAN PEMILIK: JANGAN hapus workergroup
Workergroup (dan worker-nya) **tidak boleh dihapus**, meskipun kelihatan $0 itu lebih murah.
Alasannya: penghapusan memaksa worker baru men-download ulang seluruh bobot dari nol.
Terukur di `vastai show invoices`:

```
Instance_<id>_download_charge: GB_*$/.GB   72,100   0,003   0,188
```

Jadi satu siklus hapus-buat = ±72 GB transfer (plus ±22 menit provisioning). Simpan
workergroup-nya, biarkan `cold_workers=0` yang mengurus biaya. Yang boleh diubah-ubah hanyalah
**parameter endpoint** (`update endpoint`), bukan workergroup:

```bash
vastai update endpoint 36613 --cold_workers 0 --inactivity_timeout 300   # aman, tidak mengganti worker
# JANGAN: vastai delete workergroup ...   (perintahnya sengaja tidak ditulis di sini)
# JANGAN: vastai update workergroup ... --launch_args/--template_hash (bisa memicu worker baru = unduh ulang)
```

Karena provisioning penuh bisa 22 menit, `max_queue_time` dinaikkan ke **1800** agar request
pertama tidak dianggap antrian basi — `HIGGSGEN_JOB_TIMEOUT` (API) dan timeout polling FE ikut
naik ke 1800 s / 30 menit.

## Filter wilayah (WAJIB - syarat lisensi model)
Lisensi bobot mengecualikan **Uni Eropa, Inggris, Korea Selatan, AS** dari hosting/penjualan
bobot maupun output. Autoscaler Vast merekrut host dari pasar global, jadi wilayah harus
disaring di `search_params`.

### ⚠️ Satuan field di `search_params` (jebakan, terukur 2026-09-08)
`cpu_ram` dan `gpu_ram` di **query** bersatuan **GB**, tapi di **output JSON** `search offers` keduanya
bersatuan **MB**. Jadi `cpu_ram>=32000` = "butuh 32 000 GB" → **0 hasil**, sementara `x['cpu_ram']`
menampilkan `64475` (= 64 GB). Yang benar: `cpu_ram>=48`. Field `disk_bw` (MB/s) baru ada di output,
dan sebagai filter query ia diterima.

Cara memeriksa funnel sebelum memasang query di workergroup (satu calls, hitung lokal):
```bash
vastai search offers "num_gpus=1 gpu_name=RTX_5090 compute_cap>=890 geolocation in [JP,TW,TH,VN,HK,CN,ID,MY,IN,AE,SA,LK,AU,NZ,CA,MX,AR,CL,ZA,JO,SG]" --raw \
  | python3 -c "import json,sys;o=json.load(sys.stdin);print(len(o),'offer | dph',sorted(x['dph_total'] for x in o)[:3])"
```

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
