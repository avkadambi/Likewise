"""Pre-registered mutation catalogue.

PUBLISHED, because a kill rate against a private catalogue is unreviewable. Every
mutant is drawn from a real defect in this project's own review history -- which is
why it cannot be gamed by writing guard items that only test what already works.

Restoration is guaranteed in a finally block: a mutation run once corrupted a pack on
disk because cleanup was a manual step.
"""
CATALOGUE = [
    # id, file, find, replace, provenance
    ("M01", "likewise/specs.py", 'return denied - approved', 'return approved - denied',
     "polarity flip on higher_is_worse "),
    ("M02", "likewise/specs.py", 'return approved - denied\n        raise',
     'return denied - approved\n        raise', "polarity flip on higher_is_better"),
    ("M03", "likewise/core.py", 'if worse_by > threshold:', 'if worse_by >= threshold:',
     "'<' vs '<=' at the resolution boundary -- review"),
    ("M04", "likewise/core.py", 'clause2 = all(', 'clause2 = any(',
     "universal quantifier weakened to existential -- s8.1 clause 2"),
    # M05 is an EQUIVALENT mutant and is recorded as such rather than counted against
    # the kill rate. Proof: clause2 = all(outcome != "supported") is evaluated first,
    # and an informative dimension is either "not_supported" or "supported". If clause2
    # holds then every informative dimension is "not_supported", so any() and all() over
    # `informative` agree; if clause2 fails the outcome is "supported" regardless of
    # clause3. The empty case returns earlier at the `if not informative` guard.
    ("M05", "likewise/core.py", 'clause3 = any(', 'clause3 = all(',
     "EQUIVALENT: clause3 any/all agree whenever clause2 holds", "equivalent"),
    ("M06", "likewise/core.py", 'if not informative:', 'if False:',
     "empty-conjunction guard deleted; conjunction over empty set is true"),
    ("M07", "likewise/specs.py", 'return max(self.tolerance * abs(ref), self.min_absolute or 0.0)',
     'return self.tolerance * abs(ref)', "min_absolute floor dropped -- SQL reviewer finding 2a"),
    ("M08", "likewise/specs.py", 'ref = min(a, b) if self.reference == "min"',
     'ref = a if self.reference == "min"',
     "tolerance reference made asymmetric -- match(a,b) != match(b,a)"),
    ("M09", "likewise/core.py", 'mid = (i + j) / 2.0 + 1.0', 'mid = float(i + 1)',
     "midranks replaced by arbitrary tie-break -- architect drop-in defect"),
    ("M10", "likewise/core.py", 'return ("adequate" if min_p <= q else "underpowered"), min_p',
     'return "adequate", min_p', "cell power floor removed -- s8.2"),
    ("M11", "likewise/core.py", 'if av is None or dv is None:\n            incomplete = True',
     'if av is None or dv is None:\n            incomplete = False',
     "null in exact field no longer disqualifies -- s11.5"),
    ("M12", "likewise/egress.py", 'if len(key) < 32:', 'if len(key) < 0:',
     "weak pseudonym key accepted"),
    ("M13", "likewise/egress.py", 'return "LEI-" + self._mac("lei", lei)',
     'return "LEI-" + self._mac("lei", lei)[:6]',
     "24-bit LEI mask restored -- ~49% collision across the filer panel"),
    ("M14", "likewise/egress.py", 'if k in FORBIDDEN_KEYS:', 'if False:',
     "egress leak guard disabled"),
    ("M15", "likewise/specs.py", 'if not bound > g:', 'if not bound >= g:',
     "rule 3 relaxed from strict to non-strict -- the equality case is the empty band"),
    ("M16", "likewise/specs.py", 'if int(disc.get("k_min", 0)) < 5:',
     'if int(disc.get("k_min", 0)) < 0:', "k_min floor removed"),
    ("M17", "likewise/specs.py", 'if declared is not None and declared + 1e-9 < required:',
     'if False:', "decisive-threshold floor check removed -- the CLTV gate"),
    ("M18", "likewise/specs.py", 'for name in sorted(named & PROTECTED_CLASS_FIELDS):',
     'for name in sorted(set()):', "protected-class guard removed"),
    ("M19", "likewise/specs.py", 'return abs(a - b) <= self.bound(a, b)',
     'return abs(a - b) < self.bound(a, b)',
     "boundary inclusivity flipped on the tolerance test"),
    ("M20", "likewise/stats.py", 'return min(1.0, max(k, 1) / n)', 'return min(1.0, k / n)',
     "rank p-value allowed below the exact floor 1/n"),
    ("M21", "likewise/stats.py", '            if worse and not better:\n                hits += 1',
     '            if worse:\n                hits += 1',
     "clause 2 dropped from the EXACT null; the closed form and the permutation would "
     "then estimate different events and the agreement test is what notices"),
    ("M22", "likewise/scan.py", 'worse = [m for m in margins if m < -c["threshold"]]',
     'worse = [m for m in margins if m > c["threshold"]]',
     "null statistic polarity inverted -- caught during the build"),
    ("M23", "likewise/scan.py", 'margins = [(v - o) if hiw else (o - v) for o in others]',
     'margins = [(o - v) if hiw else (v - o) for o in others]',
     "null statistic orientation flipped away from Dimension.margin"),
    ("M24", "likewise/scan.py", 'if worse and not better:', 'if worse:',
     "clause 2 (no comparator strictly better) dropped from the null statistic"),
    # --- web view and the guards it depends on --------------------------------
    ("M25", "likewise/scan.py", 'if den and app and not (den & app):', 'if False:',
     "post-treatment guard deleted; a field determined by the outcome silently returns "
     "zero comparators instead of refusing"),
    ("M26", "likewise/scan.py", 'if den and app and not (den & app):',
     'if den and app and (den & app):',
     "post-treatment criterion inverted; every well-behaved field refuses"),
    ("M27", "likewise/web/format.py", 'mag = fmt_margin(dim, abs(m)).lstrip("+")',
     'mag = fmt_margin(dim, m).lstrip("+")',
     "signed margin printed to the reader; '-8.8 pp worse' states the opposite of the "
     "finding -- caught in the first render review"),
    ("M28", "likewise/api.py",
     'raise HTTPException(409, "sweep absent for this scan; findings are not servable")\n    rows',
     'pass\n    rows',
     "sweep guarantee removed from the findings route"),
    ("M29", "likewise/web/format.py", 'if f.get("cell_power") == "underpowered" or (f.get("cell_size") or 0) < 2:',
     'if False:',
     "underpowered cells get a strength bar; worst-of-two reads as evidence"),
    ("M30", "likewise/web/pages/coverage.py",
     'share = (100.0 * n / den) if den else 0.0',
     'share = (100.0 * n / total) if total else 0.0',
     "every chain row measured against the same denominator, so a marginal that is not "
     "nested inside the previous step renders as if it were"),
    ("M31", "likewise/web/format.py",
     'survives = max(0, matched - defeated - untest_matched)',
     'survives = max(0, matched - defeated)',
     "matched-but-untestable denials counted as surviving; absence of evidence reported "
     "as evidence of absence -- product requirements section 10"),
    ("M32", "likewise/web/format.py",
     '"untestable": untest_matched + unmatched,',
     '"untestable": untest_matched,',
     "denials with no comparator dropped from the unseen count, so the page understates "
     "what the product cannot see"),
    # --- the drop-folder loader (added with the inbox) -------------------------
    ("M33", "likewise/loader.py",
     'out["income"] = None if inc is None else float(inc) * INCOME_UNIT_THOUSANDS',
     'out["income"] = None if inc is None else float(inc)',
     "FFIEC income left in thousands; every income off by three orders of magnitude"),
    ("M34", "likewise/loader.py", 'if nc and not allow_nonconforming:', 'if False:',
     "publication-granularity check disabled; un-coarsened internal data loads silently "
     "behind screens that state a bin width it does not have"),
    ("M35", "likewise/loader.py", 'if physical and physical != n_raw:', 'if False:',
     "row-count reconciliation disabled; the CSV reader drops a mis-shaped row silently "
     "and the load reports success on a file it did not fully read"),
    ("M36", "likewise/loader.py", 'counts = count_domain_violations(con, conv)',
     'counts = {}',
     "value-domain check disabled; an unrecognised action_taken moves a record between "
     "populations instead of failing the load"),
    ("M44", "likewise/loader.py",
     'con.execute("SET temp_directory = " + _lit(tempfile.gettempdir()))', 'pass',
     "spill directory left at DuckDB's default of `.tmp`, relative to the working "
     "directory, so a large load scatters scratch files through the operator's project"),
    ("M37", "likewise/loader.py", 'if len(leis) != 1 or len(years) != 1:',
     'if len(leis) != 1 and len(years) != 1:',
     "two filing years in one snapshot pass when the filer is single, breaking the "
     "purity of scan_id = f(filer, year, spec, snapshot)"),
    ("M38", "likewise/web/pages/coverage.py", 'if manifest.get("public_record") is False:', 'if False:',
     "the non-public stamp stops travelling; a snapshot of un-coarsened internal data "
     "renders behind screens that state published bin widths"),
    # --- the v0.7 statistics --------------------------------------------------
    ("M45", "likewise/stats.py", 'k = sum(1 for v in values if v <= observed)',
     'k = sum(1 for v in values if v < observed)',
     "p-value reverts to the midrank form under ties; anticonservative by up to 2x on "
     "dimensions published at bin resolution"),
    ("M46", "likewise/stats.py",
     'best = min(values) if higher_is_worse else max(values)\n    return sum(1 for v in values if v == best) / n',
     'best = min(values) if higher_is_worse else max(values)\n    return 1.0 / n',
     "attainable floor reverts to 1/n, so a cell whose best value is shared by half its "
     "members is called adequately powered"),
    ("M47", "likewise/stats.py", 'if v <= 0:                       # every value tied',
     'if False:',
     "a cell with no order contributes a zero-variance term to the pooled test"),
    ("M48", "likewise/scan.py",
     '"matched_fraction": _rate(c["denials_with_matched_comparator"], c["denials_in_scope"])',
     '"matched_fraction": _rate(c["denials_with_matched_comparator"], c["denials_non_exempt"])',
     "numerator and denominator counted over different populations; the reported "
     "fraction can exceed one"),
    ("M49", "likewise/scan.py", '"denials_with_finding": len(adequate),',
     '"denials_with_finding": len(findings),',
     "cells below the power floor counted as findings, which is the headline rate the "
     "tripwire reads"),
    # --- review pass: container paths, refusal handling, engine budget ---------
    ("M51", "likewise/api.py",
     '        raise HTTPException(422, "specification refused") from exc',
     '        raise HTTPException(500, "scan failed") from exc',
     "a refused specification reported as a server crash; the structured payload is "
     "still stored but the caller is told the wrong thing"),
    ("M52", "likewise/api.py",
     'STORE = open_store(paths.store_root())',
     'STORE = open_store("./data/store")',
     "store path hardcoded again; in a container the code is read-only at /app and the "
     "volume is at /data, so every scan silently writes nowhere the operator can see"),
    ("M53", "likewise/loader.py",
     '    out_root = out_root or _paths.curated_root()\n    man = dict(extra or {})',
     '    out_root = out_root or "data/curated"\n    man = dict(extra or {})',
     "curated root hardcoded in the loader; the manifest lands beside the code instead "
     "of on the volume"),
    ("M54", "likewise/runtime.py",
     '    return max(MIN_MEMORY_MB, v)',
     '    return v',
     "engine memory floor removed; a value below DuckDB's own floor fails a three-row "
     "file and reads as a tighter budget"),
    ("M55", "likewise/loader.py",
     "    con.execute(f\"SET memory_limit='{_runtime.memory_mb()}MB'\")",
     "    pass",
     "the load path stops bounding its own memory -- the step that reads the national "
     "file sizes itself from host RAM inside a memory-capped container"),
    ("M56", "likewise/scan.py",
     '        if sig_a is not None and sig_a == sig_d:',
     '        if sig_a == sig_d:',
     "null-equality restored to the resubmission signature; two records that merely both "
     "lack an income and a property value are read as the same applicant and dropped"),
    ("M57", "likewise/specs.py",
     "        clash = sorted(tested & fields)",
     "        clash = sorted(set())",
     "rule 8 disabled; a tested dimension may be matched on again, and the finding is "
     "then a difference the matcher already declared immaterial"),
    ("M58", "likewise/specs.py",
     "        if rel <= tol:",
     "        if rel < 0:",
     "rule 9 disabled; a residual band flush with its own tolerance passes and clause 4 "
     "becomes unreachable"),
    ("M59", "likewise/core.py",
     '    if policy == "conservative" and any(not e.testable for e in entries):',
     "    if False:",
     "multi-code conservatism dropped; the claim silently weakens from 'the reason you "
     "cited' to 'at least one of the reasons you cited'"),
    # --- panel pass: precedence, the lattice split, and the version in force ---
    ("M60", "likewise/compare.py",
     "    elif a_lo == a_hi == d_lo == d_hi:",
     "    elif False:",
     "an exact tie collapses back into AMBIGUOUS; under precedence the strongest "
     "a-fortiori bind becomes indistinguishable from an unsettled record"),
    ("M61", "likewise/compare.py",
     "                      resolved=order not in (AMBIGUOUS, UNRECORDED))",
     "                      resolved=True)",
     "every comparison reports itself resolved, so a silence is indistinguishable from "
     "an identified order"),
    ("M62", "likewise/precedent.py",
     "    if unproven:\n        return Admission(precedent_id, PREMISE_UNPROVEN, cmp_t,",
     "    if False:\n        return Admission(precedent_id, PREMISE_UNPROVEN, cmp_t,",
     "silence no longer outranks admission; a precedent binds on a premise dimension the "
     "present case never established"),
    ("M63", "likewise/precedent.py",
     "    if all(c.order in (TIED, \"weakly_better\", \"strictly_better\") for c in cmp_t):",
     "    if True:",
     "every admission reported a fortiori; an admission resting on the tolerance is "
     "presented as one that does not depend on it"),
    ("M64", "likewise/precedent.py",
     "    if len(ranked) > 1 and authority(ranked[0]) == authority(ranked[1]):",
     "    if False:",
     "an untotal authority order silently picks by sort position instead of abstaining"),
    ("M65", "likewise/specs.py",
     "    if not author or author.lower() == \"unsigned\":",
     "    if False:",
     "a service may serve an unsigned specification again, with policy supplied by a "
     "Python default rather than the versioned artifact"),
    ("M66", "likewise/specs.py",
     "        if span is not None and t.tolerance >= span:",
     "        if False:",
     "rule 10 disabled; a tolerance may switch a dimension off entirely"),

    # --- replay determinism ------------------------------------------------
    ("M67", "likewise/core.py",
     "ORDER BY denied_key, approved_key\n",
     "\n",
     "the candidate query loses its total order; comparators[0] and the two max() ties "
     "resolve by DuckDB arrival order under preserve_insertion_order=false, so the same "
     "input can produce a different null and a different reported comparator"),
    ("M68", "likewise/scan.py",
     "        best = max(winners, key=lambda r: (abs(_best_dim(r).margin) /\n"
     "                                           (_best_dim(r).decisive_threshold or 1.0),\n"
     "                                           r[\"row\"][\"approved_key\"]))",
     "        best = max(winners, key=lambda r: abs(_best_dim(r).margin) /\n"
     "                   (_best_dim(r).decisive_threshold or 1.0))",
     "the reported comparator is chosen by list position whenever two comparators tie on "
     "the decisive margin, which is the common case inside a cell"),

    # --- version governance --------------------------------------------------
    ("M69", "likewise/specs.py",
     "    version = version or IN_FORCE",
     "    version = version or \"1.0.0\"",
     "every caller that does not name a version silently reverts to a specification "
     "three versions behind the one the service serves"),

    # --- extraction: silence is the safety property --------------------------
    ("M70", "extract/contract.py",
     "        if self.status in SILENT and self.value is not None:",
     "        if False:",
     "an abstention may keep its best guess; a value the extractor was not confident "
     "enough to assert reaches the gate wearing an abstention's clothes"),
    ("M71", "extract/abstain.py",
     "        if field_name not in self.floors:",
     "        if False:",
     "an uncalibrated field silently borrows another field's threshold instead of "
     "refusing"),
    ("M72", "extract/abstain.py",
     "            if not (0.0 < v <= 1.0):",
     "            if not (0.0 <= v <= 1.0):",
     "a floor of zero is accepted, making the abstention path unreachable: every "
     "reading is asserted however weak"),
    ("M73", "extract/abstain.py",
     "DEFAULT_AGGREGATION = MIN",
     "DEFAULT_AGGREGATION = MEAN",
     "span confidence stops being the weakest link, so one confident token carries a "
     "span whose other tokens were unreadable"),
    ("M74", "extract/runner.py",
     "        if conf >= floor:",
     "        if True:",
     "the floor is never consulted; the extractor asserts every reading it produces"),

    # --- round-trip: the measurement has to be able to fail -------------------
    ("M75", "extract/roundtrip.py",
     "        return None if n == 0 else self.by_verdict[CORRECT] / n",
     "        return 1.0 if n == 0 else self.by_verdict[CORRECT] / n",
     "an extractor that never speaks scores perfect precision, which is the exact trap "
     "the binding acceptance gate was written to avoid"),
    ("M76", "extract/roundtrip.py",
     "    elif r.guard_assertions:",
     "    elif False:",
     "assertions on guard records no longer fail the gate; a proximity extractor that "
     "cannot represent negation passes on aggregate"),
    ("M77", "extract/roundtrip.py",
     "        for s in scored if s.verdict in ASSERTIONS and s.confidence is not None",
     "        for s in scored if s.confidence is not None",
     "silences are fed to the threshold fitter as negatives, pushing the floor DOWN to "
     "recover coverage that was never lost"),
    ("M78", "extract/roundtrip.py",
     "    if leak:",
     "    if False:",
     "styles trained on may also be evaluated on; the headline becomes a memorisation "
     "score reported as extraction accuracy"),
    ("M79", "extract/roundtrip.py",
     "    elif r.assertions < min_assertions:",
     "    elif False:",
     "the assertion floor is gone, so a handful of lucky assertions passes the gate"),

    # --- the binding acceptance gate ------------------------------------------
    ("M80", "likewise/binding_gate.py",
     "        return (None if self.binds == 0\n"
     "                else clopper_pearson_upper(self.false_binds, self.binds, alpha))",
     "        return (0.0 if self.binds == 0\n"
     "                else clopper_pearson_upper(self.false_binds, self.binds, alpha))",
     "an engine that never binds reports a false-bind rate of zero and passes; perfect "
     "precision becomes satisfiable by abstaining on the whole docket"),
    ("M81", "likewise/binding_gate.py",
     "    elif r.guard_binds:",
     "    elif False:",
     "guard binds no longer fail the gate, so an engine that binds on a premise nobody "
     "established passes on aggregate"),
    ("M82", "likewise/binding_gate.py",
     "    elif ind_binds < min_independent_binds:",
     "    elif False:",
     "a pass on a self-authored oracle alone becomes a pass; a shared misreading of a "
     "provision between engine and oracle reads as perfect precision"),
    ("M83", "likewise/binding_gate.py",
     "        return (BIND_AGREED if ruling.controlling == oracle.expected_controlling\n"
     "                else BIND_WRONG_PRECEDENT)",
     "        return BIND_AGREED",
     "binding on the WRONG precedent counts as agreement; a decision compelled by a "
     "precedent that does not govern is scored as correct"),
    ("M84", "likewise/binding_gate.py",
     "    floor = min_binds_absolute if absolute_present else min_binds",
     "    floor = min_binds",
     "an absolute provision -- zero tolerance, no margin to absorb an error -- is held to "
     "the ordinary evidence floor"),
    ("M85", "likewise/binding_gate.py",
     "    if leak:",
     "    if False:",
     "the gate may be evaluated on the cases its tolerances were fitted to, measuring the "
     "fit rather than the engine"),

    # --- the exact binomial bound, after the overflow defect -------------------
    # Provenance: found by cross-validating against scipy.stats.beta.ppf, not by any test
    # in this suite. The CDF was summed as a direct product and raised OverflowError at
    # the sizes the assertion floor is built around. These two mutants stand guard over
    # the log-space form that replaced it.
    ("M86", "likewise/binding_gate.py",
     "            total += math.exp(lgn - math.lgamma(i + 1) - math.lgamma(n - i + 1)\n"
     "                              + i * lp + (n - i) * lq)",
     "            total += math.exp(lgn - math.lgamma(i + 1) - math.lgamma(n - i + 1)\n"
     "                              + i * lp + (n - i) * lp)",
     "the failure and success log-probabilities are the same term, so the binomial CDF is "
     "not a distribution and the returned limit is not the root it claims to be"),
    ("M87", "likewise/binding_gate.py",
     "        lp, lq = math.log(p), math.log1p(-p)",
     "        lp, lq = math.log(p), math.log1p(p)",
     "log1p(+p) for the complement: the bound drifts in the regime the bisection spends "
     "most of its time in, where p is small"),
]
