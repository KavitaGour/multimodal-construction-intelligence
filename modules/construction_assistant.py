"""Construction Engineering Assistant chatbot (Epic 5).

Live mode  -> Gemini with session context (latest audits, weather, valuation).
Demo mode  -> deterministic keyword knowledge base (also used if Gemini fails).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from config import AI_DISCLAIMER, DEMO_NOTICE
from modules.gemini_service import GeminiError, GeminiService
from modules.weather_advisor import get_advisory

SYSTEM_PROMPT = (
    "You are a construction engineering and site-safety assistant for Indian construction projects. "
    "Give practical, concise, structured answers (short bullets are fine). Reference IS 456 (concrete) and "
    "OSHA-style safety principles where relevant. Use the provided site context when it is relevant. "
    "Do not invent site facts that are not in the context. For structural concerns, always recommend a "
    "qualified structural engineer. You are an AI assistant, not a certified authority."
)

# (keywords, title, answer) - first/highest keyword score wins
KNOWLEDGE_BASE: List[Tuple[Tuple[str, ...], str, str]] = [
    (("rain", "monsoon", "wet", "storm"), "Heavy rain precautions",
     "- **Electrical:** isolate non-essential temporary power, use RCCB/GFCI protection, keep cables off wet ground.\n"
     "- **Excavations:** inspect shoring/sloping before entry, dewater, keep spoil away from edges.\n"
     "- **Concrete:** postpone pours in heavy rain; cover fresh concrete and protect edges.\n"
     "- **Access:** clean mud from scaffolds/ramps, add anti-slip measures, secure cement in dry raised storage."),
    (("wind", "crane", "gust"), "High wind precautions",
     "- Follow the crane manufacturer's wind limit and stop lifts when exceeded; use tag lines.\n"
     "- Secure or remove loose sheets, formwork, tarpaulins and tools.\n"
     "- Restrict elevated work and keep full tie-off; set exclusion zones below.\n"
     "- Inspect scaffold ties and sheeting."),
    (("heat", "hot", "summer", "hydration", "sun"), "Extreme heat precautions",
     "- Provide water and shade; use work/rest cycles and move heavy tasks to cooler hours.\n"
     "- Use buddy checks for dizziness, cramps or confusion (heat illness).\n"
     "- For concrete: pour in cooler hours, control evaporation, and start curing immediately."),
    (("pour", "pouring", "placing", "before concrete", "concreting"), "Pre-pour checklist for concrete",
     "1. Formwork: line, level, rigidity, joints sealed, release agent applied.\n"
     "2. Reinforcement: bar size/spacing, laps, cover blocks (cover per IS 456 exposure), cleanliness.\n"
     "3. Embedded items (conduits, sleeves, anchors) fixed and approved.\n"
     "4. Concrete: correct mix grade, slump test, delivery time, cube moulds ready.\n"
     "5. Logistics: vibrators, standby equipment, lighting, access, labour, weather check.\n"
     "6. Curing plan ready (burlap/curing compound/ponding) and permit/sign-off obtained."),
    (("cure", "curing"), "Concrete curing",
     "Keep concrete moist and protected from rapid drying. IS 456 recommends moist curing for a minimum period "
     "(generally at least 7 days for ordinary Portland cement, longer for blended cements or hot/dry weather). "
     "Use wet burlap, ponding or curing compound and protect from wind and direct sun."),
    (("crack", "cracks", "wall", "plaster"), "Why cracks appear",
     "Common causes: plastic/drying shrinkage, thermal movement without joints, differential settlement, "
     "overloading/shear, reinforcement corrosion and poor curing.\n"
     "- Thin, random map cracks: usually shrinkage -> monitor and seal.\n"
     "- Stepped/diagonal cracks near foundations: possible settlement -> investigate soil/drainage.\n"
     "- Wide diagonal cracks at beams/columns: possible shear distress -> restrict loading and call a structural engineer.\n"
     "Use the **Crack Diagnostics** page for a photo-based initial assessment."),
    (("ppe", "helmet", "vest", "harness", "boots"), "PPE essentials",
     "- **Helmet** in all active zones; **hi-vis vest** near moving plant/traffic.\n"
     "- **Safety boots** (steel toe/mid-sole) against impact and punctures.\n"
     "- **Full-body harness** with anchored lanyard for work above ~1.8 m (6 ft) without guardrails.\n"
     "- Inspect PPE daily and replace damaged items; add gloves, eye and hearing protection as the task requires."),
    (("scaffold", "ladder", "height", "fall"), "Working at height",
     "- Use inspected, tagged scaffolds with full platforms, guardrails and toe boards.\n"
     "- Secure ladders and keep three points of contact.\n"
     "- Tie off 100% with anchors rated for fall arrest; prepare a rescue plan.\n"
     "- Prevent falling objects with toe boards, nets and exclusion zones."),
    (("excavation", "trench", "shoring"), "Excavation safety",
     "Inspect daily and after rain; use shoring, sloping or benching for deep cuts; provide ladders/exits "
     "within a short travel distance; keep spoil and equipment back from the edge; locate underground utilities before digging."),
    (("steel", "rebar", "reinforcement"), "Reinforcement checks",
     "Check bar grade/diameter, spacing, laps and anchorage, correct cover (cover blocks), clean bars free of loose rust or oil, "
     "and cap exposed rebar ends to prevent impalement injuries."),
    (("cement", "mix", "grade", "slump", "water cement"), "Concrete mix quality",
     "Match grade to design (e.g. M20/M25), control the water-cement ratio, test slump on delivery, cast cubes for strength testing "
     "and avoid adding site water to restore workability."),
    (("budget", "cost", "estimate", "valuation"), "Budget & valuation",
     "Use the **Planning & Valuation** page for a conceptual budget, material estimate and progress-based valuation. "
     "These are approximate planning figures, not quotes."),
    (("electric", "shock", "wiring"), "Electrical safety",
     "Use RCCB/GFCI protected distribution boards, intact insulated cables raised off the ground, proper earthing, "
     "lock-out/tag-out for maintenance, and keep electrics dry."),
]

FALLBACK = (
    "I can help with construction safety and engineering topics such as **weather precautions, pre-pour checks, "
    "curing, cracks, PPE, working at height, excavations, reinforcement and concrete mix quality**. "
    "Try asking, e.g. *\"What should I check before concrete pouring?\"*"
)

SUGGESTED_QUESTIONS = [
    "What precautions should I take during heavy rain?",
    "What should I check before concrete pouring?",
    "Why are cracks appearing on this wall?",
    "What PPE is required for work at height?",
]


def build_context(state: Dict[str, Any]) -> str:
    """Summarise what has been analysed in this session for the assistant."""
    lines: List[str] = []
    ppe = (state.get("ppe") or {}).get("analysis")
    if ppe:
        lines.append(f"Latest PPE audit: score {ppe['safety_score']}/100, status {ppe['overall_status']}, "
                     f"{len(ppe['hazards'])} hazard(s): " + "; ".join(h["hazard"] for h in ppe["hazards"][:5]))
    crack = (state.get("crack") or {}).get("analysis")
    if crack:
        lines.append(f"Latest crack analysis: {crack['defect_type']} ({crack['severity']}), "
                     f"~{crack['estimated_crack_width_mm']} mm, urgency {crack['urgency']}; "
                     f"causes: {'; '.join(crack['possible_root_causes'][:3])}")
    val = state.get("valuation")
    if val:
        i, f = val["inputs"], val["formatted"]
        lines.append(f"Project: {i['structure_type']}, {i['built_up_area_sqft']:,.0f} sq ft, {i['location_tier']}, "
                     f"{i['completion_percent']:.0f}% complete, budget {f['total_project_budget']}.")
    weather = state.get("weather")
    if weather:
        lines.append(f"Selected site weather: {weather} (risk {get_advisory(weather)['risk_level']}).")
    return "\n".join(lines) if lines else "No site analysis has been run yet in this session."


def demo_answer(question: str, state: Optional[Dict[str, Any]] = None) -> str:
    """Deterministic keyword-based answer (safe fallback)."""
    q = (question or "").lower()
    best, best_score = None, 0
    for keywords, title, answer in KNOWLEDGE_BASE:
        score = sum(2 if k in q else 0 for k in keywords)
        if score > best_score:
            best, best_score = (title, answer), score
    if best is None:
        return FALLBACK
    title, answer = best
    extra = ""
    crack = ((state or {}).get("crack") or {}).get("analysis")
    if crack and any(k in q for k in ("crack", "wall")):
        extra = (f"\n\n**From your latest crack analysis:** {crack['defect_type']} defect, severity {crack['severity']}, "
                 f"urgency *{crack['urgency']}*. Likely causes: {'; '.join(crack['possible_root_causes'][:2]) or 'n/a'}.")
    return f"**{title}**\n\n{answer}{extra}"


def answer_question(service: Optional[GeminiService], question: str,
                    history: List[Dict[str, str]], state: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Return (answer_markdown, info). `info['mode']` is 'live' or 'demo'. Never raises."""
    question = (question or "").strip()
    if not question:
        return "Please type a construction-related question.", {"mode": "demo"}
    if len(question) > 2000:
        question = question[:2000]

    if service is not None and service.available:
        try:
            convo = "\n".join(f"{m['role'].title()}: {m['content']}" for m in history[-6:])
            prompt = (f"SITE CONTEXT:\n{build_context(state)}\n\nCONVERSATION SO FAR:\n{convo or '(none)'}\n\n"
                      f"USER QUESTION:\n{question}\n\nAnswer helpfully and concisely.")
            text = service.generate_text(prompt, system=SYSTEM_PROMPT)
            return text.strip() + f"\n\n*{AI_DISCLAIMER}*", {"mode": "live"}
        except GeminiError as exc:
            note = f"*Live AI unavailable ({exc}) - showing a built-in demonstration answer.*\n\n"
            return note + f"*{DEMO_NOTICE}*\n\n" + demo_answer(question, state), {"mode": "demo", "error": str(exc)}
        except Exception:  # noqa: BLE001
            pass
    return f"*{DEMO_NOTICE}*\n\n" + demo_answer(question, state), {"mode": "demo"}
