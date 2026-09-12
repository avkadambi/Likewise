#!/usr/bin/env bash
# Likewise - one-command install.
#
# Two ways to run it, and this script sets up either:
#
#   container  a rootless podman image. Nothing but podman is needed on the host, and
#              the same image runs on any Linux distribution. This is the default when
#              podman is available.
#   virtualenv a .venv in this directory with the pinned dependencies. Needs Python
#              3.10 or newer. This is the default otherwise, and it is what you want if
#              you are going to edit the code.
#
# Usage:
#   ./install.sh                  pick automatically, run the checks, build
#   ./install.sh --container      force the container path (needs podman)
#   ./install.sh --venv           force the virtualenv path (needs Python 3.10+)
#   ./install.sh --quick          skip the mutation gate
#   ./install.sh --start          start the application when the install finishes
#   ./install.sh --with-example   also load the example filing and scan it end to end
#
# Everything lives inside this directory. Deleting the folder is a complete uninstall,
# apart from the container image, which "podman rmi localhost/likewise:latest" removes.
#
# Written for the bash macOS ships (3.2), so nothing here needs a newer shell.

set -euo pipefail

QUICK=0
WITH_EXAMPLE=0
START=0
MODE=""
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    --with-example) WITH_EXAMPLE=1 ;;
    --start) START=1 ;;
    --container|--podman) MODE=container ;;
    --venv|--virtualenv) MODE=venv ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$(cd "$(dirname "$0")" && pwd)"

BOLD=""; DIM=""; RESET=""
if [ -t 1 ]; then BOLD="$(printf '\033[1m')"; DIM="$(printf '\033[2m')"; RESET="$(printf '\033[0m')"; fi
step() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$1"; }
note() { printf '    %s%s%s\n' "$DIM" "$1" "$RESET"; }
die()  { printf '\n%sinstall failed:%s %s\n' "$BOLD" "$RESET" "$1" >&2; exit 1; }

# ------------------------------------------------------------ mode choice ----
have_podman=0; command -v podman >/dev/null 2>&1 && have_podman=1

PYBIN=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)' 2>/dev/null; then
      PYBIN="$c"; break
    fi
  fi
done

if [ -z "$MODE" ]; then
  if [ "$have_podman" -eq 1 ]; then MODE=container; else MODE=venv; fi
fi

if [ "$MODE" = "container" ] && [ "$have_podman" -eq 0 ]; then
  echo "" >&2
  echo "podman is not on PATH, and --container needs it." >&2
  case "$(uname -s)" in
    Darwin) echo "  brew install podman && podman machine init && podman machine start" >&2 ;;
    Linux)  echo "  Fedora, RHEL, CentOS:  sudo dnf install -y podman" >&2
            echo "  Debian, Ubuntu:        sudo apt-get install -y podman" >&2 ;;
  esac
  echo "" >&2
  echo "Or install without a container:  ./install.sh --venv" >&2
  die "podman not found"
fi

if [ "$MODE" = "venv" ] && [ -z "$PYBIN" ]; then
  # 3.10 is a hard floor, not a preference: FastAPI evaluates route annotations at
  # import time and the routes use `str | None`, which 3.9 cannot parse at runtime.
  echo "" >&2
  echo "No Python 3.10 or newer on PATH." >&2
  if command -v python3 >/dev/null 2>&1; then
    echo "  python3 is $(python3 -V 2>&1), which is too old." >&2
  fi
  if [ "$(uname -s)" = "Darwin" ]; then
    echo "" >&2
    echo "On macOS, either:" >&2
    echo "  brew install python@3.12          # if you have Homebrew" >&2
    echo "  xcode-select --install            # ships a recent python3 on current macOS" >&2
    echo "or install from https://www.python.org/downloads/macos/" >&2
  fi
  if [ "$have_podman" -eq 1 ]; then
    echo "" >&2
    echo "podman is available, so you can skip Python entirely:  ./install.sh --container" >&2
  fi
  die "no suitable interpreter"
fi

IMAGE="${LIKEWISE_IMAGE:-localhost/likewise:latest}"

# The specification is the thing this product stands on, so it is validated before
# anything is built, in whichever interpreter is at hand. A failure here is a real
# result about the specification, not an installation problem.
gate_source() {
  cat <<'GATEEOF'
import sys
sys.path.insert(0, ".")
from likewise import specs
from likewise.errors import SpecError
try:
    s = specs.load(version="1.4.0")
except SpecError as e:
    e.emit_and_exit()
print("    spec v%s | snapshot %s | gate passed" % (s.version, s.snapshot_id))
GATEEOF
}

# =========================================================== container path ===
if [ "$MODE" = "container" ]; then

  step "Container install with podman"
  note "$(podman --version 2>&1)"

  # On macOS, podman runs Linux inside a virtual machine, so the machine has to be up
  # before anything can be built.
  if [ "$(uname -s)" = "Darwin" ]; then
    if ! podman machine list --format '{{.Running}}' 2>/dev/null | grep -q true; then
      echo "" >&2
      echo "The podman virtual machine is not running. Start it with:" >&2
      echo "  podman machine init      # first time only" >&2
      echo "  podman machine start" >&2
      die "podman machine is not running"
    fi
  fi

  # Rootless is the intended posture. Building as root works, but then the bind-mounted
  # data directory ends up owned by root and "uninstall is rm -rf" stops being true.
  if [ "$(id -u)" = "0" ] && [ "$(uname -s)" = "Linux" ]; then
    note "running as root: the image is built for rootless podman and does not need it"
  fi

  step "Building the image"
  note "two stages, so the runtime layer carries no compiler and no package index"
  podman build -t "$IMAGE" -f Containerfile . || die "podman build failed"

  step "Running the startup gate inside the image"
  gate_source | podman run --rm -i --entrypoint python "$IMAGE" - \
    || die "the startup gate refused the specification (see the payload above)"

  if [ "$QUICK" -eq 0 ]; then
    # The tests are deliberately not in the runtime image; they have no business in a
    # deployed artifact. They run against a throwaway layer built on top of it, so what
    # is tested is the image that will actually run.
    step "Running the test suite against the built image"
    note "this adds a minute; --quick skips it"
    tmpdir=$(mktemp -d)
    trap 'rm -rf "$tmpdir"' EXIT
    {
      echo "ARG BASE"
      echo 'FROM ${BASE}'
      echo "USER root"
      echo "COPY requirements.txt requirements-dev.txt /tmp/"
      echo "RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt"
      echo "COPY requirements.txt /app/requirements.txt"
      echo "COPY extract/ /app/extract/"
      echo "COPY tests/ /app/tests/"
      echo "COPY pytest.ini /app/pytest.ini"
      echo "COPY data/examples/ /app/data/examples/"
      echo "COPY data/raw/ /app/data/raw/"
      echo "USER 10001:10001"
    } > "$tmpdir/Containerfile.test"
    podman build -q --build-arg "BASE=$IMAGE" -t localhost/likewise-test:latest \
      -f "$tmpdir/Containerfile.test" . >/dev/null || die "could not build the test layer"
    podman run --rm --entrypoint python localhost/likewise-test:latest -m pytest tests/ -q \
      || die "tests failed against the built image; do not deploy it"
    podman rmi -f localhost/likewise-test:latest >/dev/null 2>&1 || true
  else
    note "skipped the test run (--quick)"
  fi

  mkdir -p data/inbox data/curated data/store data/examples

  if [ "$WITH_EXAMPLE" -eq 1 ] || [ "$START" -eq 1 ]; then
    step "Starting the application"
    ./likewise.sh start || die "the container did not start"
    if [ "$WITH_EXAMPLE" -eq 1 ]; then
      step "Loading the example filing and scanning it"
      cp -f data/examples/likewise_example_filing.csv data/inbox/ 2>/dev/null || true
      ./likewise.sh load --and-scan --label "Example filing" || die "the example did not load"
    fi
  fi

  cat <<EOF

$BOLD Installed as a container. $RESET

  Start the application       ./likewise.sh start
  Then open                   http://127.0.0.1:8080/ui
  Sign in with                the read/write credential printed into .env

  Stop it                     ./likewise.sh stop
  Follow the log              ./likewise.sh logs
  Load your own filing        cp docs/templates/likewise_lar_template.csv data/inbox/mine.csv
                              ./likewise.sh load
  Everything else             ./likewise.sh

$DIM  The container is rootless, its root filesystem is read-only, and it publishes only
  to 127.0.0.1. Everything mutable lives in ./data on this host. Credentials and the
  pseudonymisation key are generated into .env on first start; back that file up,
  because changing the key changes every identifier already issued.$RESET
EOF
  exit 0
fi

# ========================================================== virtualenv path ===
step "Virtualenv install"
note "$($PYBIN -V 2>&1)  ($(command -v "$PYBIN"))"

step "Creating the project virtualenv at .venv"
if [ -d .venv ] && [ ! -x .venv/bin/python ]; then
  note "removing a broken .venv"
  rm -rf .venv
fi
if [ ! -x .venv/bin/python ]; then
  "$PYBIN" -m venv .venv || die "python3 -m venv failed. On a Debian-family Linux you may need: apt install python3-venv"
else
  note "already present, reusing it"
fi
PY=".venv/bin/python"

step "Installing pinned dependencies"
"$PY" -m pip install --quiet --disable-pip-version-check --upgrade pip \
  || die "could not upgrade pip inside the venv"
"$PY" -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt \
  || die "dependency install failed. If you are offline, this step needs PyPI once."
note "$("$PY" -m pip list --format=freeze 2>/dev/null | wc -l | tr -d ' ') packages, all wheels"

step "Checking the engine loads"
"$PY" - <<'PYEOF' || die "the engine did not import"
import duckdb, fastapi, uvicorn, yaml, multipart
print("    duckdb %s | fastapi %s | uvicorn %s" % (duckdb.__version__, fastapi.__version__, uvicorn.__version__))
con = duckdb.connect()
assert con.execute("select 42").fetchone()[0] == 42
PYEOF

step "Running the startup gate against the specification"
gate_source | "$PY" - || die "the startup gate refused the specification (see the payload above)"

step "Linting"
note "the rule set is chosen to find defects, not to impose a style"
"$PY" -m ruff check . || die "lint failed"

step "Running the test suite"
"$PY" -m pytest tests/ -q || die "tests failed; do not trust a scan from this checkout"

if [ "$QUICK" -eq 0 ]; then
  # Mutation testing measures whether the tests would notice a defect, as opposed to
  # whether they pass. The kill-rate threshold is a release gate.
  step "Running the mutation gate (kill rate >= 0.90)"
  note "this takes a couple of minutes; --quick skips it"
  "$PY" tools/mutate.py || die "mutation gate below threshold"
else
  note "skipped the mutation gate (--quick)"
fi

if [ "$WITH_EXAMPLE" -eq 1 ]; then
  step "Loading the example filing and scanning it"
  cp -f data/examples/likewise_example_filing.csv data/inbox/
  "$PY" tools/load.py --and-scan --label "Example filing" || die "the example did not load"
fi

if [ "$START" -eq 1 ]; then
  step "Starting the application"
  exec make serve
fi

cat <<EOF

$BOLD Installed. $RESET

  Start the application       make serve
  Then open                   http://127.0.0.1:8080/ui
  Sign in with                dev-write

  Load your own filing        cp docs/templates/likewise_lar_template.csv data/inbox/mine.csv
                              make load
  Or try the example          make example

  Everything else             make help

$DIM  The credentials, the pseudonymisation key and the pre-registration digest are
  development defaults, documented in README.md. All three are wrong for anything but
  a local run. For a deployment, use the container path: ./install.sh --container$RESET
EOF
