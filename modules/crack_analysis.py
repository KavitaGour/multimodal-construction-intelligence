"""Crack Diagnostics & Structural Integrity (Epic 2)."""
from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict, Optional, Tuple

from config import DEFECT_TYPES, SAFETY_REFERENCE, SEVERITY_LEVELS, URGENCY_LEVELS
from modules.gemini_service import GeminiError, GeminiService
from utils.json_utils import build_meta, coerce_choice, coerce_number, coerce_str_list

CRACK_PROMPT = f"""You are a structural defect assessment assistant reviewing a photo of a concrete surface or wall.
{SAFETY_REFERENCE}

Classify the most significant visible defect into exactly one of:
"Hairline", "Settlement", "Structural Shear", "Thermal Expansion", "Spalling".
Rules:
- Base every statement on what is visible. If no defect is visible or the image is unsuitable,
  say so in visual_observations, use defect_type "Hairline", severity "Low", confidence below 30.
- estimated_crack_width_mm is a rough visual estimate in millimetres (0-50). Without a scale
  reference it is uncertain: reflect that in a lower confidence.
- severity: "Low", "Medium", "High" or "Critical".
- urgency: "Monitor", "Repair Soon", "Urgent" or "Immediate".
- confidence is an integer 0-100.
- Repairs may include e.g. epoxy injection, structural re-grouting, crack stitching, surface sealing,
  jacketing - choose what fits.

Return ONLY this JSON object, no markdown, no commentary:
{{
  "defect_type": "",
  "severity": "",
  "estimated_crack_width_mm": 0,
  "visual_observations": [],
  "possible_root_causes": [],
  "recommended_repairs": [],
  "urgency": "",
  "confidence": 0
}}"""


def validate_crack_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce arbitrary model output into the strict crack JSON contract."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "defect_type": coerce_choice(raw.get("defect_type"), DEFECT_TYPES, "Hairline"),
        "severity": coerce_choice(raw.get("severity"), SEVERITY_LEVELS, "Medium"),
        "estimated_crack_width_mm": coerce_number(raw.get("estimated_crack_width_mm"), 0, 50, default=0),
        "visual_observations": coerce_str_list(raw.get("visual_observations")),
        "possible_root_causes": coerce_str_list(raw.get("possible_root_causes")),
        "recommended_repairs": coerce_str_list(raw.get("recommended_repairs")),
        "urgency": coerce_choice(raw.get("urgency"), URGENCY_LEVELS, "Repair Soon"),
        "confidence": coerce_number(raw.get("confidence"), 0, 100, default=0, as_int=True),
    }


_DEMO_SCENARIOS = [
    {
        "defect_type": "Hairline", "severity": "Low", "estimated_crack_width_mm": 0.2,
        "visual_observations": ["Fine, shallow cracks forming a random map pattern on the plaster/concrete skin.",
                                "No visible displacement across the crack faces.", "No staining or rust marks."],
        "possible_root_causes": ["Plastic or drying shrinkage during early curing.",
                                 "Inadequate curing or rapid surface moisture loss."],
        "recommended_repairs": ["Surface sealing with polymer-modified cement slurry or elastomeric coating.",
                                "Monitor with crack gauges; use epoxy injection if width grows beyond 0.3 mm."],
        "urgency": "Monitor", "confidence": 78,
    },
    {
        "defect_type": "Settlement", "severity": "High", "estimated_crack_width_mm": 3.5,
        "visual_observations": ["Stepped diagonal cracking following mortar joints near the plinth level.",
                                "Crack wider at the top than the bottom, suggesting rotation.",
                                "Slight door-frame misalignment nearby."],
        "possible_root_causes": ["Differential foundation settlement due to poor soil compaction.",
                                 "Water ingress or leaking drainage softening the sub-soil.",
                                 "Nearby excavation or tree-root moisture changes."],
        "recommended_repairs": ["Geotechnical investigation and foundation assessment by a structural engineer.",
                                "Stabilise cause first (drainage correction / underpinning) before repairs.",
                                "Structural re-grouting and crack stitching once movement has stopped."],
        "urgency": "Urgent", "confidence": 72,
    },
    {
        "defect_type": "Structural Shear", "severity": "Critical", "estimated_crack_width_mm": 5.0,
        "visual_observations": ["Diagonal (approx. 45 degree) crack running through a beam-column joint region.",
                                "Crack widening toward mid-depth with possible concrete crushing at edges.",
                                "Rust-coloured staining suggests reinforcement exposure."],
        "possible_root_causes": ["Insufficient shear reinforcement or stirrup spacing.",
                                 "Overloading beyond design capacity.",
                                 "Reinforcement corrosion reducing effective steel area."],
        "recommended_repairs": ["Immediately restrict loading and provide temporary propping.",
                                "Engineer-designed strengthening: epoxy injection with jacketing or FRP wrapping.",
                                "Structural re-grouting only after the strengthening design is approved."],
        "urgency": "Immediate", "confidence": 69,
    },
    {
        "defect_type": "Thermal Expansion", "severity": "Medium", "estimated_crack_width_mm": 1.2,
        "visual_observations": ["Near-vertical cracks at regular spacing along a long wall/slab span.",
                                "Cracks align with a change in section or opening corners."],
        "possible_root_causes": ["Absence or poor spacing of expansion/control joints.",
                                 "Large daily temperature swings on exposed surfaces."],
        "recommended_repairs": ["Cut and install proper control/expansion joints with flexible sealant.",
                                "Epoxy or flexible polyurethane injection for active cracks.",
                                "Apply reflective/insulating coating on exposed roof surfaces."],
        "urgency": "Repair Soon", "confidence": 74,
    },
    {
        "defect_type": "Spalling", "severity": "High", "estimated_crack_width_mm": 2.0,
        "visual_observations": ["Concrete cover has delaminated, exposing corroded reinforcement bars.",
                                "Rust staining and hollow-sounding patches likely around the damaged area."],
        "possible_root_causes": ["Reinforcement corrosion from chloride or carbonation attack.",
                                 "Insufficient concrete cover relative to IS 456 durability requirements.",
                                 "Persistent moisture exposure."],
        "recommended_repairs": ["Remove loose concrete, clean rust from bars and apply anti-corrosive primer.",
                                "Repair with polymer-modified repair mortar; restore cover and apply protective coating.",
                                "Replace sections of severely corroded rebar after engineer review."],
        "urgency": "Urgent", "confidence": 76,
    },
]


def build_demo_crack(image_bytes: Optional[bytes], note: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    digest = hashlib.sha256(image_bytes or b"demo").digest()
    scenario = copy.deepcopy(_DEMO_SCENARIOS[digest[1] % len(_DEMO_SCENARIOS)])
    notes = ["Sample scenario selected from built-in data. The uploaded image was NOT analysed."]
    if note:
        notes.append(note)
    return validate_crack_result(scenario), build_meta("demo", "crack_diagnostics", notes=notes)


def analyze_crack(service: Optional[GeminiService], image: Any,
                  image_bytes: Optional[bytes] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run crack diagnostics; falls back to demo data on any failure (never raises)."""
    if service is None or not service.available:
        return build_demo_crack(image_bytes)
    try:
        raw, notes = service.generate_json(CRACK_PROMPT, image=image)
        return validate_crack_result(raw), build_meta("live", "crack_diagnostics", model=service.model, notes=notes)
    except GeminiError as exc:
        return build_demo_crack(image_bytes, note=f"Live analysis failed ({exc}) - showing demonstration data instead.")
    except Exception:  # noqa: BLE001
        return build_demo_crack(image_bytes, note="Unexpected error during live analysis - showing demonstration data instead.")
