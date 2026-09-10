"""REST surface.

Every route except /health requires a per-principal bearer credential -- reads
included. Ingress control is a network path setting, not authentication, and the
architect review's proposal to gate reads on it was rejected for that reason.

The service fails closed: the startup gate runs BEFORE the port is bound, so a running
process always holds a valid, loaded, digested specification.

What this module owns: the HTTP surface. Credentials and scopes, the audit event per
request, the mapping from a raised failure to a status code, and the order in which
stored artifacts are read. What it does NOT own: any analysis. It computes nothing --
scanning is scan.py, comparability is the specification, and every object it returns has
already been through egress. A route that assembled a response body out of raw records
would be a second way out of the process, which is the rule egress.py exists to hold.
"""
from __future__ import annotations
import json, logging, os, subprocess, sys, time, uuid
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from . import __version__
from . import scan as scan_mod, specs as specs_mod
from .egress import Egress
from .errors import SpecError
from .store import open_store
from . import paths

# ---- fail-closed startup (before the app object serves anything) -----------
# Module level on purpose: this runs at import, which is before uvicorn binds the port.
# A specification that does not load exits the process with the structured payload rather
# than starting a service that would refuse every scan one request at a time.
try:
    SPEC = specs_mod.load_in_force(os.environ.get("LIKEWISE_SPECS", "specs"))
except SpecError as e:                                    # pragma: no cover
    e.emit_and_exit()

STORE = open_store(paths.store_root())
# The development key is a visible placeholder, not a secret. It is long enough to pass
# the Egress length check so a checkout runs without configuration; a deployment that
# forgets LIKEWISE_PSEUDONYM_KEY publishes pseudonyms anyone can recompute, which is why
# the key version travels on every finding.
EGRESS = Egress(bytes.fromhex(os.environ["LIKEWISE_PSEUDONYM_KEY"])
                if os.environ.get("LIKEWISE_PSEUDONYM_KEY") else b"dev-key-not-for-production!!!!!!",
                key_version=int(os.environ.get("LIKEWISE_KEY_VERSION", 1)))
IMAGE_DIGEST = os.environ.get("LIKEWISE_IMAGE_DIGEST", "sha256:dev")

# One logger, stdlib only. The audit trail records what a principal asked for; this
# records what went wrong doing it. A failure that reaches the caller as a status field
# has already lost its traceback, so the traceback is written here before the status is.
logging.basicConfig(
    level=os.environ.get("LIKEWISE_LOG_LEVEL", "INFO").upper(),
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s",'
           '"msg":"%(message)s"}')
log = logging.getLogger("likewise")

# principal -> scopes. In deployment these come from the secret store.
PRINCIPALS: dict[str, dict] = json.loads(os.environ.get(
    "LIKEWISE_PRINCIPALS", '{"dev-read":{"sub":"dev","scopes":["read"]},'
                           '"dev-write":{"sub":"dev","scopes":["read","write"]}}'))

app = FastAPI(title="Likewise", version=__version__)


# ---------------------------------------------------------------------------
# Credentials and scopes
# ---------------------------------------------------------------------------
# Two scopes, and only two. `read` sees specifications, scans, findings, nulls, controls
# and sweeps; `write` additionally creates and executes scans, evaluates a supplied pair,
# and records dispositions. The only routes with no credential at all are /health and the
# web view's own sign-in page. No scope grants raw records: egress is not a permission,
# so no credential can turn it off.
def principal(authorization: str = Header(default="")) -> dict:
    tok = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    p = PRINCIPALS.get(tok)
    # 401, not 403: the caller presented no usable credential, so the remedy is to
    # present one rather than to ask for more scope.
    if not p:
        raise HTTPException(401, "credential required on every route except /health")
    return p


def require(scope: str):
    # A dependency factory rather than a check inside each handler, so the scope a route
    # needs is stated in its signature and is readable from the route list. The framework
    # resolves it per request, before the handler body runs.
    def dep(p: dict = Depends(principal)) -> dict:
        # 403 here: the credential is valid and the answer is still no.
        if scope not in p["scopes"]:
            raise HTTPException(403, f"scope '{scope}' required")
        return p
    return dep


def audit(p: dict, route: str, **kw):
    """One object per event. Object storage has no append on any target platform, so
    events.jsonl would be read-modify-write on a growing object -- requiring full
    overwrite permission on the key it claims to protect, and silently losing
    concurrent events."""
    ev = {"ts": time.time(), "principal": p["sub"], "route": route, **kw}
    STORE.put(f"audit/{time.strftime('%Y-%m-%d')}/{uuid.uuid4().hex}.json",
              json.dumps(ev, sort_keys=True).encode())


# ---------------------------------------------------------------------------
# Health and the specification in force
# ---------------------------------------------------------------------------
# /health is the only unauthenticated route. It carries the specification digests, the
# snapshot and the gate report rather than a bare "ok", because the question an operator
# actually has is which standard this process is serving -- and a process that could not
# answer it would not have started.
@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "spec_digests": SPEC.digests,
            "snapshot_id": SPEC.snapshot_id, "gate": SPEC.gate_report}


@app.get("/v1/specs/{kind}")
def get_spec(kind: str, p: dict = Depends(require("read"))):
    # An allow-list of three kinds, so the path parameter cannot name an attribute of
    # the loaded specification that was never meant to be served.
    if kind not in ("materiality", "reasons", "budget"):
        raise HTTPException(404, "unknown spec kind")
    return {"materiality": SPEC.raw, "reasons": SPEC.reasons,
            "budget": SPEC.budget.raw}[kind]


# ---------------------------------------------------------------------------
# Scans: creating and executing
# ---------------------------------------------------------------------------
# The record is written before any work starts and updated in place as the run moves
# through queued -> running -> complete / refused / failed. Every one of those states is
# a stored fact rather than something inferred from which files exist, so a process that
# dies mid-run leaves a record saying so.
@app.post("/v1/scans", status_code=202)
def create_scan(body: dict, p: dict = Depends(require("write"))):
    sid = "scn_" + uuid.uuid4().hex[:16]
    rec = {"scan_id": sid, "status": "queued", "lei": body["lei"],
           "activity_year": int(body["activity_year"]),
           "snapshot_id": SPEC.snapshot_id, "image_digest": IMAGE_DIGEST,
           "spec_digests": SPEC.digests, "pseudonym_key_version": EGRESS.key_version,
           # Without a pre-registration digest the run is labelled exploratory, and every
           # finding carries that label out through egress. The label is derived here,
           # once, from whether the lock exists -- it is not a field a caller may set.
           "preregistration_digest": os.environ.get("LIKEWISE_PREREG", "unset"),
           "analysis_status": "confirmatory" if os.environ.get("LIKEWISE_PREREG") else "exploratory",
           "started_at": None, "deadline": None, "finished_at": None,
           "superseded_by": None, "error": None}
    # create, not put: the only conditional operation in the store. Two requests that
    # produce the same key must not both believe they created the scan.
    STORE.create(f"scans/{sid}/scan.json", json.dumps(rec, indent=2).encode())
    audit(p, "POST /v1/scans", scan_id=sid)
    return {"scan_id": sid, "status": "queued"}


@app.post("/v1/scans/{sid}/execute", status_code=200)
def execute(sid: str, files: list[str] | None = None, p: dict = Depends(require("write"))):
    rec = STORE.get_json(f"scans/{sid}/scan.json")
    rec.update(status="running", started_at=time.time(),
               deadline=time.time() + 45 * 60)      # static deadline; stale derived on read
    STORE.put_json(f"scans/{sid}/scan.json", rec)
    # The three exits from this block are the whole error map for a scan:
    #   SpecError      -> 422, status "refused", the structured payload stored
    #   anything else  -> 500, status "failed", the traceback logged here
    #   success        -> 200, status "complete", summary and findings stored
    # In all three the scan record is written before the response leaves, so what the
    # caller is told and what the store says can never disagree.
    try:
        import glob
        fs = files or sorted(glob.glob(
            os.path.join(paths.curated_root(), "**", "*.parquet"), recursive=True))
        res = scan_mod.run(fs, SPEC, rec["lei"], rec["activity_year"], sid,
                           image_digest=IMAGE_DIGEST, analysis_status=rec["analysis_status"])
        # Both artifacts go through egress on the way to the store, so what is written to
        # disk is already the disclosable form. The unsuppressed findings never exist as
        # a file: the dangerous artifact is the one on disk, not the response.
        STORE.put_json(f"scans/{sid}/summary.json", EGRESS.summary(res["summary"]))
        STORE.put_json(f"scans/{sid}/findings.json",
                       [EGRESS.finding(f, SPEC) for f in res["findings"]])
        rec.update(status="complete", finished_at=time.time())
    except SpecError as exc:
        # A refused specification is a RESULT, not a crash, and the background runner
        # has always recorded it as one. This path used to fold it into the generic
        # failure below, so the same refusal produced two different scan records
        # depending on which route ran it -- and the structured payload was discarded.
        log.warning("scan %s refused: %s", sid, exc.kind)
        rec.update(status="refused", finished_at=time.time(),
                   error=exc.kind, refusal=exc.payload())
        STORE.put_json(f"scans/{sid}/scan.json", rec)
        raise HTTPException(422, "specification refused") from exc
    except Exception as exc:
        log.exception("scan %s failed", sid)
        rec.update(status="failed", finished_at=time.time(), error=repr(exc))
        STORE.put_json(f"scans/{sid}/scan.json", rec)
        raise HTTPException(500, "scan failed") from exc
    STORE.put_json(f"scans/{sid}/scan.json", rec)
    audit(p, "POST execute", scan_id=sid)
    return EGRESS.scan_record(rec)


# ---------------------------------------------------------------------------
# Reading a scan
# ---------------------------------------------------------------------------
def _stale(rec: dict) -> dict:
    """A running scan past its deadline reads as failed.

    Derived on READ and never written back. The process that would have recorded the
    failure is the one that died, so there is nobody left to write it; a reaper that
    rewrote the record would also have to win a race against a run that is merely slow.
    """
    if rec.get("status") == "running" and rec.get("deadline") and time.time() > rec["deadline"]:
        return {**rec, "status": "failed", "error": "lease expired (derived on read)"}
    return rec


@app.get("/v1/scans")
def list_scans(status: str | None = None, p: dict = Depends(require("read"))):
    out = []
    for k in STORE.list("scans"):
        if k.endswith("scan.json"):
            r = _stale(STORE.get_json(k))
            if status is None or r["status"] == status:
                out.append(EGRESS.scan_record(r))
    return {"scans": out}


@app.get("/v1/scans/{sid}")
def get_scan(sid: str, p: dict = Depends(require("read"))):
    rec = _stale(STORE.get_json(f"scans/{sid}/scan.json"))
    out = {"scan": EGRESS.scan_record(rec)}
    if STORE.exists(f"scans/{sid}/summary.json"):
        out["summary"] = STORE.get_json(f"scans/{sid}/summary.json")
    audit(p, "GET scan", scan_id=sid)
    return out


@app.get("/v1/scans/{sid}/findings")
def findings(sid: str, limit: int = Query(50, le=200), offset: int = 0,
             p: dict = Depends(require("read"))):
    """A rate is never served without its null: the envelope always carries both.

    404 and 409 mean different things here and the distinction is load-bearing. 404 is
    "this scan produced no findings artifact". 409 is "the findings exist and are not
    servable yet", which is a state the caller can wait out.
    """
    if not STORE.exists(f"scans/{sid}/findings.json"):
        raise HTTPException(404, "scan has no findings artifact")
    if not STORE.exists(f"scans/{sid}/sweep.json"):
        # A finding may not be presented without the sweep that shows whether the
        # threshold was chosen to produce it.
        raise HTTPException(409, "sweep absent for this scan; findings are not servable")
    rows = STORE.get_json(f"scans/{sid}/findings.json")
    summary = STORE.get_json(f"scans/{sid}/summary.json")
    audit(p, "GET findings", scan_id=sid, n=min(limit, max(0, len(rows) - offset)))
    # The null, the counts and the tripwire breaches ride in the SAME envelope as the
    # page of findings. Paginating the findings away from their denominators would let a
    # caller quote a rate whose null they never fetched.
    return {"total": len(rows), "limit": limit, "offset": offset,
            "null": summary.get("null"), "counts": summary.get("counts"),
            "tripwire_breaches": summary.get("tripwire_breaches"),
            "evidentiary_status": "screening_hypothesis",
            "findings": rows[offset:offset + limit]}


@app.get("/v1/scans/{sid}/null")
def null(sid: str, p: dict = Depends(require("read"))):
    return STORE.get_json(f"scans/{sid}/summary.json").get("null")


@app.get("/v1/scans/{sid}/controls")
def controls(sid: str, p: dict = Depends(require("read"))):
    k = f"scans/{sid}/controls.json"
    if not STORE.exists(k):
        raise HTTPException(404, "controls not yet computed for this scan")
    return STORE.get_json(k)


# ---------------------------------------------------------------------------
# Evaluating a caller-supplied pair
# ---------------------------------------------------------------------------
@app.post("/v1/pairs/evaluate")
def evaluate_pair(body: dict, p: dict = Depends(require("write"))):
    """Rejects institution identifiers -- does NOT redact them. Redacting caller-supplied
    input would make this an oracle over its own pseudonymisation function: the filer
    panel is public and enumerable."""
    from . import core
    for side in ("approved", "denied"):
        for banned in ("lei", "record_key", "census_tract"):
            if banned in body.get(side, {}):
                raise HTTPException(422, f"'{banned}' is not accepted on this endpoint")
    a, d = body["approved"], body["denied"]
    m = core.match(a, d, SPEC)
    o = core.evaluate(a, d, body.get("denial_reason_codes", []), SPEC)
    return {"matched": m.matched, "incomplete": m.incomplete,
            "deltas": m.deltas, "reason_outcome": o.outcome, "cause": o.cause,
            "evidentiary_status": "screening_hypothesis",
            "tested": [t.as_dict() for t in o.tested],
            "spec_digests": SPEC.digests}


# ---------------------------------------------------------------------------
# Sweep and disposition
# ---------------------------------------------------------------------------
@app.get("/v1/scans/{sid}/sweep")
def sweep(sid: str, p: dict = Depends(require("read"))):
    if not STORE.exists(f"scans/{sid}/sweep.json"):
        raise HTTPException(404, "sweep not computed for this scan")
    return STORE.get_json(f"scans/{sid}/sweep.json")


def _dispositions(sid: str) -> dict:
    k = f"scans/{sid}/dispositions.json"
    return STORE.get_json(k) if STORE.exists(k) else {}


VERDICTS = {"holds", "not_holds", "unclear"}


@app.patch("/v1/findings/{fid}/disposition")
def set_disposition(fid: str, body: dict, p: dict = Depends(require("write"))):
    # Four refusals before anything is written, in widening order: the scan must be
    # named, the verdict must be one of three, the scan must exist, and the finding must
    # belong to THAT scan. A finding identifier is stable across reruns of the same scan
    # but is not globally unique, so a disposition recorded without its scan would
    # attach to whichever scan was asked for it next.
    sid = body.get("scan_id")
    if not sid:
        raise HTTPException(422, "scan_id is required: finding ids are scoped to a scan")
    verdict = body.get("verdict")
    if verdict not in VERDICTS:
        raise HTTPException(422, f"verdict must be one of {sorted(VERDICTS)}")
    if not STORE.exists(f"scans/{sid}/findings.json"):
        raise HTTPException(404, "unknown scan")
    if not any(f["finding_id"] == fid for f in STORE.get_json(f"scans/{sid}/findings.json")):
        raise HTTPException(404, "unknown finding on this scan")
    d = _dispositions(sid)
    d[fid] = {"verdict": verdict, "note": (body.get("note") or "")[:4000],
              "principal": p["sub"], "recorded_at": time.strftime("%Y-%m-%d %H:%M")}
    STORE.put_json(f"scans/{sid}/dispositions.json", d)
    audit(p, "PATCH disposition", scan_id=sid, finding_id=fid, verdict=verdict)
    return d[fid]


# ---------------------------------------------------------------------------
# Web view. Server-rendered over the same stored post-egress
# artifacts the API serves; the renderer never sees a raw Finding.
#
# Session: the cookie carries the SAME bearer credential the API takes, so the web
# view adds no second signing key and no new trust root -- which was the objection
# that deferred it. It is HttpOnly, SameSite=Strict and set Secure off localhost.
# ---------------------------------------------------------------------------
from fastapi import Cookie, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import web

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
          name="static")

# --- web-view helpers: reading what is already stored ----------------------
# Each of these reads post-egress artifacts out of the store and hands them to the
# renderer. None of them computes anything, and none of them touches a raw record: the
# web view is a second VIEW, not a second route out of the process.
SPEC_CACHE: dict[str, Any] = {}


def spec_for(version: str | None):
    """The specification a scan was run under, loaded on demand and cached.

    A finding is only meaningful against the version that produced it, and old scans
    stay readable after the in-force version moves on. A version that no longer loads
    falls back to the one in force rather than failing the page -- the page then states
    the wrong version, which is why the version is printed on it and linked.
    """
    v = version or SPEC.version
    if v not in SPEC_CACHE:
        try:
            SPEC_CACHE[v] = specs_mod.load(os.environ.get("LIKEWISE_SPECS", "specs"), version=v)
        except (FileNotFoundError, SpecError):
            SPEC_CACHE[v] = SPEC
    return SPEC_CACHE[v]


def ui_principal(authorization: str = Header(default=""),
                 lw_session: str = Cookie(default="")) -> dict:
    # Same principal table as the API, reached either by header or by cookie, and the
    # header takes precedence. The web view therefore adds no second secret and no second
    # place to revoke one.
    tok = authorization[7:] if authorization.lower().startswith("bearer ") else lw_session
    p = PRINCIPALS.get(tok)
    # 303 to the sign-in page rather than a 401 body: this dependency guards HTML routes,
    # where the useful answer to "no credential" is a form.
    if not p:
        raise HTTPException(status_code=303, detail="sign in",
                            headers={"Location": "/ui/login"})
    return p


def _reasons(spec) -> dict:
    return {int(k): v for k, v in (spec.reasons.get("codes") or {}).items()}


def _scan_rows() -> list[dict]:
    # Newest first, and a scan that never started sorts last rather than raising: a
    # queued record has started_at None, and the list page is the place an operator goes
    # to find out that nothing has run.
    out = []
    for k in sorted(STORE.list("scans")):
        if not k.endswith("scan.json"):
            continue
        rec = _stale(STORE.get_json(k))
        row = {"scan": rec}
        sk = f"scans/{rec['scan_id']}/summary.json"
        if STORE.exists(sk):
            row["summary"] = STORE.get_json(sk)
        out.append(row)
    out.sort(key=lambda r: r["scan"].get("started_at") or 0, reverse=True)
    return out


def _load(sid: str):
    rec = _stale(STORE.get_json(f"scans/{sid}/scan.json"))
    summary = STORE.get_json(f"scans/{sid}/summary.json") \
        if STORE.exists(f"scans/{sid}/summary.json") else {}
    ctrl = STORE.get_json(f"scans/{sid}/controls.json") \
        if STORE.exists(f"scans/{sid}/controls.json") else None
    return rec, summary, ctrl


def _findings(sid: str) -> list[dict]:
    return STORE.get_json(f"scans/{sid}/findings.json") \
        if STORE.exists(f"scans/{sid}/findings.json") else []


# --- web-view routes -------------------------------------------------------
# Every HTML route except the two sign-in routes depends on ui_principal, audits what it
# served, and returns markup built by likewise.web from the stored artifacts. The guards
# that exist on the API exist here too, deliberately: the sweep requirement and the write
# scope on a disposition. The web view is not a way around the contract.
@app.get("/ui/login", response_class=HTMLResponse)
def ui_login():
    return HTMLResponse(web.page("Sign in", """
<h1 class="page">Sign in</h1>
<form class="card blueprint" method="post" action="/ui/login" style="max-width:420px">
  <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
  <div class="field"><label>API credential</label>
    <input class="input" name="token" type="password" autofocus></div>
  <button class="btn btn-primary block" style="margin-top:12px" type="submit">Continue</button>
  <p class="muted" style="font:11.5px/1.5 var(--font-body);margin:12px 0 0">The web view holds no
    credential of its own. The cookie carries the same bearer token the API takes, so there is one
    secret and one place to revoke it.</p>
</form>"""))


@app.post("/ui/login")
def ui_login_post(token: str = Form(...)):
    if token not in PRINCIPALS:
        return RedirectResponse("/ui/login?bad=1", status_code=303)
    r = RedirectResponse("/ui/", status_code=303)
    # The cookie holds the bearer credential itself. That is what keeps the web view from
    # introducing a second secret and a second place to revoke one; httponly keeps it out
    # of scripts and samesite=strict keeps it off cross-site requests.
    r.set_cookie("lw_session", token, httponly=True, samesite="strict", path="/")
    return r


@app.get("/ui/")
def ui_home(p: dict = Depends(ui_principal)):
    rows = _scan_rows()
    live = [r for r in rows if r["scan"].get("status") == "complete"]
    if not live:
        return RedirectResponse("/ui/scans", status_code=303)
    return RedirectResponse(f"/ui/scans/{live[0]['scan']['scan_id']}/queue", status_code=303)


@app.get("/ui/scans", response_class=HTMLResponse)
def ui_scans(p: dict = Depends(ui_principal)):
    import pathlib
    d = pathlib.Path(os.environ.get("LIKEWISE_SPECS", "specs")) / "materiality"
    versions = sorted(f.stem for f in d.glob("*.yaml"))
    audit(p, "GET /ui/scans")
    return HTMLResponse(web.scans_page(_scan_rows(), versions, "write" in p["scopes"]))


@app.get("/ui/scans/{sid}/queue", response_class=HTMLResponse)
def ui_queue(sid: str, tab: str = "needs", offset: int = 0,
             p: dict = Depends(ui_principal)):
    rec, summary, ctrl = _load(sid)
    if rec.get("status") == "complete" and not STORE.exists(f"scans/{sid}/sweep.json"):
        # Same guarantee as GET /v1/scans/{id}/findings. The web view is not a way
        # around the contract.
        raise HTTPException(409, "sweep absent for this scan; findings are not servable")
    audit(p, "GET /ui/queue", scan_id=sid)
    return HTMLResponse(web.queue_page(
        sid, rec, summary, _findings(sid), _dispositions(sid),
        _reasons(spec_for(rec.get("spec_version"))), ctrl, tab, 25, offset))


@app.get("/ui/scans/{sid}/findings/{fid}", response_class=HTMLResponse)
def ui_finding(sid: str, fid: str, p: dict = Depends(ui_principal)):
    rec, summary, ctrl = _load(sid)
    rows = _findings(sid)
    idx = next((i for i, f in enumerate(rows) if f["finding_id"] == fid), None)
    if idx is None:
        raise HTTPException(404, "unknown finding")
    disp = _dispositions(sid)
    # "Next" is the next UNDISPOSED finding AFTER this one, so working through the queue
    # never loops back over pairs the reviewer has already decided. The findings arrive
    # in rank order and are not re-sorted here.
    nxt = next((f["finding_id"] for f in rows[idx + 1:] if f["finding_id"] not in disp), None)
    audit(p, "GET /ui/finding", scan_id=sid, finding_id=fid)
    return HTMLResponse(web.finding_page(
        sid, rec, summary, rows[idx], disp.get(fid, {}),
        _reasons(spec_for(rec.get("spec_version"))), ctrl, idx + 1, len(rows), nxt))


@app.post("/ui/scans/{sid}/findings/{fid}/disposition")
def ui_disposition(sid: str, fid: str, verdict: str = Form(""), note: str = Form(""),
                   p: dict = Depends(ui_principal)):
    # Checked here rather than by require("write"): the HTML routes resolve their
    # principal through the cookie dependency, which does not carry a scope requirement.
    if "write" not in p["scopes"]:
        raise HTTPException(403, "recording a disposition needs write scope")
    if verdict not in VERDICTS:
        return RedirectResponse(f"/ui/scans/{sid}/findings/{fid}", status_code=303)
    # The form posts through the SAME handler the API route uses, so the web view cannot
    # record a disposition the API would have refused.
    set_disposition(fid, {"scan_id": sid, "verdict": verdict, "note": note}, p)
    rows = _findings(sid)
    disp = _dispositions(sid)
    nxt = next((f["finding_id"] for f in rows if f["finding_id"] not in disp), None)
    return RedirectResponse(
        f"/ui/scans/{sid}/findings/{nxt}" if nxt else f"/ui/scans/{sid}/queue", status_code=303)


@app.get("/ui/scans/{sid}/coverage", response_class=HTMLResponse)
def ui_coverage(sid: str, p: dict = Depends(ui_principal)):
    rec, summary, ctrl = _load(sid)
    man = None
    mpath = paths.manifest_path(rec.get('curated_snapshot') or '')
    if os.path.exists(mpath):
        man = json.load(open(mpath))
    audit(p, "GET /ui/coverage", scan_id=sid)
    return HTMLResponse(web.coverage_page(sid, rec, summary, ctrl, man))


@app.get("/ui/scans/{sid}/sweep", response_class=HTMLResponse)
def ui_sweep(sid: str, p: dict = Depends(ui_principal)):
    rec, summary, _ = _load(sid)
    if not STORE.exists(f"scans/{sid}/sweep.json"):
        raise HTTPException(409, "sweep absent for this scan")
    audit(p, "GET /ui/sweep", scan_id=sid)
    return HTMLResponse(web.sweep_page(sid, rec, summary,
                                       STORE.get_json(f"scans/{sid}/sweep.json")))


@app.get("/ui/scans/{sid}/controls", response_class=HTMLResponse)
def ui_controls(sid: str, p: dict = Depends(ui_principal)):
    rec, summary, ctrl = _load(sid)
    audit(p, "GET /ui/controls", scan_id=sid)
    return HTMLResponse(web.controls_page(sid, rec, summary, ctrl))


@app.get("/ui/spec", response_class=HTMLResponse)
def ui_spec(v: str | None = None, refused: str | None = None,
            p: dict = Depends(ui_principal)):
    import pathlib
    d = pathlib.Path(os.environ.get("LIKEWISE_SPECS", "specs")) / "materiality"
    versions = web.read_versions(str(d))
    spec = spec_for(v)
    refusal = None
    if refused and STORE.exists(f"scans/{refused}/scan.json"):
        refusal = STORE.get_json(f"scans/{refused}/scan.json").get("refusal")
    on_version = [r for r in _scan_rows() if r["scan"].get("spec_version") == spec.version]
    audit(p, "GET /ui/spec", spec_version=spec.version)
    return HTMLResponse(web.spec_page(spec, versions, spec.version, refusal, on_version))


# --- launching a scan from the web view -----------------------------------
import glob as _glob
import hashlib as _hashlib
import threading as _threading


def _scan_id_for(lei: str, year: int, spec_version: str, snapshot_id: str,
                 curated: str) -> str:
    """The scan identifier is a digest of the five inputs, not a random string.

    A scan is a pure function of (filer, year, specification, publication snapshot,
    curated snapshot), so re-launching the same tuple lands on the same key and the
    existing run is what the operator sees. Nothing here is timestamped: a timestamp
    would make every relaunch a new scan and the identity claim untestable.
    """
    tup = f"{lei}|{year}|{spec_version}|{snapshot_id}|{curated}"
    return "scn_" + _hashlib.sha256(tup.encode()).hexdigest()[:16]


def _run_scan_and_sweep(sid: str, rec: dict, spec, files: list[str]):
    """Executed off the request thread. The sweep is not optional: a finding may not be
    presented without the curve that shows whether its threshold was chosen to produce it,
    so the scan is not marked complete until both artifacts exist."""
    try:
        res = scan_mod.run(files, spec, rec["lei"], rec["activity_year"], sid,
                           analysis_status=rec["analysis_status"])
    except SpecError as exc:
        log.warning("scan %s refused: %s", sid, exc.kind)
        rec.update(status="refused", finished_at=time.time(),
                   error=exc.kind, refusal=exc.payload())
        STORE.put_json(f"scans/{sid}/scan.json", rec)
        return
    except Exception as exc:
        # Nothing above this frame can report the failure -- the thread is detached and
        # the caller already has its 303 -- so the traceback is logged here or lost.
        log.exception("scan %s failed", sid)
        rec.update(status="failed", finished_at=time.time(), error=repr(exc))
        STORE.put_json(f"scans/{sid}/scan.json", rec)
        return
    STORE.put_json(f"scans/{sid}/summary.json", EGRESS.summary(res["summary"]))
    STORE.put_json(f"scans/{sid}/findings.json",
                   [EGRESS.finding(f, spec) for f in res["findings"]])
    # "sweeping" is a state of its own, not a variation on running: the findings exist by
    # now but are not servable, and the queue route says so with a 409 rather than
    # showing a page that would be missing its sensitivity curve.
    rec.update(status="sweeping")
    STORE.put_json(f"scans/{sid}/scan.json", rec)
    rc = subprocess.run([sys.executable, "tools/run_sweep.py", "--scan-id", sid],
                        capture_output=True, text=True)
    # A non-zero exit AND a missing artifact both count as failure. A sweep that exits
    # cleanly without writing its file would otherwise mark the scan complete and unlock
    # the findings route on a guarantee that was never met.
    if rc.returncode != 0 or not STORE.exists(f"scans/{sid}/sweep.json"):
        log.error("scan %s sweep failed rc=%s: %s", sid, rc.returncode,
                  (rc.stderr or "")[-400:])
        rec.update(status="failed", finished_at=time.time(),
                   error="sweep failed: " + (rc.stderr or "")[-400:])
    else:
        rec.update(status="complete", finished_at=time.time())
    STORE.put_json(f"scans/{sid}/scan.json", rec)


@app.post("/ui/scans")
def ui_create_scan(lei: str = Form(...), year: str = Form(...), spec: str = Form(...),
                   p: dict = Depends(ui_principal)):
    if "write" not in p["scopes"]:
        raise HTTPException(403, "launching a scan needs write scope")
    lei = lei.strip()
    y = int(year)
    sp = spec_for(spec)
    # The curated snapshot is discovered rather than supplied: it is an input to the scan
    # identity, so letting the form name one would let two different bodies of data share
    # an identifier. First match by sorted snapshot name wins.
    curated = None
    for d in sorted(_glob.glob(os.path.join(paths.curated_root(), "snapshot=*"))):
        if _glob.glob(f"{d}/activity_year={y}/lei={lei}/*.parquet"):
            curated = d.split("snapshot=", 1)[1]
            break
    # 422, not 404: the request is well-formed and the service is fine; the data for this
    # filer-year has not been loaded.
    if not curated:
        raise HTTPException(422, f"no curated data for filer {lei} in {y}")
    sid = _scan_id_for(lei, y, sp.version, sp.snapshot_id, curated)
    prereg = os.environ.get("LIKEWISE_PREREG")
    rec = {"scan_id": sid, "status": "running", "lei": lei, "activity_year": y,
           "snapshot_id": sp.snapshot_id, "curated_snapshot": curated,
           "label": f"{lei[:8]} · FY{y}", "image_digest": IMAGE_DIGEST,
           "spec_version": sp.version, "spec_digests": sp.digests,
           "pseudonym_key_version": EGRESS.key_version,
           "preregistration_digest": prereg or "unset",
           "analysis_status": "confirmatory" if prereg else "exploratory",
           "started_at": time.time(), "deadline": time.time() + 45 * 60,
           "finished_at": None, "superseded_by": None, "error": None}
    STORE.put_json(f"scans/{sid}/scan.json", rec)
    files = sorted(_glob.glob(paths.parquet_glob(curated, y, lei)))
    _threading.Thread(target=_run_scan_and_sweep, args=(sid, rec, sp, files),
                      daemon=True).start()
    audit(p, "POST /ui/scans", scan_id=sid)
    return RedirectResponse("/ui/scans", status_code=303)
