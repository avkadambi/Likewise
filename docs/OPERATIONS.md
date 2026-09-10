# Likewise — Operations

Installing, running, configuring and troubleshooting a deployment.

Companion documents: [USER_GUIDE.md](USER_GUIDE.md), [METHOD.md](METHOD.md),
[DESIGN.md](DESIGN.md).

---

## 1. Requirements

**Container path (recommended).** Podman. Nothing else — no Python on the host, no compiler.
Runs rootless on any Linux distribution, and on macOS through `podman machine`.

**Virtual-environment path.** Python 3.10 or newer, and network access to PyPI once. 3.11
and 3.12 are what this has been run on. 3.9 will not work: FastAPI evaluates route
annotations at import and the routes use `str | None`.

There is no database server, message queue, cache, object store or cloud account in either
path. Storage is the local filesystem.

Installing podman, if needed:

```
# Fedora, RHEL, CentOS
sudo dnf install -y podman

# Debian, Ubuntu
sudo apt-get install -y podman

# macOS
brew install podman && podman machine init && podman machine start
```

## 2. Install

```
./install.sh                  # picks container if podman is present, otherwise virtualenv
./install.sh --container      # force the container path
./install.sh --venv           # force the virtualenv path
./install.sh --quick          # skip the mutation gate (about two minutes)
./install.sh --start          # start the application when the install finishes
./install.sh --with-example   # also load the example filing and scan it end to end
```

The install is idempotent — run it again after a `git pull`.

What it does, in order:

1. Picks a mode and checks the prerequisite is actually there.
2. Builds — the container image, or `.venv` with the pinned dependencies.
3. Runs the **startup gate** against the specification. A failure here is a real result about
   the specification, not an installation problem, so it prints the structured payload and
   stops.
4. Runs the test suite. On the container path, against a throwaway layer built on top of the
   image that will actually run.
5. Runs the mutation gate (virtualenv path, unless `--quick`).

If it stops, it stops with a reason and a non-zero exit code.

## 3. Start, stop, inspect

**Container:**

```
./likewise.sh start          # build if needed, then run on http://127.0.0.1:8080
./likewise.sh stop           # stop and remove the container
./likewise.sh restart
./likewise.sh status         # is it up, and which specification and snapshot is it holding
./likewise.sh logs           # follow
./likewise.sh shell          # a shell inside the container
./likewise.sh build          # rebuild the image
./likewise.sh load [args]    # load whatever is in ./data/inbox
./likewise.sh scan LEI YEAR  # scan one filer-year already loaded
```

**Virtual environment:**

```
make serve                   # API on /v1, web view on /ui
make load ARGS=--and-scan
make scan / make sweep SCAN=... / make controls SCAN=...
make test / make mutate
make help
```

The container publishes to `127.0.0.1:8080` only. To expose it elsewhere, put a reverse proxy
that terminates TLS in front of it; do not change the publish address to `0.0.0.0` and call it
done. Every route except `/health` requires a bearer credential, but the service has no TLS of
its own.

## 4. Configuration

| Variable | Default | Effect |
| :--- | :--- | :--- |
| `LIKEWISE_PRINCIPALS` | `dev-read` / `dev-write` | JSON map of bearer credential to subject and scopes. Every route except `/health` requires one |
| `LIKEWISE_PSEUDONYM_KEY` | a literal development string | Hex HMAC key behind every pseudonymised identifier. **Changing it changes every identifier** |
| `LIKEWISE_KEY_VERSION` | `1` | Published alongside identifiers so a consumer can tell key generations apart |
| `LIKEWISE_PREREG` | unset | Pre-registration digest. While unset, every scan is labelled **exploratory** and says so on every finding |
| `LIKEWISE_DATA` | `./data` | Root for the drop folder, curated snapshots and the store |
| `LIKEWISE_STORE` | `$LIKEWISE_DATA/store` | Scan results and artefacts |
| `LIKEWISE_SPECS` | `./specs` | The comparability specifications |
| `LIKEWISE_SPEC` | `1.3.0` | Specification version used by `./likewise.sh scan` |
| `LIKEWISE_IMAGE` | `localhost/likewise:latest` | Image tag |
| `LIKEWISE_CONTAINER` | `likewise` | Container name |
| `LIKEWISE_PORT` | `8080` | Host port |

The first three have development defaults so a local run works out of the box, and all three
are wrong for a deployment.

### The `.env` file

`./likewise.sh start` generates `.env` once, with `umask 077`, containing a read-only
credential, a read/write credential and a pseudonymisation key — each 24 or 32 bytes from
`/dev/urandom`. It is never regenerated, so restarts do not invalidate a session or change an
identifier.

**Back up `.env`.** `LIKEWISE_PSEUDONYM_KEY` is the HMAC key behind every pseudonymised
identifier the product has issued. Changing it changes every record reference and finding
identifier, so a worksheet exported before the change will not match one exported after. Treat
it with the same care as the data.

**Keep it out of version control.**

## 5. Data layout

Everything mutable lives under `./data` on the host, mounted at `/data` in the container.

```
data/
  inbox/       drop .csv files here
  curated/     normalised Parquet, one immutable prefix per snapshot
  store/       scan records, findings, summaries, controls, sweeps
  examples/    the shipped example filing
```

Deleting the directory removes every scan and snapshot. Nothing is written anywhere else —
in the container, the root filesystem is read-only and `/tmp` is a tmpfs, so this is enforced
rather than promised.

### Backup

Back up `./data` and `.env` together. Restoring `data` without the matching pseudonymisation
key gives you the same scans under different identifiers, which is worse than not restoring
them.

Snapshots under `data/curated/` are immutable once written, so an incremental backup of that
directory is safe. `data/store/` is append-mostly; dispositions written from the review queue
are the only in-place updates.

### Upgrade

```
git pull
./install.sh --container      # rebuilds the image, re-runs the gates
./likewise.sh restart
```

Existing snapshots and scans survive an upgrade. A scan is identified by its inputs including
the specification version, so a new specification produces new scans rather than altering old
ones.

## 6. Sizing

The loader converts inside DuckDB rather than in Python, so memory does not scale with the
input file. `SET memory_limit` is a budget DuckDB honours rather than a cliff it falls off.
512 MB is DuckDB's own floor for this pipeline — below that, a three-row file fails too.

The container defaults to `--memory 2g --cpus 2`, which handles the full national file
(13.5 million records) for load and single-filer scans. Raise it in `likewise.sh` if you scan
several filers concurrently; the service runs at concurrency 1 per scan, so the bound that
matters is instances, not threads.

Disk: budget roughly the size of your input CSVs again for the curated Parquet, plus a small
constant for the store.

## 7. Security posture

- **Rootless.** The image runs as uid/gid 10001. Building or running as root works but leaves
  the bind-mounted data directory owned by root, and then "uninstall is `rm -rf`" stops being
  true.
- **Read-only root filesystem**, with a tmpfs for `/tmp`. The process writes only to `/data`.
- **`:Z` relabelling** on the volume, so it works unmodified under SELinux.
- **Published to `127.0.0.1` only.**
- **Every route except `/health` requires a per-principal bearer credential**, reads included.
  The web view's session cookie carries the same credential the API takes — no second signing
  key, no second trust root, one place to revoke.
- **`/pairs/evaluate` rejects institution identifiers rather than redacting them**, because
  redaction would make the endpoint an oracle over its own pseudonymisation function across an
  enumerable public panel.
- **Request bodies are excluded from logs.**
- **Census tract is dropped at ingest**, so no intermediate file and no downstream code can
  carry it.
- **All external serialisation passes through one boundary** (`egress.py`), enforced by a
  contract test over every registered route and a static check that fails the build on a direct
  import of a raw dataclass into a renderer.

## 8. Troubleshooting

**The container exits immediately, exit code 78.**
The startup gate refused the specification. `./likewise.sh logs` shows the payload, which names
the offending dimension and rule. This is a specification result, not an installation problem.
See DESIGN §5.

**`podman build` fails on macOS.**
The podman virtual machine is not running: `podman machine init` (first time), then
`podman machine start`. `install.sh` checks for this and says so.

**Writes fail with "Read-only file system".**
Something is trying to write outside `/data`. That is the design working. If it is a genuine
need, it belongs under `/data` via `paths.py`, not via a writable root.

**A load refused.**
Read the payload; it names the rows or columns. The most common cause is data that is not at
publication granularity — see USER_GUIDE §5. `--internal-data` overrides it and permanently
stamps the snapshot non-public.

**A load refused with a row-count mismatch.**
A ragged row. The loader never pads, because a shifted column is exactly what that catches. The
payload gives physical rows scanned against rows produced.

**The review queue returns 409.**
The scan has no sweep. `make sweep SCAN=scn_...` or `./likewise.sh` equivalent. There is no flag
to bypass it: a finding may not be presented without the curve showing whether its threshold was
chosen to produce it.

**A scan produced no findings.**
Common and usually correct. Check `/ui/scans/{id}/coverage` — the chain shows where the
population went. Typically matching (a filer dispersed across many geographies) or testability
(stated reasons the public record cannot adjudicate).

**Nothing is being published even though there are findings.**
The controls did not pass. Check `/ui/scans/{id}/controls`.

**Tests fail after a killed mutation run.**
The mutation harness snapshots every source file before it starts. If a run was killed with
SIGKILL, its `finally` block did not run; the next `tools/mutate.py` invocation restores any
leftover automatically. If you need to do it by hand, the snapshot is in `.mutation-snapshot/`.

**Port 8080 is in use.**
`LIKEWISE_PORT=8081 ./likewise.sh start`.

## 9. Uninstall

```
./likewise.sh stop
podman rmi localhost/likewise:latest
rm -rf <this directory>
```

For the virtualenv path, `make clean` and deleting the directory is the whole of it.
