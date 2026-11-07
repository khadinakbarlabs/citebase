#!/usr/bin/env python3
"""AI-citation measurement loop: frozen prompt panel -> repeat runs -> Recommendation Share -> experiments.

  init DIR                                  create panel.csv, runs.csv, experiments.csv
  panel add DIR --prompt TEXT --type T      T = awareness | consideration | brand | control
                                            (--brand NAME warns if a non-brand question names the brand)
  panel list DIR | panel freeze DIR         freeze locks the panel (edits afterwards are refused)
  ingest DIR --snapshot NAME --file F       append run results (JSON list or CSV) to runs.csv
  experiment add|list|close DIR ...         log what you changed and when to re-measure
  report DIR [--baseline S] [--current S] [--json] [--brand NAME --domain D]

Recommendation Share (RS) = share of (prompt x engine x repeat) answers in which the brand is
actively recommended, averaged per prompt over the BUYING questions (awareness + consideration).
Questions that already name the brand ("brand" type) are reported apart as a reputation check.
Repeats of one prompt are correlated, so confidence intervals resample PROMPTS (bootstrap), not runs.
Control prompts (where the brand should not be recommended) estimate false positives and drift.
Experiment verdicts compare target prompts with the other prompts (difference-in-differences) and are
only given for changes made between the two rounds.
That is evidence, not proof: overlapping changes and engine drift confound it. Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import sys
from collections import defaultdict

PANEL_COLS = ["prompt_id", "prompt", "type", "topic"]
RUN_COLS = ["run_id", "snapshot", "date", "prompt_id", "platform", "repeat", "mentioned", "cited",
            "recommended", "position", "competitors", "cited_domains", "metric_version"]
EXP_COLS = ["exp_id", "date", "action", "mechanism", "target_prompt_ids", "url", "status", "recheck_after", "notes"]
TYPES = ("awareness", "consideration", "brand", "control")
MECHANISMS = ("onpage", "fact-page", "listicle", "review-site", "press", "reddit", "youtube", "directory",
              "podcast", "creator", "schema", "llms-txt", "technical", "other")
ALIASES = {"brand_mentioned": "mentioned", "brand_cited": "cited", "brand_recommended": "recommended"}
TRUE, FALSE = {"1", "true", "yes", "y", "t"}, {"0", "false", "no", "n", "f", ""}
Z95 = 1.959964
BOOT_N = 2000
MIN_PROMPTS = 20
MIN_REPEATS = 3
MIN_CONTROLS = 5
# metric_version 1 (rounds saved before this field existed): any non-negative mention counted as a
# recommendation and brand-name questions sat inside the headline. 2: buying questions only, stricter rule.
METRIC_VERSION = 2
DISCOVERY_TYPES = ("awareness", "consideration")
RULE_OF_THREE = 3.0  # upper bound on a rate after 0 hits in n units (about 95%)
MIN_ACTIONABLE = 0.10  # a change smaller than this (10 points) is not worth acting on
DETECT_FACTOR = 2.8 / 3.92  # 80% power: smallest visible change is about 2.8 SE, the 95% half-width is 1.96 SE
DRIFT_EPS = 0.005  # half a point: below this, movement in other prompts is treated as noise
MIN_PEERS = 3  # fewest comparison prompts an experiment needs after leaving out other changes' targets
MIN_TARGETS = 3  # fewer targeted prompts than this cannot separate a real change from noise


def path(d: str, name: str) -> str:
    return os.path.join(d, name)


def read_csv(p: str) -> list[dict]:
    try:
        with open(p, newline="") as fh:
            return list(csv.DictReader(fh))
    except FileNotFoundError:
        return []


def write_csv(p: str, cols: list[str], rows: list[dict]) -> None:
    with open(p, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def wilson(k: int, n: int) -> tuple[float, float, float]:
    """Wilson 95% interval for k successes in n pooled trials. Returns (rate, low, high)."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    denom = 1 + Z95 ** 2 / n
    centre = (p + Z95 ** 2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def boot_ci(values: list[float], seed: int = 7, lo: float = 0.0, hi: float = 1.0) -> tuple[float, float, float] | None:
    """Mean and 95% percentile-bootstrap interval over the given units (prompts).

    A bootstrap collapses to a single point when every unit has the same result, which would print a false
    "exactly 0%". Those cases get a rule-of-three bound instead: n units that all sit at the floor (or ceiling, or,
    for changes with lo < 0 < hi, at zero) cannot rule out a true value up to about 3/n away. One unit tells
    nothing, so it gets the full range [lo, hi].
    """
    if not values:
        return None
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, lo, hi
    if max(values) == min(values):
        v, bound = values[0], min(RULE_OF_THREE / n, hi - lo)
        if v == lo:
            return mean, mean, min(hi, mean + bound)
        if v == hi:
            return mean, max(lo, mean - bound), mean
        # Identical values that are not at a bound (including zero change): the bootstrap would collapse to a
        # zero-width interval, so show the same three-over-n reach on both sides.
        return mean, max(lo, mean - bound), min(hi, mean + bound)
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(BOOT_N))
    return mean, means[int(0.025 * BOOT_N)], means[int(0.975 * BOOT_N) - 1]


def parse_date(value) -> dt.date | None:
    """YYYY-MM-DD (a longer timestamp is cut to its date). None when the text is not a date."""
    try:
        return dt.date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def smallest_visible(low: float, high: float) -> int | None:
    """Smallest change (in whole points) a panel can reliably see, from the width of its 95% interval."""
    if high <= low:
        return None
    return max(1, round(100 * DETECT_FACTOR * (high - low)))


def to_bool(value) -> int:
    text = str(value).strip().lower()
    if text in TRUE:
        return 1
    if text in FALSE:
        return 0
    raise ValueError(f"not a yes/no value: {value!r}")


def load_panel(d: str) -> dict[str, dict]:
    return {r["prompt_id"]: r for r in read_csv(path(d, "panel.csv"))}


def panel_hash(panel: dict[str, dict]) -> str:
    lines = sorted(f"{r['prompt_id']}|{r['prompt']}|{r['type']}" for r in panel.values())
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def lock_info(d: str) -> dict | None:
    try:
        with open(path(d, "panel.lock.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def brand_terms(brand: dict | None) -> list[str]:
    """Lower-case words that would give the brand away in a question: name, aliases, domain and its main label.
    Names shorter than 3 characters are skipped, because they would match ordinary words."""
    brand = brand or {}
    terms = [brand.get("name")] + list(brand.get("aliases") or [])
    domain = re.sub(r"^[a-z]+://", "", str(brand.get("domain") or "").strip().lower())
    domain = domain.split("/")[0].removeprefix("www.")
    if "." in domain:
        terms += [domain, domain.split(".")[0]]
    seen: list[str] = []
    for t in terms:
        text = " ".join(str(t or "").lower().split())
        if len(text) >= 3 and text not in seen and (text != domain.split(".")[0] or len(text) >= 4):
            seen.append(text)
    return seen


def panel_warnings(panel, brand: dict | None) -> list[str]:
    """Plain warnings (never errors) for questions that name the brand when they should not.

    Awareness and consideration questions must not name the brand, or the share is inflated; control questions
    that name it will be 'recommended' and look like false positives. Brand-type questions may name it.
    `panel` is a list of prompt rows or a dict keyed by prompt_id."""
    terms = brand_terms(brand)
    if not terms:
        return []
    patterns = [re.compile(r"(?<![a-z0-9])" + re.escape(t).replace(r"\ ", r"\s+") + r"(?![a-z0-9])") for t in terms]
    rows = list(panel.values()) if isinstance(panel, dict) else list(panel)
    hits: dict[str, list[str]] = {"discovery": [], "control": []}
    for row in rows:
        group = prompt_group(str(row.get("type", "")))
        text = " ".join(str(row.get("prompt", "")).lower().split())
        if group in hits and any(pt.search(text) for pt in patterns):
            hits[group].append(str(row.get("prompt_id", "")))
    out = []
    if hits["discovery"]:
        out.append(f"{len(hits['discovery'])} buying question(s) name the brand ({', '.join(hits['discovery'][:8])}). "
                   "Rewrite them without the brand name, or move them to the brand type, otherwise the "
                   "Recommendation Share will be overstated.")
    if hits["control"]:
        out.append(f"{len(hits['control'])} control question(s) name the brand ({', '.join(hits['control'][:8])}). "
                   "Control questions should be about unrelated topics, or they will look like false positives.")
    return out


def brand_from_args(a) -> dict | None:
    name = getattr(a, "brand", "") or ""
    if not name:
        return None
    aliases = [x.strip() for x in (getattr(a, "alias", "") or "").split(",") if x.strip()]
    return {"name": name, "domain": getattr(a, "domain", "") or "", "aliases": aliases}


def cmd_init(a) -> int:
    os.makedirs(a.dir, exist_ok=True)
    for name, cols in (("panel.csv", PANEL_COLS), ("runs.csv", RUN_COLS), ("experiments.csv", EXP_COLS)):
        if not os.path.exists(path(a.dir, name)):
            write_csv(path(a.dir, name), cols, [])
    print(f"ready: {a.dir}")
    return 0


def cmd_panel(a) -> int:
    panel = load_panel(a.dir)
    if a.action == "list":
        for r in panel.values():
            print(f"{r['prompt_id']}  [{r['type']}]  {r['prompt']}")
        print(f"{len(panel)} prompts; frozen: {bool(lock_info(a.dir))}")
        return 0
    if a.action == "freeze":
        if not panel:
            raise SystemExit("Panel is empty.")
        for w in panel_warnings(panel, brand_from_args(a)):
            print(f"WARNING: {w}", file=sys.stderr)
        info = {"frozen_at": dt.date.today().isoformat(), "sha256": panel_hash(panel), "n_prompts": len(panel)}
        with open(path(a.dir, "panel.lock.json"), "w") as fh:
            json.dump(info, fh, indent=1)
        print(f"frozen {len(panel)} prompts ({info['sha256'][:12]}). Do not edit; start a new workspace for a new panel.")
        return 0
    if lock_info(a.dir):
        raise SystemExit("Panel is frozen: results are only comparable while the prompts stay identical.")
    if a.type not in TYPES:
        raise SystemExit(f"--type must be one of {', '.join(TYPES)}")
    text = " ".join((a.prompt or "").split())
    if not text:
        raise SystemExit("--prompt is required")
    if any(r["prompt"].lower() == text.lower() for r in panel.values()):
        raise SystemExit("Prompt already in the panel.")
    pid = f"p{len(panel) + 1:03d}"
    panel[pid] = {"prompt_id": pid, "prompt": text, "type": a.type, "topic": a.topic or ""}
    write_csv(path(a.dir, "panel.csv"), PANEL_COLS, list(panel.values()))
    for w in panel_warnings([panel[pid]], brand_from_args(a)):
        print(f"WARNING: {w}", file=sys.stderr)
    print(f"added {pid}")
    return 0


def normalise_run(raw: dict, panel: dict[str, dict], snapshot: str, n: int) -> dict:
    row = {ALIASES.get(k, k): v for k, v in raw.items()}
    pid = str(row.get("prompt_id", "")).strip()
    if pid not in panel:
        raise ValueError(f"unknown prompt_id {pid!r}")
    platform = str(row.get("platform", "")).strip().lower()
    if not platform:
        raise ValueError("platform is required")
    rec = to_bool(row.get("recommended", 0))
    version = int(row.get("metric_version") or METRIC_VERSION)
    if version < 1:
        raise ValueError("metric_version must be 1 or higher")
    return {"run_id": f"r{n:05d}", "snapshot": snapshot, "date": row.get("date") or dt.date.today().isoformat(),
            "prompt_id": pid, "platform": platform, "repeat": int(row.get("repeat") or 1),
            "mentioned": max(to_bool(row.get("mentioned", 0)), rec), "cited": to_bool(row.get("cited", 0)),
            "recommended": rec, "position": row.get("position", ""),
            "competitors": row.get("competitors", ""), "cited_domains": row.get("cited_domains", ""),
            "metric_version": version}


def cmd_ingest(a) -> int:
    panel, runs = load_panel(a.dir), read_csv(path(a.dir, "runs.csv"))
    if not lock_info(a.dir):
        raise SystemExit("Freeze the panel before ingesting runs: python3 citation_loop.py panel freeze DIR")
    with open(a.file, newline="") as fh:
        incoming = json.load(fh) if a.file.endswith(".json") else list(csv.DictReader(fh))
    if not isinstance(incoming, list):
        raise SystemExit("Input must be a list of run objects.")
    seen = {(r["snapshot"], r["prompt_id"], r["platform"], str(r["repeat"])) for r in runs}
    added = 0
    for i, raw in enumerate(incoming, 1):
        try:
            row = normalise_run(raw, panel, a.snapshot, len(runs) + added + 1)
        except (ValueError, TypeError) as err:
            raise SystemExit(f"row {i}: {err}")
        key = (row["snapshot"], row["prompt_id"], row["platform"], str(row["repeat"]))
        if key in seen:
            raise SystemExit(f"row {i}: duplicate {key}")
        seen.add(key)
        runs.append(row)
        added += 1
    write_csv(path(a.dir, "runs.csv"), RUN_COLS, runs)
    print(f"ingested {added} runs into snapshot '{a.snapshot}'")
    return 0


def cmd_experiment(a) -> int:
    p, rows = path(a.dir, "experiments.csv"), read_csv(path(a.dir, "experiments.csv"))
    if a.action == "list":
        for r in rows:
            print(f"{r['exp_id']}  {r['status']:8} {r['mechanism']:11} {r['date']}  recheck {r['recheck_after']}  {r['action']}")
        return 0
    if a.action == "close":
        hit = [r for r in rows if r["exp_id"] == a.exp_id]
        if not hit:
            raise SystemExit(f"No experiment {a.exp_id}")
        hit[0]["status"] = a.status
        write_csv(p, EXP_COLS, rows)
        return 0
    if a.mechanism not in MECHANISMS:
        raise SystemExit(f"--mechanism must be one of {', '.join(MECHANISMS)}")
    panel = load_panel(a.dir)
    targets = [t.strip() for t in (a.targets or "").split(",") if t.strip()]
    unknown = [t for t in targets if t not in panel]
    if unknown or not targets:
        raise SystemExit(f"--targets must list panel prompt ids; unknown: {unknown or 'none given'}")
    rows.append({"exp_id": f"e{len(rows) + 1:03d}", "date": a.date or dt.date.today().isoformat(), "action": a.action_text,
                 "mechanism": a.mechanism, "target_prompt_ids": ",".join(targets), "url": a.url or "",
                 "status": "shipped", "recheck_after": a.recheck_after or
                 (dt.date.today() + dt.timedelta(days=30)).isoformat(), "notes": a.notes or ""})
    write_csv(p, EXP_COLS, rows)
    print(f"logged {rows[-1]['exp_id']}; re-measure after {rows[-1]['recheck_after']}")
    return 0


def prompt_group(ptype: str) -> str:
    """'control', 'brand' (questions that already name the brand) or 'discovery' (buying questions)."""
    return ptype if ptype in ("control", "brand") else "discovery"


def on_platform(row: dict, platform) -> bool:
    """platform may be None (all engines), one engine name, or a collection of engine names."""
    if platform is None:
        return True
    return row["platform"] in platform if isinstance(platform, (set, frozenset, list, tuple)) else row["platform"] == platform


def prompt_props(runs: list[dict], panel: dict, snapshot: str, platform, controls: bool,
                 group: str | None = None) -> dict[str, float]:
    """Per-prompt recommendation rate (mean over engines x repeats) for one snapshot.
    Default group: buying questions (or controls when controls=True). Pass group='brand' for brand questions."""
    want = group or ("control" if controls else "discovery")
    acc: dict[str, list[int]] = defaultdict(list)
    for r in runs:
        if r["snapshot"] != snapshot or not on_platform(r, platform):
            continue
        if prompt_group(panel[r["prompt_id"]]["type"]) == want:
            acc[r["prompt_id"]].append(int(r["recommended"]))
    return {pid: sum(v) / len(v) for pid, v in acc.items()}


def pooled(runs: list[dict], panel: dict, snapshot: str, platform, field: str) -> tuple[int, int]:
    rows = [r for r in runs if r["snapshot"] == snapshot and on_platform(r, platform)
            and prompt_group(panel[r["prompt_id"]]["type"]) == "discovery"]
    return sum(int(r[field]) for r in rows), len(rows)


def run_version(row: dict) -> int:
    try:
        return int(row.get("metric_version") or 1)  # rounds saved before the field existed are version 1
    except (TypeError, ValueError):
        return 1


def snapshot_version(runs: list[dict], snapshot: str) -> int:
    """Oldest metric version among a round's rows: one old row makes the whole round 'older'."""
    versions = [run_version(r) for r in runs if r["snapshot"] == snapshot]
    return min(versions) if versions else METRIC_VERSION


def snapshot_summary(runs, panel, snapshot, platform) -> dict | None:
    """Headline Recommendation Share over buying questions, plus a separate brand-name 'reputation check'."""
    props = prompt_props(runs, panel, snapshot, platform, controls=False)
    if not props:
        return None
    ci = boot_ci(list(props.values()))
    ctrl = list(prompt_props(runs, panel, snapshot, platform, controls=True).values())
    brand = list(prompt_props(runs, panel, snapshot, platform, controls=False, group="brand").values())
    rep_ci = boot_ci(brand) if brand else None
    version = snapshot_version(runs, snapshot)
    out = {"prompts": len(props), "recommendation_share": ci[0], "rs_low": ci[1], "rs_high": ci[2],
           "control_false_positive": (sum(ctrl) / len(ctrl)) if ctrl else None,
           "reputation_share": rep_ci[0] if rep_ci else None, "reputation_low": rep_ci[1] if rep_ci else None,
           "reputation_high": rep_ci[2] if rep_ci else None, "reputation_prompts": len(brand),
           "metric_version": version, "older_metric": version < METRIC_VERSION,
           "headline": (f"AI recommends you in {pct(ci[0])} of buying questions "
                        f"(likely range {pct(ci[1])} to {pct(ci[2])}).")}
    for field in ("mentioned", "cited"):
        k, n = pooled(runs, panel, snapshot, platform, field)
        out[f"{field}_rate"], out[f"{field}_low"], out[f"{field}_high"] = wilson(k, n)
    reps = defaultdict(int)
    for r in runs:
        if r["snapshot"] == snapshot and on_platform(r, platform):
            reps[(r["prompt_id"], r["platform"])] += 1
    out["min_repeats"] = min(reps.values()) if reps else 0
    return out


def verdict(low: float, high: float, drift: float | None = None) -> str:
    """Plain reading of a change interval (in share, -1..1), respecting drift in the control questions.

    A clear rise or fall only stands if it survives subtracting the controls' movement in the same direction;
    otherwise the engines moved. An interval that includes zero is 'too early to tell' when it is still wide
    enough to hide a change worth acting on, and 'no detectable change' only when it is tight around zero."""
    drift = drift or 0.0
    if low > 0 or high < 0:
        if low > 0:
            return "improved" if low - max(drift, 0.0) > 0 else "engines moved"
        return "worsened" if high - min(drift, 0.0) < 0 else "engines moved"
    if high >= MIN_ACTIONABLE or low <= -MIN_ACTIONABLE:
        return "too early to tell"
    return "no detectable change"


def drift_note(label: str, drift: float | None, raw: str) -> str:
    if label == "engines moved":
        return (f"Control questions moved too ({100 * (drift or 0):+.1f} points), so this may be the AI engines "
                f"changing rather than your work (raw reading: {raw}).")
    if label == "too early to tell":
        return "The range is too wide to rule out a change worth acting on. Add questions or repeats, or wait."
    return ""


def compare(runs, panel, base, cur, platform) -> dict | None:
    b = prompt_props(runs, panel, base, platform, False)
    c = prompt_props(runs, panel, cur, platform, False)
    shared = sorted(set(b) & set(c))
    if not shared:
        return None
    ci = boot_ci([c[p] - b[p] for p in shared], lo=-1.0, hi=1.0)
    cb = prompt_props(runs, panel, base, platform, True)
    cc = prompt_props(runs, panel, cur, platform, True)
    drift = [cc[p] - cb[p] for p in set(cb) & set(cc)]
    drift_mean = (sum(drift) / len(drift)) if drift else None
    vb, vc = snapshot_version(runs, base), snapshot_version(runs, cur)
    raw = verdict(ci[1], ci[2])
    if vb != vc:
        label, note = "not comparable", ("These rounds were counted in different ways (an older round counted every "
                                         "non-negative mention as a recommendation). Re-check the old round or start a new baseline.")
    else:
        label = verdict(ci[1], ci[2], drift_mean)
        note = drift_note(label, drift_mean, raw)
    return {"prompts": len(shared), "delta": ci[0], "low": ci[1], "high": ci[2], "verdict": label,
            "control_drift": drift_mean, "min_detectable_points": smallest_visible(ci[1], ci[2]),
            "comparable": vb == vc, "note": note}


def diff_in_diff(runs, panel, base, cur, targets: set[str], exclude=frozenset(), platform=None) -> dict | None:
    """Target prompts vs the other buying questions. `exclude` = prompts other changes targeted (left out of the
    comparison group unless that would leave fewer than MIN_PEERS)."""
    b = prompt_props(runs, panel, base, platform, False)
    c = prompt_props(runs, panel, cur, platform, False)
    both = set(b) & set(c)
    t = [c[p] - b[p] for p in sorted(both & targets)]
    pool = both - targets
    peers = pool - set(exclude)
    if len(peers) < MIN_PEERS:
        peers = pool
    o = [c[p] - b[p] for p in sorted(peers)]
    if not t or not o:
        return None
    rng, nt, no = random.Random(11), len(t), len(o)
    diffs = sorted(sum(rng.choice(t) for _ in range(nt)) / nt - sum(rng.choice(o) for _ in range(no)) / no
                   for _ in range(BOOT_N))
    low, high = diffs[int(0.025 * BOOT_N)], diffs[int(0.975 * BOOT_N) - 1]
    est = sum(t) / nt - sum(o) / no
    degenerate = low == high  # every prompt moved identically: a zero-width bootstrap interval is false precision
    if degenerate:
        reach = min(1.0, RULE_OF_THREE / (nt + no))  # three over the number of prompts compared
        low, high = max(-1.0, est - reach), min(1.0, est + reach)
    label = "supported" if low > 0 else ("worse" if high < 0 else "inconclusive")
    if nt < MIN_TARGETS:
        label = "inconclusive"  # the bootstrap over one or two prompts is not a real interval
    target_delta, other_delta = sum(t) / nt, sum(o) / no
    wide = label == "inconclusive" and nt >= MIN_TARGETS and target_delta > 0 and other_delta > DRIFT_EPS
    visible = smallest_visible(low, high)
    if nt < MIN_TARGETS:
        reading = (f"Only {nt} targeted question(s): too few to tell a real change from noise. "
                   "Target at least 3 questions per change.")
    elif label == "supported":
        reading = f"The targeted questions rose {100 * est:.1f} points more than the others."
    elif label == "worse":
        reading = f"The targeted questions fell {100 * -est:.1f} points more than the others."
    elif wide:
        reading = (f"Other prompts rose too ({100 * other_delta:+.1f} points), likely engine-wide, so the targeted "
                   "rise is not clearly your change.")
    elif visible is not None and visible > 100 * MIN_ACTIONABLE:
        reading = f"Too early to tell: this panel can only see a difference of about {visible} points."
    else:
        reading = "No clear difference between the targeted questions and the others."
    return {"targets": nt, "others": no, "others_excluded": len(pool) - len(peers), "target_delta": target_delta,
            "other_delta": other_delta, "did": est, "low": low, "high": high, "verdict": label,
            "engine_wide_likely": wide, "min_detectable_points": visible, "reading": reading}


def build_report(a) -> dict:
    panel, runs = load_panel(a.dir), read_csv(path(a.dir, "runs.csv"))
    lock = lock_info(a.dir)
    snaps = sorted({r["snapshot"] for r in runs}, key=lambda s: min(r["date"] for r in runs if r["snapshot"] == s))
    if not snaps:
        raise SystemExit("No runs yet. Ingest a baseline snapshot first.")
    base, cur = a.baseline or snaps[0], a.current or snaps[-1]
    platforms = sorted({r["platform"] for r in runs}) + [None]
    base_engines = {r["platform"] for r in runs if r["snapshot"] == base}
    cur_engines = {r["platform"] for r in runs if r["snapshot"] == cur}
    shared_engines = frozenset(base_engines & cur_engines) if base != cur and base_engines != cur_engines else None
    rep: dict = {"snapshots": snaps, "baseline": base, "current": cur, "warnings": [], "summary": {}, "change": {}}
    if lock and lock["sha256"] != panel_hash(panel):
        rep["warnings"].append("Panel differs from the frozen version: comparisons are invalid.")
    for p in platforms:
        s = snapshot_summary(runs, panel, cur, p)
        if s:
            rep["summary"][p or "all"] = s
        scope = shared_engines if p is None and shared_engines is not None else p  # none shared -> compares nothing
        if base != cur and (c := compare(runs, panel, base, cur, scope)):
            rep["change"][p or "all"] = c
    overall = rep["summary"].get("all", {})
    types = [t["type"] for t in panel.values()]
    if not any(prompt_group(t) == "discovery" for t in types):
        rep["warnings"].append("No awareness or consideration questions in the panel, so there are no buying "
                               "questions to give a Recommendation Share.")
    elif overall.get("prompts", 0) < MIN_PROMPTS:
        rep["warnings"].append(f"Fewer than {MIN_PROMPTS} buying questions (awareness and consideration): "
                               "treat results as directional.")
    if overall.get("min_repeats", 0) < MIN_REPEATS:
        rep["warnings"].append(f"Some prompt/engine pairs have fewer than {MIN_REPEATS} repeats: answers vary run to run.")
    n_controls = types.count("control")
    if n_controls == 0:
        rep["warnings"].append("No control prompts: you cannot separate real change from engine drift.")
    elif n_controls < MIN_CONTROLS:
        rep["warnings"].append(f"Only {n_controls} control prompts (at least {MIN_CONTROLS} are recommended): "
                               "the false-positive and drift checks are weak.")
    if overall and overall["recommendation_share"] == 0.0:
        rep["warnings"].append(f"Nothing was recommended in the latest round, so read this as 'below about "
                               f"{pct(overall['rs_high'])}', not exactly 0%.")
    versions = (snapshot_version(runs, base), snapshot_version(runs, cur))
    if base != cur and versions[0] != versions[1]:
        rep["warnings"].append("One of these rounds is from an older version of Citebase that counted every "
                               "non-negative mention as a recommendation and put brand-name questions in the headline. "
                               "The two rounds are not comparable: re-check the old round or start a new baseline.")
    elif versions[1] < METRIC_VERSION:
        rep["warnings"].append("This round is from an older version of Citebase that counted every non-negative "
                               "mention as a recommendation, so the share may be overstated. Compare it only with "
                               "other older rounds.")
    if base != cur and base_engines != cur_engines:
        rep["warnings"].append("The two rounds used different engines (baseline: " + ", ".join(sorted(base_engines)) +
                               "; now: " + ", ".join(sorted(cur_engines)) + "). The 'all' change uses only the "
                               "engines both rounds share.")
    if base != cur:
        rb, rc = (summary_repeats(runs, base), summary_repeats(runs, cur))
        if rb != rc:
            rep["warnings"].append(f"The rounds used different numbers of repeats (baseline {rb}, now {rc}): "
                                   "the noise level differs, so read small changes with care.")
    rep["warnings"] += panel_warnings(panel, getattr(a, "brand_info", None) or brand_from_args(a))
    rep["headline"] = overall.get("headline", "")
    visible = [c["min_detectable_points"] for c in rep["change"].values() if c.get("min_detectable_points")]
    allc = rep["change"].get("all", {}).get("min_detectable_points")
    rep["smallest_change_points"] = allc if allc else (min(visible) if visible else None)
    rep["experiments"], rep["due"] = experiment_rows(a.dir, runs, panel, base, cur, shared_engines)
    return rep


def summary_repeats(runs: list[dict], snapshot: str) -> int:
    """Fewest repeats any prompt/engine pair has in a round."""
    reps: dict[tuple[str, str], int] = defaultdict(int)
    for r in runs:
        if r["snapshot"] == snapshot:
            reps[(r["prompt_id"], r["platform"])] += 1
    return min(reps.values()) if reps else 0


def round_dates(runs: list[dict], snapshot: str) -> tuple[dt.date | None, dt.date | None]:
    days = [d for d in (parse_date(r.get("date")) for r in runs if r["snapshot"] == snapshot) if d]
    return (min(days), max(days)) if days else (None, None)


TIMING_NOTES = {
    "before_baseline": "Not scored: this change was made on or before the day the starting round was measured, so it "
                       "cannot explain a difference since then.",
    "after_current": "Not scored: this change was made after the latest round was measured. Measure again once it has "
                     "had time to work.",
    "undated": "Not scored: this change has no valid date (use YYYY-MM-DD).",
    "rounds_not_separated": "Not scored: the two rounds carry the same dates, so the change cannot be placed between "
                            "them. Give each round the date it was really measured (YYYY-MM-DD).",
}


def experiment_timing(e: dict, base_end: dt.date | None, cur_start: dt.date | None) -> str:
    """'ok' only when baseline_date < change date <= current_date (round dates are the last day of the baseline
    round and the first day of the current round, so every baseline answer came before and every current answer
    after the change)."""
    day = parse_date(e.get("date"))
    if day is None:
        return "undated"
    if base_end and cur_start and base_end >= cur_start:
        return "rounds_not_separated"  # no real dates on the rounds: say so rather than claim the change came first
    if base_end and day <= base_end:
        return "before_baseline"
    if cur_start and day > cur_start:
        return "after_current"
    return "ok"


def experiment_rows(d, runs, panel, base, cur, platform=None):
    out, due, today = [], [], dt.date.today().isoformat()
    exps = read_csv(path(d, "experiments.csv"))
    base_end, cur_start = round_dates(runs, base)[1], round_dates(runs, cur)[0]
    cur_end = round_dates(runs, cur)[1]
    comparable = snapshot_version(runs, base) == snapshot_version(runs, cur)
    targets = {e["exp_id"]: set(filter(None, e["target_prompt_ids"].split(","))) for e in exps}
    timing = {e["exp_id"]: experiment_timing(e, base_end, cur_start) for e in exps}
    in_window = [e["exp_id"] for e in exps if timing[e["exp_id"]] == "ok" and e["status"] != "abandoned"]
    for e in exps:
        eid = e["exp_id"]
        remeasured = bool(cur_end) and e["recheck_after"] <= cur_end.isoformat()  # a round already came after it
        if e["status"] == "shipped" and e["recheck_after"] <= today and not remeasured:
            due.append(f"{eid} ({e['mechanism']}): {e['action']}")
        others = [x for x in in_window if x != eid]
        mine = targets[eid]
        confounded_with = [x for x in others if mine & targets[x]] if timing[eid] == "ok" else []
        res, note = None, TIMING_NOTES.get(timing[eid], "")
        if base != cur and timing[eid] == "ok":
            if comparable:
                skip = set().union(*(targets[x] for x in others)) if others else set()
                res = diff_in_diff(runs, panel, base, cur, mine, skip, platform)
            else:
                note = "Not scored: the two rounds were counted in different ways."
        out.append({"exp_id": eid, "mechanism": e["mechanism"], "action": e["action"], "status": e["status"],
                    "result": res, "timing": timing[eid], "note": note, "confounded": bool(confounded_with),
                    "confounded_with": confounded_with})
    return out, due


def pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def render(rep: dict) -> str:
    lines = [f"# Citation report: {rep['current']}" + (f" vs {rep['baseline']}" if rep["baseline"] != rep["current"] else "")]
    if rep.get("headline"):
        lines += ["", f"**{rep['headline']}**"]
        rs = rep["summary"]["all"]
        if rs.get("reputation_prompts"):
            lines += [f"Reputation check (questions that already name the brand): {pct(rs['reputation_share'])}."]
    lines += [""] + [f"WARNING: {w}" for w in rep["warnings"]]
    lines += ["", "| Engine | Prompts | Recommendation Share (95% CI) | Mentioned | Cited | Control false-positive | Brand-name questions |",
              "|---|---|---|---|---|---|---|"]
    for name, s in rep["summary"].items():
        lines.append(f"| {name} | {s['prompts']} | {pct(s['recommendation_share'])} ({pct(s['rs_low'])} to {pct(s['rs_high'])})"
                     f" | {pct(s['mentioned_rate'])} | {pct(s['cited_rate'])} | {pct(s['control_false_positive'])}"
                     f" | {pct(s['reputation_share'])} |")
    if rep["change"]:
        lines += ["", f"## Change since {rep['baseline']} (paired by prompt)", "", "| Engine | Prompts | Delta RS (95% CI) | Verdict | Control drift |", "|---|---|---|---|---|"]
        for name, c in rep["change"].items():
            lines.append(f"| {name} | {c['prompts']} | {100 * c['delta']:+.1f} pts ({100 * c['low']:+.1f} to {100 * c['high']:+.1f})"
                         f" | {c['verdict']} | {pct(c['control_drift'])} |")
        notes = sorted({c["note"] for c in rep["change"].values() if c.get("note")})
        lines += [""] + [f"- {n}" for n in notes]
        if rep.get("smallest_change_points"):
            lines += ["", f"Smallest change this panel can reliably see: about {rep['smallest_change_points']} points."]
    if rep["experiments"]:
        lines += ["", "## Experiments (target vs other prompts)"]
        for e in rep["experiments"]:
            r = e["result"]
            tail = (f"target {100 * r['target_delta']:+.1f} pts, others {100 * r['other_delta']:+.1f} pts, "
                    f"difference {100 * r['did']:+.1f} ({100 * r['low']:+.1f} to {100 * r['high']:+.1f}) -> {r['verdict']}. {r['reading']}"
                    if r else (e["note"] or "not enough data yet"))
            note = (f" [confounded: shares questions with {', '.join(e['confounded_with'])}]"
                    if e["confounded"] and r else "")
            lines.append(f"- {e['exp_id']} {e['mechanism']}: {e['action']}: {tail}{note}")
    if rep["due"]:
        lines += ["", "## Re-measure now"] + [f"- {x}" for x in rep["due"]]
    lines += ["", "Correlation, not proof: engines drift and changes overlap. Treat 'supported' as a lead to repeat."]
    return "\n".join(lines)


def cmd_report(a) -> int:
    rep = build_report(a)
    print(json.dumps(rep, indent=1) if a.json else render(rep))
    return 0


def add_brand_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--brand", default="", help="brand name: warns when a non-brand question contains it")
    parser.add_argument("--domain", default="", help="brand domain, same purpose")
    parser.add_argument("--alias", default="", help="other names for the brand, comma separated")


def build() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").add_argument("dir")
    sub.choices["init"].set_defaults(fn=cmd_init)
    p = sub.add_parser("panel")
    p.add_argument("action", choices=["add", "list", "freeze"])
    p.add_argument("dir")
    p.add_argument("--prompt")
    p.add_argument("--type", default="consideration")
    p.add_argument("--topic", default="")
    add_brand_args(p)
    p.set_defaults(fn=cmd_panel)
    i = sub.add_parser("ingest")
    i.add_argument("dir")
    i.add_argument("--snapshot", required=True)
    i.add_argument("--file", required=True)
    i.set_defaults(fn=cmd_ingest)
    e = sub.add_parser("experiment")
    e.add_argument("action", choices=["add", "list", "close"])
    e.add_argument("dir")
    e.add_argument("--action-text", dest="action_text", default="")
    e.add_argument("--mechanism", default="other")
    e.add_argument("--targets", default="")
    e.add_argument("--url", default="")
    e.add_argument("--date", default="")
    e.add_argument("--recheck-after", dest="recheck_after", default="")
    e.add_argument("--notes", default="")
    e.add_argument("--exp-id", dest="exp_id", default="")
    e.add_argument("--status", default="done", choices=["shipped", "done", "failed", "abandoned"])
    e.set_defaults(fn=cmd_experiment)
    r = sub.add_parser("report")
    r.add_argument("dir")
    r.add_argument("--baseline", default="")
    r.add_argument("--current", default="")
    r.add_argument("--json", action="store_true")
    add_brand_args(r)
    r.set_defaults(fn=cmd_report)
    return ap


def main() -> int:
    a = build().parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
