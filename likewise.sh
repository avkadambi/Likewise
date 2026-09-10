#!/usr/bin/env bash
# Likewise — start, stop and drive the container.
#
#   ./likewise.sh start            build if needed, then run on http://127.0.0.1:8080
#   ./likewise.sh stop             stop and remove the container
#   ./likewise.sh status           is it up, and what is it holding
#   ./likewise.sh logs             follow the log
#   ./likewise.sh load [args]      load whatever is in ./data/inbox
#   ./likewise.sh scan LEI YEAR [SNAPSHOT]
#                                  scan one filer-year already loaded; the snapshot
#                                  defaults to the most recently loaded one
#   ./likewise.sh shell            a shell inside the container
#   ./likewise.sh restart          stop, then start
#   ./likewise.sh build            rebuild the image
#
# Everything mutable lives in ./data on the host, mounted at /data in the container.
# Nothing is written anywhere else.

set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

IMAGE="${LIKEWISE_IMAGE:-localhost/likewise:latest}"
NAME="${LIKEWISE_CONTAINER:-likewise}"
PORT="${LIKEWISE_PORT:-8080}"
DATA="${LIKEWISE_DATA:-$PWD/data}"

BOLD=""; DIM=""; RESET=""
if [ -t 1 ]; then BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); RESET=$(printf '\033[0m'); fi
say()  { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$1"; }
note() { printf '    %s%s%s\n' "$DIM" "$1" "$RESET"; }
die()  { printf '\n%serror:%s %s\n' "$BOLD" "$RESET" "$1" >&2; exit 1; }

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; }

case "${1:-}" in
  -h|--help|help) usage; exit 0 ;;
esac

command -v podman >/dev/null 2>&1 || die "podman is not installed. See docs/OPERATIONS.md."

# Credentials. Generated once into .env and never regenerated, so container restarts
# do not invalidate a session or change any pseudonymised identifier.
ensure_env() {
  [ -f .env ] && return 0
  say "Generating credentials into .env"
  local read_tok write_tok pseudo
  read_tok=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
  write_tok=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
  pseudo=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  umask 077
  cat > .env <<EOF
# Generated on first start. Keep out of version control.
#
# LIKEWISE_PSEUDONYM_KEY is the HMAC key behind every pseudonymised identifier a
# response carries. Changing it changes every record reference and finding id, so a
# worksheet exported before the change will not match one exported after. Back it up
# with the same care as the data.
LIKEWISE_PRINCIPALS={"${read_tok}":{"sub":"read","scopes":["read"]},"${write_tok}":{"sub":"analyst","scopes":["read","write"]}}
LIKEWISE_PSEUDONYM_KEY=${pseudo}
LIKEWISE_KEY_VERSION=1
EOF
  note "read-only credential : ${read_tok}"
  note "read/write credential: ${write_tok}"
  note "both are in .env; sign in at /ui with the read/write one"
}

build() {
  say "Building ${IMAGE}"
  podman build -t "$IMAGE" -f Containerfile . || die "build failed"
}

start() {
  ensure_env
  podman image exists "$IMAGE" || build
  if podman container exists "$NAME"; then
    if [ "$(podman inspect -f '{{.State.Running}}' "$NAME")" = "true" ]; then
      note "already running"; status; return 0
    fi
    podman rm "$NAME" >/dev/null
  fi
  mkdir -p "$DATA/inbox" "$DATA/curated" "$DATA/store" "$DATA/examples"
  [ -f data/examples/likewise_example_filing.csv ] && \
    cp -n data/examples/likewise_example_filing.csv "$DATA/examples/" 2>/dev/null || true

  say "Starting ${NAME} on port ${PORT}"
  # --read-only with a tmpfs for /tmp: the process writes only to /data. :Z relabels the
  # volume for SELinux, which is what makes this work unmodified on RHEL and Fedora.
  podman run -d --name "$NAME" \
    --env-file .env \
    -p "127.0.0.1:${PORT}:8080" \
    -v "${DATA}:/data:Z" \
    --read-only --tmpfs /tmp:rw,size=512m \
    --memory 2g --cpus 2 \
    --restart unless-stopped \
    "$IMAGE" >/dev/null || die "could not start the container"

  printf '    waiting for the specification gate'
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      printf '\n'; say "Ready"
      note "web view : http://127.0.0.1:${PORT}/ui"
      note "API      : http://127.0.0.1:${PORT}/v1"
      note "credentials are in .env"
      return 0
    fi
    if [ "$(podman inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" != "true" ]; then
      printf '\n'
      echo "--- container log ---" >&2
      podman logs "$NAME" >&2 || true
      die "the container exited during startup. Exit code 78 means the specification was refused; the payload above names the offending dimension."
    fi
    printf '.'; sleep 1
  done
  printf '\n'; die "did not become healthy within 30s. ./likewise.sh logs"
}

stop() {
  podman container exists "$NAME" || { note "not running"; return 0; }
  say "Stopping ${NAME}"
  podman stop "$NAME" >/dev/null && podman rm "$NAME" >/dev/null
}

status() {
  if ! podman container exists "$NAME"; then note "not running"; return 0; fi
  podman ps --filter "name=^${NAME}$" --format '    {{.Names}}  {{.Status}}  {{.Ports}}'
  curl -fsS "http://127.0.0.1:${PORT}/health" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("    spec %s  snapshot %s"%(d.get("version"),d.get("snapshot_id")))' \
    2>/dev/null || note "not answering on /health yet"
}

in_container() { podman exec -it "$NAME" "$@"; }

case "${1:-start}" in
  start)  start ;;
  stop)   stop ;;
  restart) stop; start ;;
  build)  build ;;
  status) status ;;
  logs)   podman logs -f "$NAME" ;;
  shell)  in_container /bin/bash ;;
  load)   shift; in_container python tools/load.py --inbox /data/inbox "$@" ;;
  scan)   shift; [ $# -ge 2 ] || die "usage: ./likewise.sh scan LEI YEAR [SNAPSHOT]"
          SNAP="${3:-}"
          if [ -z "$SNAP" ]; then
            # Default to the most recently written curated snapshot, and say which.
            SNAP=$(ls -1t "${DATA}/curated" 2>/dev/null | head -1)
            [ -n "$SNAP" ] || die "no curated snapshot in ${DATA}/curated -- run './likewise.sh load' first"
            note "snapshot: ${SNAP}"
          fi
          in_container python tools/run_scan.py --lei "$1" --year "$2" \
            --snapshot "$SNAP" --spec-version "${LIKEWISE_SPEC:-1.4.0}" ;;
  *)      usage; exit 2 ;;
esac
