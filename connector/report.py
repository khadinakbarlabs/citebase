"""Shareable one-page report built from a saved project.

Self-contained HTML (no scripts, no external files). Every value from the project is HTML-escaped. The page is saved
in the user's own store; the link is whatever that store can give (a link that only people holding it can open).
"""
from __future__ import annotations

import asyncio
import html
from typing import Any

import history as hist
import storage as stg

REPORT_KEY_SUFFIX = "report.html"
W, H, PAD = 560, 140, 28

CSS = """
:root{--bg:#fbfaf7;--ink:#1b1b18;--mute:#6b6a63;--line:#e4e1d8;--acc:#1f6f5c;--bad:#b3402a;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--ink:#f1efe8;--mute:#a09e94;--line:#2c2b27;--acc:#58c2a6;--bad:#ef8a73;--card:#1e1e1b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,sans-serif}
main{max-width:720px;margin:0 auto;padding:32px 16px 64px}h1{font-size:1.7rem;margin:0 0 4px}h2{font-size:1.1rem;margin:32px 0 8px}
.sub{color:var(--mute);margin:0 0 24px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.big{font-size:2.4rem;font-weight:700;color:var(--acc);line-height:1}table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:600;font-size:.85rem}
.up{color:var(--acc)}.down{color:var(--bad)}svg{width:100%;height:auto}small{color:var(--mute)}
"""


def pct(x: Any) -> str:
    return "n/a" if x is None else f"{100 * float(x):.1f}%"


def esc(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def spark(points: list[tuple[str, float, float, float]], unit_pct: bool) -> str:
    """Inline SVG line: points are (label, value, low, high). The range is drawn as a soft band."""
    if len(points) < 2:
        return ""
    hi = max(max(p[3] for p in points), 1e-9)
    xs = [PAD + i * (W - 2 * PAD) / (len(points) - 1) for i in range(len(points))]

    def y(v: float) -> float:
        return H - PAD - (v / hi) * (H - 2 * PAD)

    band = " ".join(f"{x:.1f},{y(p[3]):.1f}" for x, p in zip(xs, points)) + " " + \
        " ".join(f"{x:.1f},{y(p[2]):.1f}" for x, p in reversed(list(zip(xs, points))))
    line = " ".join(f"{x:.1f},{y(p[1]):.1f}" for x, p in zip(xs, points))
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y(p[1]):.1f}" r="3.5" fill="var(--acc)"/>' for x, p in zip(xs, points))
    labels = "".join(f'<text x="{x:.1f}" y="{H - 6}" font-size="10" fill="var(--mute)" text-anchor="middle">{esc(str(p[0])[:10])}</text>'
                     for x, p in zip(xs, points))
    top = f"{100 * hi:.0f}%" if unit_pct else f"{hi:.0f}"
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Trend chart"><polygon points="{band}" fill="var(--acc)" opacity=".15"/>'
            f'<polyline points="{line}" fill="none" stroke="var(--acc)" stroke-width="2.5"/>{dots}{labels}'
            f'<text x="4" y="14" font-size="10" fill="var(--mute)">{top}</text></svg>')


def verdict_cell(verdict: str) -> str:
    cls = "up" if verdict == "improved" else ("down" if verdict == "worsened" else "")
    return f'<span class="{cls}">{esc(verdict)}</span>'


def render_html(project: str, data: dict, snaps: list[dict], measure: dict | None, steps: list[dict] | None) -> str:
    brand = data["meta"].get("brand", {})
    name = brand.get("name") or project
    parts = [f"<main><h1>{esc(name)}: AI visibility report</h1>",
             f'<p class="sub">Project {esc(project)}. Updated {esc(data["meta"].get("updated", ""))}. '
             f'{len(data["panel"])} test questions. Made with Citebase.</p>']
    if snaps:
        last = snaps[-1]
        parts.append(f'<div class="card"><div class="big">{pct(last["recommendation_share"])}</div>'
                     f'<p>of the time, AI assistants recommended {esc(name)} in the latest round '
                     f'({esc(last["snapshot"])}). Likely range {pct(last["rs_low"])} to {pct(last["rs_high"])}.</p>'
                     f'{spark([(s["snapshot"], s["recommendation_share"], s["rs_low"], s["rs_high"]) for s in snaps], True)}</div>')
        parts.append("<h2>Every round</h2><table><tr><th>Round</th><th>Saved</th><th>Recommended</th><th>Named</th><th>Linked</th></tr>" +
                     "".join(f'<tr><td>{esc(s["snapshot"])}</td><td>{esc(s["saved_on"])}</td><td>{pct(s["recommendation_share"])}</td>'
                             f'<td>{pct(s["mentioned_rate"])}</td><td>{pct(s["cited_rate"])}</td></tr>' for s in snaps) + "</table>")
    if measure:
        rows = [(k, v) for k, v in measure.get("change", {}).items() if v]
        if rows:
            parts.append("<h2>Change since the start</h2><table><tr><th>Engine</th><th>Change</th><th>Verdict</th></tr>" +
                         "".join(f'<tr><td>{esc(k)}</td><td>{pct(v.get("delta"))}</td><td>{verdict_cell(v.get("verdict", ""))}</td></tr>'
                                 for k, v in rows) + "</table>")
        exps = measure.get("experiments") or []
        if exps:
            parts.append("<h2>What you changed, and did it work?</h2><table><tr><th>Change</th><th>Verdict</th></tr>" +
                         "".join(f'<tr><td>{esc(e.get("action"))}</td><td>{esc((e.get("result") or {}).get("verdict", "too early"))}</td></tr>'
                                 for e in exps) + "</table>")
        if measure.get("warnings"):
            parts.append("<h2>Be careful with</h2><ul>" + "".join(f"<li>{esc(w)}</li>" for w in measure["warnings"]) + "</ul>")
    audits = data["audits"]
    if audits:
        pts = [(a["date"], float(a.get("health_score") or 0), float(a.get("health_score") or 0), float(a.get("health_score") or 0))
               for a in audits]
        parts.append(f'<h2>Website health</h2><div class="card"><div class="big">{esc(audits[-1].get("health_score"))}/100</div>'
                     f'<p>Latest check on {esc(audits[-1]["date"])}.</p>{spark(pts, False)}</div>')
        probs = audits[-1].get("problems") or []
        if probs:
            parts.append("<h2>Top problems to fix</h2><table><tr><th>Problem</th><th>Detail</th></tr>" +
                         "".join(f'<tr><td>{esc(p.get("check"))}</td><td>{esc(p.get("detail"))}</td></tr>' for p in probs[:8]) + "</table>")
    if steps:
        parts.append("<h2>What to do next</h2><table><tr><th>Step</th><th>Who</th><th>Time</th></tr>" +
                     "".join(f'<tr><td><b>{esc(s["step"])}</b><br><small>{esc(s["why"])}</small></td><td>{esc(s["who"])}</td>'
                             f'<td>{esc(s["effort"])}</td></tr>' for s in steps) + "</table>")
    if not snaps and not audits:
        parts.append("<p>Nothing saved yet.</p>")
    parts.append("</main>")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>{esc(name)}: AI visibility report</title><style>{CSS}</style></head><body>' +
            "".join(parts) + "</body></html>")


async def make_report(project: str) -> dict:
    import tools  # local import keeps module load order simple

    data = await hist.load_project(project)
    snaps = await asyncio.to_thread(hist.snapshot_trend, data)
    measure, skipped = None, None
    if snaps and data["runs"]:
        try:
            measure = await asyncio.to_thread(hist.measure_loaded, data)
        except ValueError as err:
            skipped = str(err)  # still make the report, and tell the user why a section is missing
    audit = data["audits"][-1] if data["audits"] else None
    steps = tools.next_steps(audit, measure, 5)["steps"] if (audit or measure) else None
    page = render_html(data["slug"], data, snaps, measure, steps)
    be = await stg.get_backend()
    key = stg.key(data["slug"], REPORT_KEY_SUFFIX)
    await be.set(key, page, content_type="text/html; charset=utf-8")
    url = await be.public_url(key)
    how_to_stop = f"To stop sharing, delete the '{key}' record in your Apify key-value store 'citebase-projects'."
    note = ("The link works for anyone who has it (it is not listed anywhere). " if url else
            "No share link could be made, but the report is saved in your Apify key-value store 'citebase-projects' "
            "and you can open it there. ") + how_to_stop
    if skipped:
        note += f" The measuring section was left out: {skipped}"
    return {"project": data["slug"], "share_url": url, "stored_key": key, "bytes": len(page),
            "snapshots": len(snaps), "site_checks": len(data["audits"]), "note": note}
