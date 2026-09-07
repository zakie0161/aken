#!/bin/bash
# onstart: pasang PyWorker pakai repo resmi, tapi dengan benchmark dari stack spec kita.
#
# Kenapa perlu: /opt/supervisor-scripts/pyworker.sh punya escape hatch - kalau
# /root/onstart.sh menyebut "pyworker" atau "start_server.sh", supervisor skip
# bootstrap bawaannya dan serahkan ke script ini. Jadi kita bisa pakai worker
# resmi + menukar file benchmark-nya.
set -uo pipefail

PYWORKER_REPO="${PYWORKER_REPO:-https://github.com/vast-ai/pyworker.git}"
PYWORKER_REF="${PYWORKER_REF:-main}"
BACKEND="${BACKEND:-comfyui-json}"
WS="${WORKSPACE:-/workspace}"
# HARUS sama dengan SERVER_DIR di start_server.sh resmi: $WORKSPACE_DIR/vast-pyworker
PYWORKER_DIR="${PYWORKER_DIR:-$WS/vast-pyworker}"
STACK_REF="${STACK_REF:-main}"
STACK_REPO="${STACK_REPO:-https://github.com/zakie0161/aken.git}"
LOG="[stack-onstart]"

log() { echo "$LOG $*"; }

main() {
  log "mulai (SERVERLESS=${SERVERLESS:-unset}, BACKEND=$BACKEND, dir=$PYWORKER_DIR)"

  [[ -d "$PYWORKER_DIR/.git" ]] || git clone --depth 1 --branch "$PYWORKER_REF" "$PYWORKER_REPO" "$PYWORKER_DIR" || return 1

  local tmp=/workspace/.stack-src
  if [[ ! -d "$tmp/.git" ]]; then
    git clone --depth 1 --branch "$STACK_REF" "$STACK_REPO" "$tmp" || { log "gagal clone stack repo"; return 1; }
  else
    ( cd "$tmp" && git fetch --depth 1 origin "$STACK_REF" -q && git reset --hard -q "origin/$STACK_REF" )
  fi

  local dst="$PYWORKER_DIR/workers/$BACKEND/misc"
  mkdir -p "$dst"
  if [[ -s "$WS/stack/benchmark.json" ]]; then
    cp -f "$WS/stack/benchmark.json" "$dst/benchmark.json"
    log "benchmark dari stack spec -> $dst/benchmark.json ($(wc -c < "$dst/benchmark.json") byte)"
  elif [[ -s "$tmp/stack/benchmark.example.json" ]]; then
    cp -f "$tmp/stack/benchmark.example.json" "$dst/benchmark.json"
    log "benchmark dari contoh repo (placeholder - ganti lewat spec!)"
  else
    log "tidak ada benchmark custom, worker pakai bawaan repo pyworker"
  fi

  # start_server.sh clones ke $WORKSPACE_DIR/vast-pyworker; kalau foldernya sudah ada,
  # dia cuma fetch/checkout/pull - benchmark.json kita (untracked) tetap selamat.
  export BACKEND WORKSPACE_DIR="$WS"
  cd "$PYWORKER_DIR" || return 1
  exec bash -c "curl -fsSL https://raw.githubusercontent.com/vast-ai/pyworker/$PYWORKER_REF/start_server.sh | bash"
}

main "$@"
