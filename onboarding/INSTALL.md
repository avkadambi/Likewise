# Install Guide

Getting Likewise running, with real data in it, in about twenty minutes. No prior
knowledge assumed.

There are two ways to install it. Pick one:

- **Container** — you need only `podman`. Nothing else touches your machine. Best if you
  just want to see it work, or if you are deploying it.
- **Virtual environment** — you need Python 3.10 or newer. Best if you are going to edit
  the code, which as a new joiner you probably are.

If you have neither, install one of them:

```bash
# Container route
sudo dnf install -y podman         # Fedora, RHEL, CentOS
sudo apt-get install -y podman     # Debian, Ubuntu
brew install podman && podman machine init && podman machine start   # macOS

# Python route
brew install python@3.12           # macOS with Homebrew
sudo apt-get install -y python3 python3-venv    # Debian, Ubuntu
```

Python 3.9 will not work. The web routes use `str | None` in their annotations and FastAPI
evaluates those at import time, so 3.9 fails before the first line of this code runs.

---

## Step 1 — Install

From the top of the repository:

```bash
./install.sh
```

That is the whole command. It picks the container route if `podman` is on your PATH and
the virtual-environment route otherwise. To force one:

```bash
./install.sh --container
./install.sh --venv
```

Useful flags:

| Flag | Effect |
| :--- | :--- |
| `--quick` | Skip the mutation gate. Saves about two minutes |
| `--with-example` | Also load a sample filing and scan it end to end |
| `--start` | Start the application when the install finishes |

**Expect it to take a few minutes**, and expect it to do real work rather than just copying
files. In order it will:

1. Check the prerequisite is actually there, and tell you how to get it if not.
2. Build — the container image, or `.venv` with the pinned dependencies.
3. Run the **startup gate** against the comparability specification.
4. Run the test suite. On the container route, against a throwaway layer built on top of
   the image that will actually ship, so what is tested is what runs.
5. Run the **mutation gate** unless you passed `--quick`.

If it stops, it stops with a reason and a non-zero exit code. It never half-installs.

### If step 3 fails

You will see a block of JSON naming a dimension and a rule. **This is not a broken
install.** It is the startup gate refusing the specification, which is a real result about
the specification — see MODELS §5 for why the gate exists and what it is protecting. On a
clean checkout it should not happen; if it does, something in `specs/` was edited.

---

## Step 2 — Start it

**Container:**

```bash
./likewise.sh start
```

On first start this generates a `.env` file containing two credentials and a
pseudonymisation key, and prints them. Sign in with the read/write one.

**Back up that file.** The pseudonymisation key is the HMAC key behind every identifier the
product has issued. Change it and every record reference and finding id changes, so a
worksheet exported before the change will not match one exported after. Treat it like the
data.

**Virtual environment:**

```bash
make serve
```

The development credential is `dev-write`. Fine locally, wrong anywhere else.

Either way, open **<http://127.0.0.1:8080/ui>**.

---

## Step 3 — Put data in it

Nothing interesting happens until there is a filing loaded. Three options, easiest first.

### Option A — the shipped example

```bash
make example
```

Loads a 15,000-row example filing and runs the whole sequence: load, scan, sweep,
controls. Ends with a URL for the review queue. About a minute.

### Option B — the real FFIEC records in the repository

```bash
make ingest     # the real filer-county-year extract in data/raw/
make fixture    # a synthetic snapshot with a planted signal, so screens have content
make scan
```

The real extract is 400 records from one lender in one county for one filing year,
retrieved through the CFPB HMDA Data Browser and verified slice by slice against the
aggregations endpoint. It is small, and it produces **zero findings** — which is the
correct and expected outcome, not a broken install. Look at the coverage screen to see
where the population goes.

### Option C — your own filing

```bash
make template                       # copies a CSV template into data/inbox/
# edit data/inbox/my_filing.csv
make load ARGS=--and-scan
```

In the container the equivalent is `./likewise.sh load`.

Three input layouts are recognised automatically from the header row: an FFIEC **Snapshot**
file, an FFIEC **Data Browser** or Modified LAR export, or the **template** in
`docs/templates/`. `docs/templates/likewise_lar_dictionary.csv` documents every column.

#### The loader will probably refuse your first attempt

It refuses rather than repairs, and prints a payload naming the offending rows or columns.
The most common reason, and the one that surprises everybody:

**Values must be at publication granularity.**

| Field | Required form |
| :--- | :--- |
| `loan_amount` | midpoint of a $10,000 bin (so `x mod 10000 == 5000`) |
| `property_value` | midpoint of a $10,000 bin |
| `income` | rounded to $1,000 |
| `debt_to_income_ratio` | an exact integer only in `[36, 49]`; a band otherwise |

This is not fussiness. Every comparability threshold in the product is *derived from* that
rounding — see MODELS §5. Full-precision data makes the derivation wrong and every screen
would state a bin width the values do not have.

If you genuinely need to load internal-precision data, `--internal-data` will do it and
permanently stamp the snapshot `public_record: false`. That stamp then appears on every
screen of every scan of that snapshot, forever.

---

## Step 4 — Look at it in the right order

Once a scan exists, the screens are meant to be read in this order:

1. **`/ui/scans`** — what has been loaded and run.
2. **`/ui/scans/{id}/coverage`** — read this *before* the findings. It is the denominator
   chain: how the population shrank from every record in the filing down to the handful of
   results, with the reason at each step. It also shows which parts of the book the method
   is structurally blind to.
3. **`/ui/scans/{id}/queue`** — the prioritised list.
4. **`/ui/scans/{id}/findings/{fid}`** — one denial and one comparator side by side.
5. **`/ui/scans/{id}/sweep`** and **`/controls`** — did the threshold produce the result,
   and does the engine fire on the cited reason specifically.

If the queue returns **409**, the scan has no sensitivity sweep. Run
`make sweep SCAN=scn_…`. There is deliberately no way around this: a result may not be
shown without the curve that answers "did you pick the threshold that produced this?"

---

## Everyday commands

```bash
make check                      # lint and the test suite — run before every push
make test                       # tests only
make mutate                     # the mutation gate (a few minutes)
make serve                      # run it
make scan                       # one filer-year
make sweep    SCAN=scn_...      # required before findings are servable
make controls SCAN=scn_...      # required before anything is published
make help                       # everything
```

Container equivalents: `./likewise.sh start | stop | restart | status | logs | load | scan
| shell | build`.

**Do not run `make mutate` while you are editing.** The harness rewrites source files in
place and restores them from a snapshot taken when it started, so an edit made mid-run is
silently reverted. This has cost real time more than once.

---

## Configuration

Everything is environment variables, all with local defaults.

| Variable | Default | What it does |
| :--- | :--- | :--- |
| `LIKEWISE_PRINCIPALS` | `dev-read` / `dev-write` | Bearer credential to scope map. Every route except `/health` needs one |
| `LIKEWISE_PSEUDONYM_KEY` | a development string | HMAC key behind every identifier |
| `LIKEWISE_PREREG` | unset | Pre-registration digest. While unset, every scan is labelled **exploratory** |
| `LIKEWISE_DATA` | `./data` | Root for the drop folder, snapshots and results |
| `LIKEWISE_MEMORY_MB` | `2048` | Engine memory budget. Floor 512 |
| `LIKEWISE_THREADS` | `2` | Engine threads |
| `LIKEWISE_SPEC` | `1.4.0` | Specification version used by `./likewise.sh scan` |

The first three have development defaults so it works out of the box, and all three are
wrong for a deployment.

---

## Uninstalling

```bash
./likewise.sh stop
podman rmi localhost/likewise:latest
rm -rf <this directory>
```

Nothing is installed outside the directory. For the virtual-environment route, `make clean`
and deleting the folder is the whole of it.

---

## What to read next

[PRODUCT.md](PRODUCT.md) for what it is for, then [MODELS.md](MODELS.md) for how it works.
`../docs/OPERATIONS.md` §8 has the full troubleshooting list.
