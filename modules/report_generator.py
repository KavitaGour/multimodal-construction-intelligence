"""Consolidated project report (JSON + Markdown)."""
from __future__ import annotations

from typing import Any, Dict, List

from config import (AI_DISCLAIMER, APP_NAME, DEMO_NOTICE, ESTIMATE_DISCLAIMER,
                    STRUCTURAL_DISCLAIMER)
from modules.weather_advisor import advisory_report
from utils.json_utils import build_meta


def _section(entry: Any) -> Dict[str, Any]:
    """Wrap a stored {analysis, meta, filename} entry, or mark it as not run."""
    if not entry:
        return {"status": "not_run"}
    return {"status": "completed", "source_file": entry.get("filename"),
            "analysis": entry.get("analysis"), "meta": entry.get("meta")}


def build_consolidated_report(state: Dict[str, Any]) -> Dict[str, Any]:
    """Merge everything produced in the current session into one JSON document."""
    valuation = state.get("valuation")
    report: Dict[str, Any] = {
        "report_title": f"{APP_NAME} - Consolidated Site Report",
        "ppe_safety_audit": _section(state.get("ppe")),
        "crack_diagnostics": _section(state.get("crack")),
        "planning_and_valuation": ({"status": "completed", **valuation} if valuation else {"status": "not_run"}),
        "weather_advisory": advisory_report(state.get("weather", "Normal"), state.get("checklist_done")),
        "disclaimers": [AI_DISCLAIMER, STRUCTURAL_DISCLAIMER, ESTIMATE_DISCLAIMER],
    }
    live = any(report[k].get("meta", {}).get("mode") == "live"
               for k in ("ppe_safety_audit", "crack_diagnostics") if report[k]["status"] == "completed")
    demo = any(report[k].get("meta", {}).get("mode") == "demo"
               for k in ("ppe_safety_audit", "crack_diagnostics") if report[k]["status"] == "completed")
    notes: List[str] = []
    if demo:
        notes.append(DEMO_NOTICE + " (applies to sections marked mode = demo)")
    report["meta"] = build_meta("live" if live and not demo else "demo", "consolidated_report",
                                notes=notes, extra={"contains_demo_data": demo})
    return report


def report_to_markdown(report: Dict[str, Any]) -> str:
    """Human-readable Markdown version of the consolidated report."""
    L: List[str] = [f"# {report['report_title']}", f"_Generated: {report['meta']['generated_at_utc']}_", ""]
    if report["meta"].get("contains_demo_data"):
        L += [f"> **{DEMO_NOTICE}** (some sections contain sample data)", ""]

    ppe = report["ppe_safety_audit"]
    L.append("## 1. Site Safety & PPE Audit")
    if ppe["status"] == "completed":
        a = ppe["analysis"]
        L += [f"- Mode: **{ppe['meta']['mode']}** | Score: **{a['safety_score']}/100** | Status: **{a['overall_status']}**"]
        L += [f"- {k.replace('_', ' ').title()}: {v['status']} ({v['confidence']}%)" for k, v in a["ppe_detection"].items()]
        L += ["", "**Hazards**"] + [f"- [{h['severity']}] {h['hazard']} - {h['corrective_action']}" for h in a["hazards"]]
        L += ["", "**Recommendations**"] + [f"- {r}" for r in a["recommendations"]]
    else:
        L.append("_Not run in this session._")

    crack = report["crack_diagnostics"]
    L += ["", "## 2. Crack Diagnostics"]
    if crack["status"] == "completed":
        a = crack["analysis"]
        L += [f"- Mode: **{crack['meta']['mode']}** | Defect: **{a['defect_type']}** | Severity: **{a['severity']}** | "
              f"Width: ~{a['estimated_crack_width_mm']} mm | Urgency: **{a['urgency']}** | Confidence: {a['confidence']}%"]
        L += ["", "**Root causes**"] + [f"- {x}" for x in a["possible_root_causes"]]
        L += ["", "**Recommended repairs**"] + [f"- {x}" for x in a["recommended_repairs"]]
    else:
        L.append("_Not run in this session._")

    val = report["planning_and_valuation"]
    L += ["", "## 3. Planning & Valuation (conceptual)"]
    if val["status"] == "completed":
        i, f = val["inputs"], val["formatted"]
        L += [f"- {i['structure_type']} | {i['built_up_area_sqft']:,.0f} sq ft | {i['location_tier']} | "
              f"{i['completion_percent']:.0f}% complete | {i['quality_grade']} quality",
              f"- Total budget: **{f['total_project_budget']}** | CapEx incurred: **{f['capital_expenditure_incurred']}** | "
              f"Current valuation: **{f['current_market_asset_valuation']}**",
              f"- Steel: {f['steel_requirement']} | Cement: {f['cement_requirement']}"]
    else:
        L.append("_Not run in this session._")

    w = report["weather_advisory"]
    L += ["", f"## 4. Weather Advisory - {w['condition']} (risk: {w['risk_level']})", w["summary"], ""]
    L += ["**Alerts**"] + [f"- {x}" for x in w["safety_alerts"]]
    L += ["", "**Checklist**"] + [f"- [{'x' if c['done'] else ' '}] {c['item']}" for c in w["daily_checklist"]]
    L += ["", "---"] + [f"*{d}*" for d in report["disclaimers"]]
    return "\n".join(L)
