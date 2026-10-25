"""Weather-aware safety advisories (Epic 5).

A curated, rule-based advisory library - deterministic and available offline.
It does NOT fetch live weather; the user selects the condition on site.
"""
from __future__ import annotations

from typing import Any, Dict, List

WEATHER_CONDITIONS = ["Normal", "High Wind", "Heavy Rain", "Extreme Heat"]

ADVISORIES: Dict[str, Dict[str, Any]] = {
    "Normal": {
        "icon": "\u2600\ufe0f",
        "risk_level": "Low",
        "summary": "Standard working conditions. Maintain routine controls and daily inspections.",
        "alerts": [
            "No weather-related restrictions, but normal site hazards (falls, struck-by, electrical) still apply.",
            "Re-assess conditions if sky, wind or temperature changes during the shift.",
        ],
        "actions": [
            "Hold the daily toolbox talk and record attendance.",
            "Inspect scaffolds, ladders, lifting gear and temporary electrics before use.",
            "Verify PPE (helmet, hi-vis vest, safety boots, harness at height) at site entry.",
            "Keep walkways clear and materials stacked safely.",
        ],
        "prohibited": [
            "Work at height without fall protection.",
            "Operating equipment without a valid operator authorisation.",
            "Bypassing guards, barricades or lock-out/tag-out controls.",
        ],
        "checklist": [
            "Toolbox talk completed and signed",
            "PPE checked for all workers",
            "Scaffolding & ladders inspected (tags up to date)",
            "Temporary electrical panels / cables inspected",
            "Excavations and openings barricaded",
            "Fire extinguishers and first-aid kit accessible",
            "Housekeeping: walkways and exits clear",
        ],
    },
    "High Wind": {
        "icon": "\U0001f32c\ufe0f",
        "risk_level": "High",
        "summary": "Strong winds increase the risk of falling objects, unstable loads and loss of balance at height.",
        "alerts": [
            "Crane and hoist operations may need to stop once wind exceeds the manufacturer's limit.",
            "Unsecured sheets, formwork, scaffold boards and packaging can become dangerous projectiles.",
            "Workers at height face a higher risk of losing balance or being struck by wind-blown debris.",
        ],
        "actions": [
            "Check the anemometer / forecast and follow the crane manufacturer's maximum wind speed; stop lifts when exceeded.",
            "Tie down or relocate loose materials, tarpaulins, sheets and formwork panels.",
            "Lower or secure crane booms and hoist loads; keep tag lines on all suspended loads.",
            "Restrict elevated work, and use 100% tie-off with secured tools (tool lanyards).",
            "Inspect scaffold ties and sheeting; remove debris netting that acts as a sail if required.",
            "Keep workers clear of the fall zone beneath elevated work and temporary hoardings.",
        ],
        "prohibited": [
            "Crane lifts of large-surface-area loads (sheets, panels) in gusty wind.",
            "Work on roof edges, unprotected slab edges or exposed scaffolds when gusts are strong.",
            "Handling sheet materials or tarpaulins at height without a second person.",
            "Leaving tools or materials unsecured at height.",
        ],
        "checklist": [
            "Wind speed checked and logged against equipment limits",
            "Loose materials secured or removed",
            "Crane boom parked / lifting plan reviewed",
            "Scaffold ties and sheeting inspected",
            "Elevated work suspended or reassessed",
            "Exclusion zones set up below elevated work",
            "Workers briefed on wind hazards",
        ],
    },
    "Heavy Rain": {
        "icon": "\U0001f327\ufe0f",
        "risk_level": "High",
        "summary": "Rain raises electrocution, slip and excavation-collapse risks and can damage fresh concrete.",
        "alerts": [
            "Wet conditions greatly increase electrical shock hazards from temporary wiring and tools.",
            "Excavations and trenches may collapse as soil becomes saturated; water may accumulate.",
            "Fresh concrete can be washed out or diluted, reducing strength and surface quality.",
            "Slippery scaffolds, ladders, ramps and formwork increase fall risk.",
        ],
        "actions": [
            "Isolate non-essential temporary power; use RCCB/GFCI protection and keep connections off the ground and covered.",
            "Inspect excavations before entry; check shoring, dewater, and keep spoil heaps away from the edge.",
            "Postpone concrete pours in heavy rain; cover fresh concrete with tarpaulin/plastic sheeting and protect edges.",
            "Check slump / water-cement ratio and avoid placing concrete into standing water (per good practice and IS 456).",
            "Clean mud from scaffolds and walkways; add anti-slip measures and extra lighting.",
            "Secure materials such as cement bags in dry, raised storage and cover aggregates.",
        ],
        "prohibited": [
            "Using damaged or non-RCCB-protected electrical equipment in wet areas.",
            "Entering unsupported or water-filled excavations.",
            "Pouring concrete during heavy rainfall without proper protection.",
            "Working on wet steel/scaffold surfaces at height without full fall protection.",
        ],
        "checklist": [
            "Temporary electrics isolated / RCCB tested",
            "Excavations inspected and dewatered",
            "Shoring / sloping verified",
            "Concrete pours postponed or fully covered",
            "Cement and dry materials stored off the ground and covered",
            "Scaffolds, ramps and access routes cleared of mud",
            "Site drainage and pumps checked",
        ],
    },
    "Extreme Heat": {
        "icon": "\U0001f525",
        "risk_level": "High",
        "summary": "High temperatures cause heat illness and accelerate concrete setting and moisture loss.",
        "alerts": [
            "Risk of heat exhaustion and heat stroke; symptoms include dizziness, confusion, cramps and hot dry skin.",
            "Workers who are new to the site or wearing heavy PPE are at greater risk.",
            "Hot-weather concreting can cause rapid slump loss, plastic shrinkage cracking and weak surfaces.",
            "Metal tools, formwork and scaffolds can become hot enough to burn skin.",
        ],
        "actions": [
            "Provide cool drinking water and shaded rest areas; encourage regular small drinks.",
            "Use work/rest cycles and shift heavy tasks to early morning or evening.",
            "Acclimatise new workers gradually and use buddy checks for heat-illness symptoms.",
            "Schedule pours in cooler hours; use chilled water/ice, retarding admixtures if specified, and shade aggregates.",
            "Start curing immediately: wet burlap, fog misting or curing compound; protect from wind and direct sun (IS 456 curing guidance).",
            "Provide breathable, light-coloured clothing under mandatory PPE and sun protection for neck and skin.",
        ],
        "prohibited": [
            "Continuous heavy labour in peak midday heat without rest.",
            "Leaving workers alone when they show heat-illness symptoms.",
            "Placing concrete in direct sun without curing and evaporation control.",
            "Handling unshaded hot metal surfaces without gloves.",
        ],
        "checklist": [
            "Drinking water and shaded rest area available",
            "Work/rest schedule communicated",
            "Heat-illness signs briefed; buddy system active",
            "Heavy tasks moved to cooler hours",
            "Concrete curing plan ready (burlap, misting, compound)",
            "First-aid / cooling facilities checked",
            "Hot metal surfaces and tools identified",
        ],
    },
}


def get_advisory(condition: str) -> Dict[str, Any]:
    """Return the advisory for a condition (falls back to Normal for unknown input)."""
    data = ADVISORIES.get(condition) or ADVISORIES["Normal"]
    return {"condition": condition if condition in ADVISORIES else "Normal", **data}


def advisory_report(condition: str, checklist_state: Dict[str, bool] | None = None) -> Dict[str, Any]:
    """JSON-friendly advisory (used by the consolidated report)."""
    adv = get_advisory(condition)
    state = checklist_state or {}
    items: List[Dict[str, Any]] = [{"item": t, "done": bool(state.get(t, False))} for t in adv["checklist"]]
    return {
        "condition": adv["condition"],
        "risk_level": adv["risk_level"],
        "summary": adv["summary"],
        "safety_alerts": adv["alerts"],
        "recommended_actions": adv["actions"],
        "prohibited_activities": adv["prohibited"],
        "daily_checklist": items,
        "source": "Curated rule-based advisory library (no live weather data).",
    }
