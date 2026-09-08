#!/bin/bash
# Bootstrap generik: unduh komponen worker dari STACK_SPEC_URL, lalu pasang PyWorker.
# Tidak ada nama model, kredensial, atau URL spesifik di file ini — semuanya dari spec.
#
# Env yang dibutuhkan (di-set lewat template Vast, yang bersifat private):
#   STACK_SPEC_URL   wajib  URL JSON publik (tanpa auth) berisi daftar file + graph
#   STACK_WORKSPACE  opsional default /workspace
#   STACK_JOBS       opsional default 3
set -uo pipefail

WS="${STACK_WORKSPACE:-/workspace}"
COMFYUI_DIR="${COMFYUI_DIR:-$WS/ComfyUI}"
MODELS="${STACK_MODELS_DIR:-$COMFYUI_DIR/models}"
WORK="${STACK_WORK_DIR:-$WS/stack}"
SPEC_URL="${STACK_SPEC_URL:-}"
JOBS="${STACK_JOBS:-3}"
SPEC="$WS/stack-spec.json"
LOG="[stack]"
PY="${PYTHON:-python3}"

die() { echo "$LOG [ERROR] $*" >&2; exit 1; }
[[ -n "$SPEC_URL" ]] || die "STACK_SPEC_URL kosong - set di env template"

fetch_spec() {
  mkdir -p "$WS"
  wget -q --tries=5 --timeout=60 -O "$SPEC" "$SPEC_URL" || die "gagal ambil spec: $SPEC_URL"
  $PY -c "import json,sys;json.load(open('$SPEC'))" || die "spec bukan JSON valid"
  echo "$LOG spec ok: $(wc -c < "$SPEC") byte"
}

dl() { # repo rev path target size
  local repo="$1" rev="$2" path="$3" target="$4" want="$5" name out size
  name="$(basename "$path")"; out="$target/$name"
  mkdir -p "$target"
  if [[ -s "$out" ]]; then
    size=$(stat -c %s "$out")
    if [[ "${want:-0}" == "0" || "$size" == "$want" ]]; then echo "$LOG skip $name"; return 0; fi
    echo "$LOG ukuran beda ($size != $want), ambil ulang: $name"; rm -f "$out"
  fi
  local auth=()
  [[ -n "${HF_TOKEN:-}" ]] && auth=(--header="Authorization: Bearer $HF_TOKEN")
  echo "$LOG -> $name"
  wget -q --continue --tries=10 --retry-connrefused --timeout=120 "${auth[@]}" \
    -O "$out" "https://huggingface.co/$repo/resolve/$rev/$path" || { echo "$LOG GAGAL $name"; return 1; }
  size=$(stat -c %s "$out" 2>/dev/null || echo 0)
  [[ "${want:-0}" != "0" && "$size" != "$want" ]] && { echo "$LOG KORUP $name ($size/$want)"; return 1; }
  echo "$LOG ok $name ($size)"
}

install_pyworker() {
  # start_server.sh resmi meng-clone ke "$WORKSPACE_DIR/vast-pyworker"; kalau foldernya sudah
  # ada, dia cuma fetch/checkout - benchmark.json kita (untracked) tetap selamat.
  local repo="${PYWORKER_REPO:-https://github.com/vast-ai/pyworker}"
  local ref="${PYWORKER_REF:-main}"
  local backend="${BACKEND:-comfyui-json}"
  local dir="${PYWORKER_DIR:-$WS/vast-pyworker}"
  if [[ ! -d "$dir/.git" ]]; then
    echo "$LOG clone pyworker -> $dir" || true
    git clone --depth 1 --branch "$ref" "$repo" "$dir" || { echo "$LOG GAGAL clone pyworker"; return 1; }
  fi
  local dst="$dir/workers/$backend/misc"
  if [[ -s "$WORK/benchmark.json" ]]; then
    mkdir -p "$dst"
    cp -f "$WORK/benchmark.json" "$dst/benchmark.json"
    echo "$LOG benchmark terpasang: $dst/benchmark.json ($(wc -c < "$dst/benchmark.json") byte)"
  else
    echo "$LOG tidak ada benchmark dari spec - worker pakai bawaan"
  fi
}

main() {
  echo "$LOG mulai; workspace=$WS"
  fetch_spec
  # Satu jalan: petakan kapabilitas -> file bobot, murni dari spec (capabilities/profiles/components).
  # STACK_ONLY=<kapabilitas> -> worker hanya unduh bobot kapabilitas itu + pakai benchmark ringan.
  # Tanpa itu: semua file + benchmark bawaan spec (perilaku lama).
  local listfile="$WS/stack-files.list"
  rm -f "$listfile"
  $PY - "$SPEC" "${STACK_ONLY:-}" "$WORK" "$listfile" <<'PY' || die "gagal memproses spec"
import json, os, re, sys
spec, only, work, listfile = (json.load(open(sys.argv[1])), (sys.argv[2] or "").strip().lower(),
                              sys.argv[3], sys.argv[4])
WEIGHT = re.compile(r"([A-Za-z0-9_.\-]+\.(?:safetensors|ckpt|pt|pth|bin|onnx|gguf|ggml))")
names = lambda o: set(WEIGHT.findall(json.dumps(o)))
caps, profs = spec.get("capabilities") or {}, spec.get("profiles") or {}
need = {}
for cap, cfg in caps.items():
    s = set()
    for p in (cfg.get("profiles") or []):
        if p in profs: s |= names(profs[p])
    comp = (spec.get("components") or {}).get(cap)
    if comp: s |= names(comp)
    need[cap.lower()] = s
allrefs = set().union(*need.values()) if need else set()

files = spec.get("files") or []
if only and only not in need:
    print(f"[stack] [ERROR] STACK_ONLY={only} bukan kapabilitas spec {sorted(need)}", file=sys.stderr)
    sys.exit(1)

keep, skipped = [], 0
for f in files:
    b = f["path"].rsplit("/", 1)[-1]
    if only and b not in need[only] and b in allrefs:
        skipped += 1
        continue
    keep.append(f)
with open(listfile, "w") as fh:
    for f in keep:
        fh.write("|".join([f["repo"], f["rev"], f["path"], f["subdir"], str(f.get("size", 0))]) + "\n")
gb = sum(int(f.get("size", 0)) for f in keep) / 1e9
print(f"[stack] unduh {len(keep)}/{len(files)} file = {gb:.1f} GB" + (f" (STACK_ONLY={only}, lewati {skipped})" if only else ""))

os.makedirs(work, exist_ok=True)
profiles = {k: v for k, v in profs.items() if not only or str(v.get("capability", "")).lower() == only}
bench = spec.get("benchmark")
if only and profiles:
    pick = sorted(profiles.items(), key=lambda kv: (kv[1].get("cost") or 0, kv[0]))[0]
    bench = pick[1].get("graph")
    print(f"[stack] benchmark ringan: profil {pick[0]} (cost {pick[1].get('cost')}) bukan graph bawaan spec")
missing = (names(bench) - {f["path"].rsplit("/", 1)[-1] for f in keep}) if bench else set()
if missing: print(f"[stack] [WARN] graph benchmark menyebut file yang tidak diunduh: {sorted(missing)}", file=sys.stderr)
if bench: open(f"{work}/benchmark.json", "w").write(json.dumps(bench, indent=1))
if profiles: open(f"{work}/profiles.json", "w").write(json.dumps(profiles, indent=1))
PY


  local n=0
  while IFS='|' read -r repo rev path sub want; do
    [[ -z "$repo" ]] && continue
    dl "$repo" "$rev" "$path" "$MODELS/$sub" "$want" &
    n=$((n+1))
    while [[ "$(jobs -rp | wc -l)" -ge "$JOBS" ]]; do wait -n; done
  done < "$listfile"
  wait || die "ada file yang gagal ($n item)"

  install_pyworker

  # cron pembersih output: worker hidup sampai inactivity_timeout setelah request terakhir,
  # jadi output cukup bertahan sebentar - hasil sudah dipanen higgsgen-api sebagai base64.
  if ! crontab -l 2>/dev/null | grep -qF 'stack-clean'; then
    ( crontab -l 2>/dev/null; echo "# stack-clean"; \
      echo '*/5 * * * * find '"$COMFYUI_DIR"'/output -type f -mmin +20 -delete; find '"$COMFYUI_DIR"'/temp -type f -mmin +20 -delete' ) | crontab -
  fi
  echo "$LOG selesai"; du -sh "$MODELS"/* 2>/dev/null | sed "s/^/$LOG   /"
}

main "$@"
