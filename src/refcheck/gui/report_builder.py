"""Builds the templated HTML report — Jinja2 + embedded matplotlib images, no live
preview in the app, per the reconciled spec.

Chart aggregation logic is shared with the Summary screen via report_data.py so the
report can never show numbers that disagree with what the app displayed live.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Sequence
from dataclasses import dataclass

import jinja2
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from refcheck.extraction.citation_matching import CitationMatch
from refcheck.extraction.document_artifact import DocumentArtifact
from refcheck.extraction.reference_list_audit import NOT_AUDITED, ReferenceListAudit
from refcheck.gui import citation_display
from refcheck.gui.reference_list_display import reference_list_note
from refcheck.gui.models import STATUS_LABELS, ReferenceResult
from refcheck.gui.real_pipeline import CITATIONS_NOT_RUN
from refcheck.gui.report_data import (
    age_bin_counts,
    citation_bin_counts,
    citation_rows,
    outlet_breakdown,
    topic_breakdown,
)

# autoescape=True matters here: raw citation text comes from a parsed manuscript, which
# is untrusted input — without escaping, a crafted reference string could inject HTML/JS
# into the report a reviewer later opens in a browser.
_ENV = jinja2.Environment(autoescape=True)
_TEMPLATE = _ENV.from_string(
    """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Reference check report — {{ meta.document }}</title>
<style>
body { font-family: 'Segoe UI', system-ui, sans-serif; background:#dcdad5; margin:0; padding:36px; color:#26241f; }
.card { max-width:980px; margin:0 auto; background:#f3f2ef; border:1px solid #c6c3bc; border-radius:7px; padding:28px 32px; }
h1 { font-size:20px; margin:0 0 4px; }
.meta { color:#8a877f; font-family:monospace; font-size:11.5px; margin-bottom:18px; }
.watermark { border:1px dashed #b9976a; background:#fbf4e6; color:#7a5a12; border-radius:4px; padding:10px 13px; margin-bottom:18px; font-size:12.5px; }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:.05em; color:#5c594f; border-bottom:1px solid #dedbd4; padding-bottom:6px; margin-top:28px; }
table { width:100%; border-collapse:collapse; font-size:12.5px; margin-top:8px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid #e4e1db; vertical-align:top; }
th { color:#6b6860; font-weight:600; font-size:11px; }
.badge { display:inline-block; padding:2px 6px; border-radius:3px; font-size:10.5px; font-weight:500; }
.scorecards { display:flex; gap:10px; flex-wrap:wrap; }
.scorecard { border:1px solid #cdcac3; border-radius:4px; background:#fff; padding:8px 11px; min-width:120px; }
.scorecard .value { font-size:16px; font-weight:600; }
.scorecard .label { font-size:10.5px; color:#6b6860; }
img.chart { max-width:100%; border:1px solid #cdcac3; border-radius:5px; margin-top:8px; background:#fff; }
</style></head>
<body><div class="card">
<h1>Reference check report</h1>
<div class="meta">{{ meta.document }} · {{ meta.check_date }} · {{ meta.api_version }} · {{ meta.format }}</div>

{% if meta.watermark %}
<div class="watermark"><strong>SYNTHETIC EXAMPLE</strong> — generated from the bundled synthetic manuscript.</div>
{% endif %}

{% if include.scores %}
<h2>Category scores</h2>
<div class="scorecards">
  {% for label, value in scores %}
  <div class="scorecard"><div class="value">{{ value }}</div><div class="label">{{ label }}</div></div>
  {% endfor %}
</div>
{% endif %}

{% if include.charts %}
<h2>Charts</h2>
<img class="chart" src="data:image/png;base64,{{ charts.outlets }}" alt="Articles cited per journal or outlet">
<img class="chart" src="data:image/png;base64,{{ charts.age }}" alt="Publication age histogram">
<img class="chart" src="data:image/png;base64,{{ charts.topic }}" alt="Topic breadth">
<img class="chart" src="data:image/png;base64,{{ charts.citations }}" alt="How often the cited sources are themselves cited">
{% endif %}

{% if include.confidence %}
<h2>References</h2>
{% if reference_list.headline %}
<p style="{{ 'color:#5c594f;' if reference_list.complete else 'border:1px solid #d8a83c;background:#fdf4e2;color:#4a4843;border-radius:5px;padding:8px 12px;' }} font-size:12.5px;">
  <strong>{{ reference_list.headline }}</strong>{% if reference_list.detail %} {{ reference_list.detail }}{% endif %}
</p>
{% endif %}
<table>
<tr><th>#</th><th>Raw citation</th><th>Status</th><th>Confidence</th><th>DOI</th></tr>
{% for r in references %}
<tr>
  <td>{{ "%02d"|format(r.n) }}</td>
  <td>{{ r.raw }}</td>
  <td><span class="badge" style="background:{{ r.badge_bg }};border:1px solid {{ r.badge_border }};color:{{ r.badge_fg }};">{{ r.status_label }}</span></td>
  <td>{{ "%.2f"|format(r.confidence) if r.confidence else "—" }}</td>
  <td>{{ r.doi }}</td>
</tr>
{% endfor %}
</table>
{% endif %}

{% if include.citations %}
<h2>In-text citations</h2>
<p style="color:#5c594f; font-size:12.5px;">{{ citations.headline }}</p>
{% if citations.rows %}
<table>
<tr><th>#</th><th>Raw citation</th><th>In text</th></tr>
{% for c in citations.rows %}
<tr>
  <td>{{ "%02d"|format(c.n) }}</td>
  <td>{{ c.raw }}</td>
  <td{% if c.uncited %} style="color:#8c2f10;"{% endif %}>{{ c.label }}</td>
</tr>
{% if c.passages %}
<tr><td></td><td colspan="2">
  {% for passage in c.passages %}
  <div style="color:#5c594f; font-size:11.5px; border-left:2px solid #c6c3bc; padding-left:8px; margin-bottom:4px;">{{ passage }}</div>
  {% endfor %}
</td></tr>
{% endif %}
{% endfor %}
</table>
{% endif %}
{% endif %}

{% if include.audit_trail %}
<h2>Manual review audit trail</h2>
{% if decisions %}
<table>
<tr><th>#</th><th>Decision</th><th>Timestamp</th></tr>
{% for d in decisions %}
<tr><td>{{ "%02d"|format(d.n) }}</td><td>{{ d.label }}</td><td>{{ d.stamp }}</td></tr>
{% endfor %}
</table>
{% else %}
<p style="color:#8a877f; font-size:12.5px;">No manual decisions recorded for this check.</p>
{% endif %}
{% endif %}

{% if include.metadata %}
<h2>API and check metadata</h2>
<table>
<tr><th>Document</th><td>{{ meta.document }}</td></tr>
<tr><th>Check date</th><td>{{ meta.check_date }}</td></tr>
<tr><th>API version</th><td>{{ meta.api_version }}</td></tr>
</table>
{% endif %}

</div></body></html>
"""
)


# What a report contains unless the reviewer says otherwise. Lives here rather than in
# AppState or the export screen because those two would otherwise each hold their own
# copy, and the copy that matters is whichever one `citation_passages` is False in.
#
# Everything structured is on. `citation_passages` is the exception and the only one: it
# writes the manuscript's own sentences into a file that leaves the session, which is a
# different act from displaying them, and the plan keeps the two decisions apart.
DEFAULT_EXPORT_INCLUDED = {
    "scores": True,
    "confidence": True,
    "audit_trail": True,
    "charts": True,
    "metadata": True,
    "citations": True,
    "citation_passages": False,
}


@dataclass(frozen=True)
class ReportMeta:
    document: str
    check_date: str
    api_version: str = "OpenAlex v1 · Crossref v1"
    format: str = "HTML (Jinja2 + matplotlib)"
    watermark: bool = False


_STATUS_PALETTE = {
    "verified": ("#e8f0e6", "#a8c39c", "#3c5c33"),
    "review": ("#fbf1dd", "#dcbb78", "#7a5a12"),
    "halluc": ("#fbeae5", "#d6a294", "#8c2f1c"),
    "dup": ("#eeece7", "#c6c3bc", "#5c594f"),
    "unchecked": ("#eceff3", "#b6bfcb", "#3f5570"),
}


def _chart_png_base64(draw) -> str:
    figure = Figure(figsize=(6, 2.6), dpi=110)
    figure.patch.set_facecolor("#ffffff")
    FigureCanvasAgg(figure)
    ax = figure.add_subplot(111)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    draw(ax)
    figure.tight_layout()
    buf = io.BytesIO()
    figure.savefig(buf, format="png")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build_html_report(
    results: list[ReferenceResult],
    decisions: dict[int, dict[str, str]],
    meta: ReportMeta,
    included: dict[str, bool],
    *,
    citation_matches: Sequence[CitationMatch] = (),
    citation_run_status: str = CITATIONS_NOT_RUN,
    artifact: DocumentArtifact | None = None,
    audit: ReferenceListAudit = NOT_AUDITED,
) -> str:
    """Render the report. The citation arguments are keyword-only and default to "the
    search did not run", so a caller that knows nothing about citations produces a report
    that says nothing about them rather than one that quietly claims a clean manuscript.

    Passages are included only when `included["citation_passages"]` is set, which is a
    different key from the on-screen toggle and defaults off: the report is a file that
    outlives the session, and consent to read a passage on screen is not consent to write
    it to disk.
    """
    n_total = len(results)
    n_verified = sum(1 for r in results if r.status == "verified")
    n_halluc = sum(1 for r in results if r.status == "halluc")
    n_dup = sum(1 for r in results if r.status == "dup")
    n_review = sum(1 for r in results if r.status in ("review", "unchecked"))

    scores = [
        (f"Verified ({round(n_verified / n_total * 100) if n_total else 0}%)", f"{n_verified} / {n_total}"),
        ("No match found", str(n_halluc)),
        ("Duplicates", str(n_dup)),
        ("Needs manual review", str(n_review)),
    ]

    def _draw_age(ax) -> None:
        ax.bar(*age_bin_counts(results), color="#7b93b8", edgecolor="#5c78a1")

    def _draw_topic(ax) -> None:
        ax.barh(*topic_breakdown(results), color="#8a9c7d", edgecolor="#6f8060")

    def _draw_citations(ax) -> None:
        # Same histogram as the Summary screen, so the report cannot show a differently
        # shaped chart than the application it was generated from.
        ax.bar(*citation_bin_counts(results), color="#7b93b8", edgecolor="#5c78a1")
        ax.set_xlabel("times cited by the wider literature", fontsize=9)
        ax.set_ylabel("references", fontsize=9)
        ax.yaxis.get_major_locator().set_params(integer=True)

    def _draw_outlets(ax) -> None:
        labels, values = outlet_breakdown(results)
        ax.barh(labels, values, color="#8a9c7d", edgecolor="#6f8060")
        ax.tick_params(axis="both", labelsize=10.5, colors="#000000")
        ax.spines["bottom"].set_color("#000000")
        ax.spines["left"].set_color("#000000")
        ax.set_xlabel("articles", fontsize=10.5, color="#000000")
        ax.xaxis.get_major_locator().set_params(integer=True)

    charts = {
        "age": _chart_png_base64(_draw_age),
        "topic": _chart_png_base64(_draw_topic),
        "outlets": _chart_png_base64(_draw_outlets),
        "citations": _chart_png_base64(_draw_citations),
    }

    ref_rows = []
    for r in results:
        bg, border, fg = _STATUS_PALETTE[r.status]
        ref_rows.append(
            {
                "n": r.n, "raw": r.raw, "doi": r.doi, "confidence": r.confidence,
                "status_label": STATUS_LABELS[r.status],
                "badge_bg": bg, "badge_border": border, "badge_fg": fg,
            }
        )

    decision_rows = [{"n": n, **d} for n, d in sorted(decisions.items())]

    citations = {
        "headline": citation_display.document_summary(
            [r.n for r in results], citation_matches, citation_run_status
        ).headline,
        "rows": citation_rows(
            results,
            citation_matches,
            citation_run_status,
            artifact=artifact,
            include_passages=bool(included.get("citation_passages")),
        ),
    }

    return _TEMPLATE.render(
        meta=meta,
        include=included,
        reference_list=reference_list_note(audit, len(results)),
        scores=scores,
        charts=charts,
        references=ref_rows,
        decisions=decision_rows,
        citations=citations,
    )
