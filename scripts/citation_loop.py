#!/usr/bin/env python3
"""AI-citation measurement loop: frozen prompt panel -> repeat runs -> Recommendation Share -> experiments.

  init DIR                                  create panel.csv, runs.csv, experiments.csv
  panel add DIR --prompt TEXT --type T      T = awareness | consideration | brand | control
  panel list DIR | panel freeze DIR         freeze locks the panel (edits afterwards are refused)
  ingest DIR --snapshot NAME --file F       append run results (JSON list or CSV) to runs.csv
  experiment add|list|close DIR ...         log what you changed and when to re-measure
  report DIR [--baseline S] [--current S] [--json]

Recommendation Share (RS) = share of (prompt x engine x repeat) answers in which the brand is
actively recommended, averaged per prompt over the non-control panel. Repeats of one prompt are
correlated, so confidence intervals resample PROMPTS (bootstrap), not individual runs.
Control prompts (where the brand should not be recommended) estimate noise and false positives.
Experiment verdicts compare target prompts with the other prompts (difference-in-differences).
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
import sys
from collections import defaultdict

PANEL_COLS = ["prompt_id", "prompt", "type", "topic"]
RUN_COLS = ["run_id", "snapshot", "date", "prompt_id", "platform", "repeat", "mentioned", "cited",
            "recommended", "position", "competitors", "cited_domains"]
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


def boot_ci(values: list[float], seed: int = 7) -> tuple[float, float, float] | None:
    """Mean and 95% percentile-bootstrap interval over the given units (prompts)."""
    if not values:
        return None
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, mean, mean
    rng, n = random.Random(seed), len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(BOOT_N))
    return mean, means[int(0.025 * BOOT_N)], means[int(0.975 * BOOT_N) - 1]


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
    return {"run_id": f"r{n:05d}", "snapshot": snapshot, "date": row.get("date") or dt.date.today().isoformat(),
            "prompt_id": pid, "platform": platform, "repeat": int(row.get("repeat") or 1),
            "mentioned": max(to_bool(row.get("mentioned", 0)), rec), "cited": to_bool(row.get("cited", 0)),
            "recommended": rec, "position": row.get("position", ""),
            "competitors": row.get("competitors", ""), "cited_domains": row.get("cited_domains", "")}


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


def prompt_props(runs: list[dict], panel: dict, snapshot: str, platform: str | None, controls: bool) -> dict[str, float]:
    """Per-prompt recommendation rate (mean over engines x repeats) for one snapshot."""
    acc: dict[str, list[int]] = defaultdict(list)
    for r in runs:
        if r["snapshot"] != snapshot or (platform and r["platform"] != platform):
            continue
        if (panel[r["prompt_id"]]["type"] == "control") == controls:
            acc[r["prompt_id"]].append(int(r["recommended"]))
    return {pid: sum(v) / len(v) for pid, v in acc.items()}


def pooled(runs: list[dict], panel: dict, snapshot: str, platform: str | None, field: str) -> tuple[int, int]:
    rows = [r for r in runs if r["snapshot"] == snapshot and (not platform or r["platform"] == platform)
            and panel[r["prompt_id"]]["type"] != "control"]
    return sum(int(r[field]) for r in rows), len(rows)


def snapshot_summary(runs, panel, snapshot, platform) -> dict | None:
    props = prompt_props(runs, panel, snapshot, platform, controls=False)
    if not props:
        return None
    ci = boot_ci(list(props.values()))
    ctrl = list(prompt_props(runs, panel, snapshot, platform, controls=True).values())
    out = {"prompts": len(props), "recommendation_share": ci[0], "rs_low": ci[1], "rs_high": ci[2],
           "control_false_positive": (sum(ctrl) / len(ctrl)) if ctrl else None}
    for field in ("mentioned", "cited"):
        k, n = pooled(runs, panel, snapshot, platform, field)
        out[f"{field}_rate"], out[f"{field}_low"], out[f"{field}_high"] = wilson(k, n)
    reps = defaultdict(int)
    for r in runs:
        if r["snapshot"] == snapshot and (not platform or r["platform"] == platform):
            reps[(r["prompt_id"], r["platform"])] += 1
    out["min_repeats"] = min(reps.values()) if reps else 0
    return out


def verdict(low: float, high: float) -> str:
    return "improved" if low > 0 else ("worsened" if high < 0 else "no detectable change")


def compare(runs, panel, base, cur, platform) -> dict | None:
    b = prompt_props(runs, panel, base, platform, False)
    c = prompt_props(runs, panel, cur, platform, False)
    shared = sorted(set(b) & set(c))
    if not shared:
        return None
    ci = boot_ci([c[p] - b[p] for p in shared])
    cb = prompt_props(runs, panel, base, platform, True)
    cc = prompt_props(runs, panel, cur, platform, True)
    drift = [cc[p] - cb[p] for p in set(cb) & set(cc)]
    return {"prompts": len(shared), "delta": ci[0], "low": ci[1], "high": ci[2], "verdict": verdict(ci[1], ci[2]),
            "control_drift": (sum(drift) / len(drift)) if drift else None}


def diff_in_diff(runs, panel, base, cur, targets: set[str]) -> dict | None:
    b = prompt_props(runs, panel, base, None, False)
    c = prompt_props(runs, panel, cur, None, False)
    t = [c[p] - b[p] for p in sorted(set(b) & set(c) & targets)]
    o = [c[p] - b[p] for p in sorted((set(b) & set(c)) - targets)]
    if not t or not o:
        return None
    rng, nt, no = random.Random(11), len(t), len(o)
    diffs = sorted(sum(rng.choice(t) for _ in range(nt)) / nt - sum(rng.choice(o) for _ in range(no)) / no
                   for _ in range(BOOT_N))
    low, high = diffs[int(0.025 * BOOT_N)], diffs[int(0.975 * BOOT_N) - 1]
    est = sum(t) / nt - sum(o) / no
    label = "supported" if low > 0 else ("worse" if high < 0 else "inconclusive")
    return {"targets": nt, "others": no, "target_delta": sum(t) / nt, "other_delta": sum(o) / no,
            "did": est, "low": low, "high": high, "verdict": label}


def build_report(a) -> dict:
    panel, runs = load_panel(a.dir), read_csv(path(a.dir, "runs.csv"))
    lock = lock_info(a.dir)
    snaps = sorted({r["snapshot"] for r in runs}, key=lambda s: min(r["date"] for r in runs if r["snapshot"] == s))
    if not snaps:
        raise SystemExit("No runs yet. Ingest a baseline snapshot first.")
    base, cur = a.baseline or snaps[0], a.current or snaps[-1]
    platforms = sorted({r["platform"] for r in runs}) + [None]
    rep: dict = {"snapshots": snaps, "baseline": base, "current": cur, "warnings": [], "summary": {}, "change": {}}
    if lock and lock["sha256"] != panel_hash(panel):
        rep["warnings"].append("Panel differs from the frozen version: comparisons are invalid.")
    for p in platforms:
        s = snapshot_summary(runs, panel, cur, p)
        if s:
            rep["summary"][p or "all"] = s
        if base != cur and (c := compare(runs, panel, base, cur, p)):
            rep["change"][p or "all"] = c
    overall = rep["summary"].get("all", {})
    if overall.get("prompts", 0) < MIN_PROMPTS:
        rep["warnings"].append(f"Fewer than {MIN_PROMPTS} non-control prompts: treat results as directional.")
    if overall.get("min_repeats", 0) < MIN_REPEATS:
        rep["warnings"].append(f"Some prompt/engine pairs have fewer than {MIN_REPEATS} repeats: answers vary run to run.")
    if not any(t["type"] == "control" for t in panel.values()):
        rep["warnings"].append("No control prompts: you cannot separate real change from engine drift.")
    rep["experiments"], rep["due"] = experiment_rows(a.dir, runs, panel, base, cur)
    return rep


def experiment_rows(d, runs, panel, base, cur):
    out, due, today = [], [], dt.date.today().isoformat()
    exps = read_csv(path(d, "experiments.csv"))
    for e in exps:
        if e["status"] == "shipped" and e["recheck_after"] <= today:
            due.append(f"{e['exp_id']} ({e['mechanism']}): {e['action']}")
        res = diff_in_diff(runs, panel, base, cur, set(filter(None, e["target_prompt_ids"].split(",")))) if base != cur else None
        out.append({"exp_id": e["exp_id"], "mechanism": e["mechanism"], "action": e["action"], "status": e["status"],
                    "result": res, "confounded": sum(1 for x in exps if x["status"] == "shipped") > 1})
    return out, due


def pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def render(rep: dict) -> str:
    lines = [f"# Citation report: {rep['current']}" + (f" vs {rep['baseline']}" if rep["baseline"] != rep["current"] else "")]
    lines += [f"WARNING: {w}" for w in rep["warnings"]]
    lines += ["", "| Engine | Prompts | Recommendation Share (95% CI) | Mentioned | Cited | Control false-positive |",
              "|---|---|---|---|---|---|"]
    for name, s in rep["summary"].items():
        lines.append(f"| {name} | {s['prompts']} | {pct(s['recommendation_share'])} ({pct(s['rs_low'])} to {pct(s['rs_high'])})"
                     f" | {pct(s['mentioned_rate'])} | {pct(s['cited_rate'])} | {pct(s['control_false_positive'])} |")
    if rep["change"]:
        lines += ["", f"## Change since {rep['baseline']} (paired by prompt)", "", "| Engine | Prompts | Delta RS (95% CI) | Verdict | Control drift |", "|---|---|---|---|---|"]
        for name, c in rep["change"].items():
            lines.append(f"| {name} | {c['prompts']} | {100 * c['delta']:+.1f} pts ({100 * c['low']:+.1f} to {100 * c['high']:+.1f})"
                         f" | {c['verdict']} | {pct(c['control_drift'])} |")
    if rep["experiments"]:
        lines += ["", "## Experiments (target vs other prompts)"]
        for e in rep["experiments"]:
            r = e["result"]
            tail = (f"target {100 * r['target_delta']:+.1f} pts, others {100 * r['other_delta']:+.1f} pts, "
                    f"difference {100 * r['did']:+.1f} ({100 * r['low']:+.1f} to {100 * r['high']:+.1f}) -> {r['verdict']}"
                    if r else "not enough data yet")
            note = " [confounded: several changes shipped together]" if e["confounded"] and r else ""
            lines.append(f"- {e['exp_id']} {e['mechanism']}: {e['action']}: {tail}{note}")
    if rep["due"]:
        lines += ["", "## Re-measure now"] + [f"- {x}" for x in rep["due"]]
    lines += ["", "Correlation, not proof: engines drift and changes overlap. Treat 'supported' as a lead to repeat."]
    return "\n".join(lines)


def cmd_report(a) -> int:
    rep = build_report(a)
    print(json.dumps(rep, indent=1) if a.json else render(rep))
    return 0


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
    r.set_defaults(fn=cmd_report)
    return ap


def main() -> int:
    a = build().parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
