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

main() {
  echo "$LOG mulai; workspace=$WS"
  fetch_spec
  # daftar file: "repo|rev|path|subdir|size" per baris, keluaran dari parser spec
  local list
  list=$($PY - "$SPEC" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))
base=s["base_url"] if "base_url" in s else "https://huggingface.co"
for f in s["files"]:
    print("|".join([f["repo"], f["rev"], f["path"], f["subdir"], str(f.get("size",0))]))
PY
) || die "spec tidak punya field files[]"

  local n=0
  while IFS='|' read -r repo rev path sub want; do
    [[ -z "$repo" ]] && continue
    dl "$repo" "$rev" "$path" "$WS/models/$sub" "$want" &
    n=$((n+1))
    while [[ "$(jobs -rp | wc -l)" -ge "$JOBS" ]]; do wait -n; done
  done <<< "$list"
  wait || die "ada file yang gagal ($n item)"

  # graph benchmark + profil kerja -> dipakai PyWorker & client
  $PY - "$SPEC" "$WS" <<'PY'
import json,sys
spec,ws=json.load(open(sys.argv[1])),sys.argv[2]
import os
os.makedirs(f"{ws}/stack",exist_ok=True)
for key,name in (("benchmark","benchmark.json"),("profiles","profiles.json")):
    if key in spec:
        open(f"{ws}/stack/{name}","w").write(json.dumps(spec[key],indent=1))
        print(f"[stack] tulis {name}")
PY

  # cron pembersih output lama
  if ! crontab -l 2>/dev/null | grep -qF 'stack-clean'; then
    ( crontab -l 2>/dev/null; echo "# stack-clean"; \
      echo '*/15 * * * * find '"$COMFYUI_DIR:-$WS/ComfyUI"'/output -type f -mmin +1440 -delete' ) | crontab -
  fi
  echo "$LOG selesai"; du -sh "$WS/models"/* 2>/dev/null | sed "s/^/$LOG   /"
}

main "$@"
