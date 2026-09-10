.PHONY: install venv dev check lint test mutate binding-gate roundtrip extract-env analysis analysis-env analysis-quick onboarding-pack docs-pack template example load ingest scan sweep controls fixture serve clean help

# Use the project virtualenv when one exists, otherwise whatever python3 is on PATH.
PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

# One filer-year, one specification version. Override on the command line.
LEI      ?= 549300MGPZBLQDIL7538
YEAR     ?= 2024
SNAPSHOT ?= hmda_2024_ffiec_2026-09-07
SPEC     ?= 1.4.0
SCAN     ?=

help:
	@grep -hE '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:[^#]*## */\t/'

install:                   ## one command: venv, dependencies, tests, mutation gate
	./install.sh $(ARGS)

template:                  ## copy the CSV template into the drop folder
	cp docs/templates/likewise_lar_template.csv data/inbox/my_filing.csv
	@echo "edit data/inbox/my_filing.csv, then: make load"
	@echo "column reference: docs/templates/likewise_lar_dictionary.csv"

example:                   ## load the example filing and scan it end to end
	cp data/examples/likewise_example_filing.csv data/inbox/
	$(PY) tools/load.py --and-scan --label "Example filing"

load:                      ## load every .csv in data/inbox into a snapshot
	$(PY) tools/load.py $(ARGS)

venv:                      ## create .venv and install pinned dependencies
	python3 -m venv .venv
	.venv/bin/python -m pip install -q --upgrade pip
	.venv/bin/python -m pip install -q -r requirements-dev.txt
	@echo "ready: $$(.venv/bin/python --version)"

dev:                       ## first run: venv, synthetic snapshot, tests
	$(MAKE) venv
	$(MAKE) fixture
	$(MAKE) test

fixture:                   ## synthetic dev snapshot with a planted signal
	$(PY) tools/make_fixture.py --n 40000 --signal 0.05 --seed 7

ingest:                    ## load the retrieved FFIEC extract in data/raw
	$(PY) tools/load.py --snapshot $(SNAPSHOT) \
	  --header data/raw/hmda_2024_fairway_sandiego/header.csv \
	  --file data/raw/hmda_2024_fairway_sandiego/denied.csv \
	  --file data/raw/hmda_2024_fairway_sandiego/originated_purchase.csv \
	  --file data/raw/hmda_2024_fairway_sandiego/originated_other.csv \
	  --manifest data/raw/hmda_2024_fairway_sandiego/manifest_seed.json \
	  --label "Fairway Independent Mortgage · San Diego County"

lint:                      ## ruff, configured to find defects rather than impose a style
	$(PY) -m ruff check .

test:                      ## unit, metamorphic and contract tests
	$(PY) -m pytest tests/ -q

docs-pack:                 ## every document plus the rendered pages, as one zip
	$(PY) tools/build_docs_pack.py --rendered $(RENDERED)

onboarding-pack:           ## the joiner pack as one tarball, docs included
	tar czf likewise-onboarding-$(shell $(PY) -c "import likewise;print(likewise.__version__)").tar.gz \
	  onboarding docs/METHOD.md docs/DESIGN.md docs/PRECEDENCE.md docs/EXTRACTION.md \
	  docs/DISTINGUISH_ENGINE.md docs/USER_GUIDE.md docs/OPERATIONS.md CONTRIBUTING.md
	@echo "built; the ../docs links resolve because docs/ travels with it"

binding-gate:              ## grade rulings against a corpus oracle: make binding-gate ORACLE=... RULINGS=...
	$(PY) tools/run_binding_gate.py --oracle $(ORACLE) --rulings $(RULINGS)

roundtrip:                 ## score an extractor against computed ground truth
	$(PY) tools/roundtrip_extractor.py --records $(RECORDS) --fields $(FIELDS)

extract-env:               ## separate venv for extraction; NOT installed by default
	python3 -m venv .venv-extract && .venv-extract/bin/pip install -r extract/requirements.txt

analysis-env:              ## the analysis stack; NOT installed in the served image
	$(PY) -m pip install -r analysis/requirements.txt

analysis:                  ## cross-validation, simulation study, EDA, figures, report
	$(PY) -m analysis.crossvalidate --json analysis/out/crossvalidation.json
	$(PY) -m analysis.simulate
	$(PY) -m analysis.eda
	$(PY) -m analysis.figures
	$(PY) -m analysis.report

analysis-quick:            ## the same studies at reduced replication, for a fast check
	$(PY) -m analysis.crossvalidate --json analysis/out/crossvalidation.json
	$(PY) -m analysis.simulate --quick
	$(PY) -m analysis.eda
	$(PY) -m analysis.figures
	$(PY) -m analysis.report

check: lint test           ## everything a change must pass before it is pushed

mutate:                    ## release gate: kill rate >= 0.90 against the published catalogue
	$(PY) tools/mutate.py

scan:                      ## run one scan; a scan id is derived from the input tuple
	$(PY) tools/run_scan.py --lei $(LEI) --year $(YEAR) --snapshot $(SNAPSHOT) \
	  --spec-version $(SPEC)

sweep:                     ## required before findings are servable: make sweep SCAN=scn_...
	$(PY) tools/run_sweep.py --scan-id $(SCAN)

controls:                  ## publication gate: make controls SCAN=scn_...
	$(PY) tools/run_controls.py --scan-id $(SCAN)

serve:                     ## API on /v1 and the web view on /ui
	$(PY) -m uvicorn likewise.api:app --port 8080

clean:
	rm -rf data/store __pycache__ .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
