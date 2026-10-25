"""Site Safety & PPE Audit (Epic 2).

analyze_ppe() always returns (analysis_dict, meta_dict) and never raises:
live Gemini result -> validated JSON; any failure -> clearly labelled demo data.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from config import PPE_STATUSES, SAFETY_REFERENCE, SEVERITY_LEVELS
from modules.gemini_service import GeminiError, GeminiService
from utils.json_utils import (build_meta, coerce_choice, coerce_number, coerce_str,
                              coerce_str_list)

PPE_ITEMS = [
    ("helmet", "Safety Helmet"),
    ("high_visibility_vest", "High-Visibility Vest"),
    ("steel_toe_boots", "Steel-Toe Boots"),
    ("safety_harness", "Safety Harness"),
]

PPE_PROMPT = f"""You are a construction site safety inspector assisting with a visual PPE audit.
{SAFETY_REFERENCE}

Inspect ONLY what is actually visible in the image: safety helmets, high-visibility vests,
steel-toe boots, safety harnesses, general worker safety and visible site hazards.
Rules:
- Never invent detections. If no workers are visible, or an item cannot be seen (e.g. boots hidden),
  use status "Unclear" with a LOW confidence.
- If the image is not a construction site, set safety_score to 0, use "Unclear" everywhere,
  return no hazards and explain in recommendations.
- status must be one of: "Detected", "Not Detected", "Unclear".
- severity must be one of: "Low", "Medium", "High", "Critical".
- safety_score is an integer 0-100 (100 = fully compliant). confidence is an integer 0-100.

Return ONLY this JSON object, no markdown, no commentary:
{{
  "safety_score": 0,
  "overall_status": "Compliant | Needs Improvement | Non-Compliant",
  "ppe_detection": {{
    "helmet": {{"status": "", "confidence": 0}},
    "high_visibility_vest": {{"status": "", "confidence": 0}},
    "steel_toe_boots": {{"status": "", "confidence": 0}},
    "safety_harness": {{"status": "", "confidence": 0}}
  }},
  "hazards": [
    {{"hazard": "", "severity": "", "description": "", "corrective_action": ""}}
  ],
  "recommendations": []
}}"""


def derive_overall_status(score: int) -> str:
    if score >= 80:
        return "Compliant"
    if score >= 50:
        return "Needs Improvement"
    return "Non-Compliant"


def validate_ppe_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce arbitrary model output into the strict PPE JSON contract."""
    raw = raw if isinstance(raw, dict) else {}
    score = coerce_number(raw.get("safety_score"), 0, 100, default=0, as_int=True)

    detection_raw = raw.get("ppe_detection") if isinstance(raw.get("ppe_detection"), dict) else {}
    detection: Dict[str, Dict[str, Any]] = {}
    for key, _label in PPE_ITEMS:
        item = detection_raw.get(key) if isinstance(detection_raw.get(key), dict) else {}
        detection[key] = {
            "status": coerce_choice(item.get("status"), PPE_STATUSES, "Unclear"),
            "confidence": coerce_number(item.get("confidence"), 0, 100, default=0, as_int=True),
        }

    hazards: List[Dict[str, str]] = []
    raw_hazards = raw.get("hazards") if isinstance(raw.get("hazards"), list) else []
    for h in raw_hazards[:10]:
        if not isinstance(h, dict) or not coerce_str(h.get("hazard")):
            continue
        hazards.append({
            "hazard": coerce_str(h.get("hazard")),
            "severity": coerce_choice(h.get("severity"), SEVERITY_LEVELS, "Medium"),
            "description": coerce_str(h.get("description"), "No description provided."),
            "corrective_action": coerce_str(h.get("corrective_action"), "Review and correct before work continues."),
        })

    status = coerce_str(raw.get("overall_status"))
    overall = coerce_choice(status, ["Compliant", "Needs Improvement", "Non-Compliant"], derive_overall_status(score))
    # "Non-Compliant" contains "Compliant" -> make sure the longer match wins
    if "non" in status.lower():
        overall = "Non-Compliant"

    return {
        "safety_score": score,
        "overall_status": overall,
        "ppe_detection": detection,
        "hazards": hazards,
        "recommendations": coerce_str_list(raw.get("recommendations")),
    }


def ppe_summary(analysis: Dict[str, Any]) -> Dict[str, int]:
    """Counts used by the UI metric cards."""
    det = analysis.get("ppe_detection", {})
    return {
        "detected": sum(1 for v in det.values() if v.get("status") == "Detected"),
        "missing": sum(1 for v in det.values() if v.get("status") == "Not Detected"),
        "unclear": sum(1 for v in det.values() if v.get("status") == "Unclear"),
        "hazards": len(analysis.get("hazards", [])),
    }


# ------------------------------- demo data -------------------------------
def _ppe(h, hc, v, vc, b, bc, s, sc):
    return {
        "helmet": {"status": h, "confidence": hc},
        "high_visibility_vest": {"status": v, "confidence": vc},
        "steel_toe_boots": {"status": b, "confidence": bc},
        "safety_harness": {"status": s, "confidence": sc},
    }


_DEMO_SCENARIOS: List[Dict[str, Any]] = [
    {
        "safety_score": 82, "overall_status": "Compliant",
        "ppe_detection": _ppe("Detected", 94, "Detected", 91, "Unclear", 52, "Not Detected", 71),
        "hazards": [
            {"hazard": "Work at height without visible fall arrest", "severity": "High",
             "description": "A worker on an elevated platform shows no visible harness or lanyard anchorage.",
             "corrective_action": "Stop elevated work until harnesses are worn and anchored to a rated anchor point."},
            {"hazard": "Loose material near edge", "severity": "Medium",
             "description": "Unsecured bricks stacked close to an open edge may fall to lower levels.",
             "corrective_action": "Relocate materials away from edges and install toe boards."},
        ],
        "recommendations": [
            "Enforce full-body harness use above 1.8 m (6 ft) as per OSHA fall-protection principles.",
            "Hold a short toolbox talk on edge protection before the next shift.",
            "Add footwear checks to the daily PPE inspection list.",
        ],
    },
    {
        "safety_score": 38, "overall_status": "Non-Compliant",
        "ppe_detection": _ppe("Not Detected", 86, "Detected", 74, "Unclear", 40, "Not Detected", 82),
        "hazards": [
            {"hazard": "Unprotected floor edge", "severity": "Critical",
             "description": "Open slab edge with no guardrail or safety netting while workers operate nearby.",
             "corrective_action": "Install guardrails/safety nets immediately and restrict access to the edge zone."},
            {"hazard": "Workers without head protection", "severity": "High",
             "description": "At least one worker is working under overhead activity without a helmet.",
             "corrective_action": "Issue helmets and prohibit entry to active zones without one."},
            {"hazard": "Exposed reinforcement bars", "severity": "High",
             "description": "Uncapped rebar ends at working height create impalement risk.",
             "corrective_action": "Fit rebar protective caps or bend over the exposed ends."},
            {"hazard": "Debris and trip hazards", "severity": "Medium",
             "description": "Cluttered walkways with offcuts and cables increase slip/trip risk.",
             "corrective_action": "Implement daily housekeeping and designate material storage areas."},
        ],
        "recommendations": [
            "Suspend work in the affected area until edge protection and PPE are in place.",
            "Appoint a site safety officer to verify PPE at every entry point.",
            "Provide refresher PPE training and document attendance.",
        ],
    },
    {
        "safety_score": 94, "overall_status": "Compliant",
        "ppe_detection": _ppe("Detected", 97, "Detected", 95, "Detected", 83, "Detected", 88),
        "hazards": [
            {"hazard": "Minor housekeeping issue", "severity": "Low",
             "description": "Small amounts of packaging waste near the material stack.",
             "corrective_action": "Clear waste at end of shift and keep walkways free."},
        ],
        "recommendations": [
            "Maintain the current PPE discipline and keep daily inspection records.",
            "Continue periodic harness and lanyard inspections.",
        ],
    },
]


def build_demo_ppe(image_bytes: Optional[bytes], note: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Deterministic sample result (same image -> same sample). NOT based on image content."""
    digest = hashlib.sha256(image_bytes or b"demo").digest()
    scenario = copy.deepcopy(_DEMO_SCENARIOS[digest[0] % len(_DEMO_SCENARIOS)])
    notes = ["Sample scenario selected from built-in data. The uploaded image was NOT analysed."]
    if note:
        notes.append(note)
    return validate_ppe_result(scenario), build_meta("demo", "ppe_audit", notes=notes)


def analyze_ppe(service: Optional[GeminiService], image: Any,
                image_bytes: Optional[bytes] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run the PPE audit. Falls back to demo data when Gemini is unavailable or fails."""
    if service is None or not service.available:
        return build_demo_ppe(image_bytes)
    try:
        raw, notes = service.generate_json(PPE_PROMPT, image=image)
        return validate_ppe_result(raw), build_meta("live", "ppe_audit", model=service.model, notes=notes)
    except GeminiError as exc:
        return build_demo_ppe(image_bytes, note=f"Live analysis failed ({exc}) - showing demonstration data instead.")
    except Exception:  # noqa: BLE001 - never crash the UI
        return build_demo_ppe(image_bytes, note="Unexpected error during live analysis - showing demonstration data instead.")
