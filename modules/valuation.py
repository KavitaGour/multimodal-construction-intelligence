"""Project Planning & Real Estate Valuation (Epic 3).

All rates are simplified, conceptual planning assumptions in INR - NOT market quotations.
Edit the tables below to calibrate them for a specific city or project.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import ESTIMATE_DISCLAIMER
from modules.gemini_service import GeminiError, GeminiService
from utils.json_utils import build_meta

STRUCTURE_TYPES = ["Residential", "Commercial", "Industrial", "Other"]
LOCATION_TIERS = ["Tier 1", "Tier 2", "Tier 3"]
QUALITY_GRADES = ["Basic", "Standard", "Premium"]

# Construction cost in INR per sq ft (Tier 2, Standard quality baseline)
BASE_CONSTRUCTION_RATE = {"Residential": 1800, "Commercial": 2600, "Industrial": 2000, "Other": 2100}
# Market value of a COMPLETED asset in INR per sq ft (Tier 2 baseline)
BASE_MARKET_RATE = {"Residential": 6500, "Commercial": 9500, "Industrial": 4200, "Other": 5500}
TIER_COST_FACTOR = {"Tier 1": 1.30, "Tier 2": 1.00, "Tier 3": 0.82}
TIER_MARKET_FACTOR = {"Tier 1": 2.00, "Tier 2": 1.00, "Tier 3": 0.60}
QUALITY_FACTOR = {"Basic": 0.88, "Standard": 1.00, "Premium": 1.28}
# Rule-of-thumb material intensity per sq ft of built-up area
STEEL_KG_PER_SQFT = {"Residential": 4.0, "Commercial": 5.0, "Industrial": 6.0, "Other": 4.5}
CEMENT_BAGS_PER_SQFT = {"Residential": 0.40, "Commercial": 0.45, "Industrial": 0.50, "Other": 0.42}
CEMENT_BAG_KG = 50

MILESTONES = [  # (name, start %, end %)
    ("Site preparation & foundation", 0, 15),
    ("Plinth & sub-structure", 15, 30),
    ("RCC superstructure", 30, 60),
    ("Masonry, plaster & services rough-in", 60, 80),
    ("Finishing & fit-out", 80, 95),
    ("Testing, handover & occupancy", 95, 100),
]

COST_BREAKDOWN = [  # share of total budget
    ("Foundation & sub-structure", 0.15),
    ("RCC superstructure", 0.30),
    ("Masonry & plastering", 0.12),
    ("Finishing & fit-out", 0.20),
    ("MEP (electrical, plumbing, HVAC)", 0.15),
    ("External works & contingency", 0.08),
]


def format_inr(amount: float) -> str:
    """Format INR using Crore / Lakh notation."""
    sign = "-" if amount < 0 else ""
    a = abs(float(amount))
    if a >= 1e7:
        return f"{sign}\u20b9{a / 1e7:,.2f} Cr"
    if a >= 1e5:
        return f"{sign}\u20b9{a / 1e5:,.2f} Lakh"
    return f"{sign}\u20b9{a:,.0f}"


def milestone_status(completion: float) -> List[Dict[str, Any]]:
    """Per-milestone state: Completed / In Progress / Pending."""
    rows = []
    for name, start, end in MILESTONES:
        if completion >= end:
            state, pct = "Completed", 100
        elif completion > start:
            state, pct = "In Progress", int(round((completion - start) / (end - start) * 100))
        else:
            state, pct = "Pending", 0
        rows.append({"milestone": name, "range": f"{start}-{end}%", "status": state, "progress_pct": pct})
    return rows


def validate_inputs(structure_type: str, area_sqft: Any, tier: str, completion: Any, quality: str) -> Dict[str, Any]:
    """Validate raw UI inputs; raises ValueError with a user-friendly message."""
    if structure_type not in STRUCTURE_TYPES:
        raise ValueError("Please choose a valid structure type.")
    if tier not in LOCATION_TIERS:
        raise ValueError("Please choose a valid location tier.")
    if quality not in QUALITY_FACTOR:
        raise ValueError("Please choose a valid quality grade.")
    try:
        area = float(area_sqft)
        comp = float(completion)
    except (TypeError, ValueError):
        raise ValueError("Built-up area and completion must be numbers.") from None
    if not (area == area) or area <= 0:
        raise ValueError("Built-up area must be greater than zero.")
    if area > 5_000_000:
        raise ValueError("Built-up area looks unrealistic (max 5,000,000 sq ft).")
    if not (0 <= comp <= 100):
        raise ValueError("Completion percentage must be between 0 and 100.")
    return {"structure_type": structure_type, "built_up_area_sqft": area, "location_tier": tier,
            "completion_percent": comp, "quality_grade": quality}


def calculate_project_estimate(structure_type: str, area_sqft: Any, tier: str,
                               completion: Any, quality: str = "Standard") -> Dict[str, Any]:
    """Compute the conceptual budget / valuation / materials estimate."""
    inp = validate_inputs(structure_type, area_sqft, tier, completion, quality)
    area, comp = inp["built_up_area_sqft"], inp["completion_percent"]

    cost_rate = BASE_CONSTRUCTION_RATE[structure_type] * TIER_COST_FACTOR[tier] * QUALITY_FACTOR[quality]
    # quality shifts market value only slightly (about +/-5% of the quality cost factor)
    market_rate = BASE_MARKET_RATE[structure_type] * TIER_MARKET_FACTOR[tier] * (0.95 + 0.05 * QUALITY_FACTOR[quality])

    total_budget = area * cost_rate
    capex = total_budget * comp / 100
    completed_value = area * market_rate
    current_value = completed_value * comp / 100  # pro-rata recognised asset value
    steel_t = area * STEEL_KG_PER_SQFT[structure_type] / 1000
    cement_bags = area * CEMENT_BAGS_PER_SQFT[structure_type]

    current_ms = next((m["milestone"] for m in milestone_status(comp) if m["status"] != "Completed"),
                      MILESTONES[-1][0])
    estimates = {
        "construction_rate_inr_per_sqft": round(cost_rate),
        "market_rate_inr_per_sqft_when_complete": round(market_rate),
        "total_project_budget_inr": round(total_budget),
        "capital_expenditure_incurred_inr": round(capex),
        "remaining_budget_inr": round(total_budget - capex),
        "completed_asset_market_value_inr": round(completed_value),
        "current_market_asset_valuation_inr": round(current_value),
        "steel_requirement_tonnes": round(steel_t, 2),
        "cement_requirement_bags_50kg": round(cement_bags),
        "cement_requirement_tonnes": round(cement_bags * CEMENT_BAG_KG / 1000, 2),
        "current_milestone": current_ms,
    }
    formatted = {
        "total_project_budget": format_inr(total_budget),
        "capital_expenditure_incurred": format_inr(capex),
        "remaining_budget": format_inr(total_budget - capex),
        "current_market_asset_valuation": format_inr(current_value),
        "completed_asset_market_value": format_inr(completed_value),
        "steel_requirement": f"{steel_t:,.1f} tonnes",
        "cement_requirement": f"{cement_bags:,.0f} bags ({cement_bags * CEMENT_BAG_KG / 1000:,.1f} t)",
    }
    return {
        "inputs": inp,
        "estimates": estimates,
        "formatted": formatted,
        "milestones": milestone_status(comp),
        "cost_breakdown": [{"item": n, "share_pct": int(s * 100), "amount_inr": round(total_budget * s)}
                           for n, s in COST_BREAKDOWN],
        "assumptions": [
            "Rates are simplified planning assumptions (INR per sq ft) by structure type, location tier and quality.",
            "Steel and cement use rule-of-thumb intensities per sq ft of built-up area.",
            "Asset valuation is recognised pro-rata to completion; land cost is excluded.",
        ],
        "disclaimer": ESTIMATE_DISCLAIMER,
        "meta": build_meta("demo", "planning_valuation",
                           notes=["Deterministic formula-based estimate (no AI model involved)."],
                           extra={"calculation_type": "rule_based"}),
    }


# --------------------------- architectural rendering prompt ---------------------------
_STAGE_TEXT = [
    (15, "an active site in the earliest stage: cleared plot, excavated foundation pits, rebar cages, survey markers"),
    (30, "plinth beams and foundation walls completed, backfilling underway, column starter bars projecting upward"),
    (60, "a partially complete RCC frame with columns, slabs and shuttering visible, tower crane and scaffolding in place"),
    (80, "the structure fully framed with brick masonry, plaster and window openings, scaffolding on the facade"),
    (95, "near-complete building with facade finishing, glazing, paint and landscaping being finalised"),
    (101, "a fully completed, occupied-ready building with finished facade, landscaping and exterior lighting"),
]
_STYLE_BY_TYPE = {
    "Residential": "contemporary Indian residential architecture with balconies, textured plaster and warm accents",
    "Commercial": "modern commercial architecture with glass curtain walls, aluminium cladding and a landscaped entrance plaza",
    "Industrial": "functional industrial architecture with steel-framed roof trusses, large bays, loading docks and clean lines",
    "Other": "modern mixed-use civic architecture with clean lines and sustainable materials",
}
_SURROUNDINGS_BY_TIER = {
    "Tier 1": "dense metropolitan setting with high-rise neighbours and busy arterial road",
    "Tier 2": "growing city neighbourhood with mid-rise buildings and tree-lined streets",
    "Tier 3": "small-town setting with low-rise surroundings, open skyline and greenery",
}


def _size_descriptor(area: float) -> str:
    if area < 1500:
        return "compact"
    if area < 5000:
        return "mid-sized"
    if area < 25000:
        return "large"
    return "very large"


def build_render_prompt(structure_type: str, area_sqft: float, tier: str, completion: float,
                        description: str = "") -> str:
    """Create a detailed text-to-image prompt (no external image API required)."""
    stage = next(text for limit, text in _STAGE_TEXT if completion < limit)
    parts = [
        f"Photorealistic architectural visualisation of a {_size_descriptor(area_sqft)} {structure_type.lower()} "
        f"building of about {area_sqft:,.0f} sq ft built-up area, shown at {completion:.0f}% completion: {stage}.",
        f"Architectural style: {_STYLE_BY_TYPE.get(structure_type, _STYLE_BY_TYPE['Other'])}.",
        f"Setting: {_SURROUNDINGS_BY_TIER.get(tier, '')}, Indian climate and vegetation.",
    ]
    if description and description.strip():
        parts.append(f"Client notes to incorporate: {description.strip()[:400]}.")
    parts.append("Camera: eye-level three-quarter exterior view, 35mm lens, golden-hour lighting, soft shadows, "
                 "high detail, realistic materials, 16:9, no text or watermarks. "
                 "Include construction-safety elements (hoardings, signage, PPE-wearing workers) only if the project is under construction.")
    return "\n".join(parts)


def refine_render_prompt(service: Optional[GeminiService], prompt: str) -> Optional[str]:
    """Optionally polish the prompt with Gemini. Returns None if unavailable/failed."""
    if service is None or not service.available:
        return None
    try:
        return service.generate_text(
            "Improve this architectural rendering prompt for a text-to-image model. Keep all facts, make it vivid "
            "and concise (max 150 words). Return only the improved prompt.\n\n" + prompt)
    except GeminiError:
        return None
