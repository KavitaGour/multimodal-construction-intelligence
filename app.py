"""Multimodal Construction Intelligence Platform - Streamlit entry point.

Run locally:   streamlit run app.py
Deploy:        Streamlit Community Cloud -> main file path = app.py
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, Optional

import pandas as pd
import streamlit as st

from config import (load_dotenv_file, AI_DISCLAIMER, ALLOWED_IMAGE_EXTENSIONS, APP_NAME, APP_SHORT_NAME, APP_VERSION,
                    DEMO_NOTICE, ESTIMATE_DISCLAIMER, MAX_UPLOAD_MB, PROJECT_TAG,
                    SAFETY_REFERENCE, STRUCTURAL_DISCLAIMER)
from modules.construction_assistant import SUGGESTED_QUESTIONS, answer_question
from modules.crack_analysis import analyze_crack
from modules.gemini_service import GeminiService
from modules.report_generator import build_consolidated_report, report_to_markdown
from modules.safety_analysis import PPE_ITEMS, analyze_ppe, ppe_summary
from modules.valuation import (LOCATION_TIERS, QUALITY_GRADES, STRUCTURE_TYPES, build_render_prompt,
                               calculate_project_estimate, format_inr, refine_render_prompt)
from modules.weather_advisor import WEATHER_CONDITIONS, get_advisory
from utils.image_utils import load_image
from utils.json_utils import to_pretty_json
from utils.ui_utils import (SEVERITY_COLORS, URGENCY_COLORS, badge, check_dependencies, hazard_card,
                            hero, inject_css, score_gauge, severity_badge, show_image,
                            show_metric_cards, status_badge)

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger("construction_ai")

st.set_page_config(page_title=APP_NAME, page_icon="\U0001f3d7\ufe0f", layout="wide",
                   initial_sidebar_state="expanded")


# =============================================================================
# EPIC 1 - environment, configuration, session state, API-key handling
# =============================================================================
SESSION_DEFAULTS: Dict[str, Any] = {
    "service": None,          # GeminiService or None (None => Demo Mode)
    "key_source": None,       # "sidebar" | "secrets" | "environment"
    "conn_msg": None,         # (level, text) shown in the sidebar
    "auto_connect_done": False,
    "ppe": None,              # {"analysis", "meta", "filename"}
    "crack": None,
    "valuation": None,
    "render_prompt": None,
    "weather": "Normal",
    "checklist_done": {},
    "chat": [],
}


def init_session_state() -> None:
    for key, default in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default.copy() if isinstance(default, (dict, list)) else default


def _key_from_secrets_or_env() -> tuple:
    """Look for GEMINI_API_KEY in Streamlit secrets, then environment variables."""
    try:
        secret = st.secrets.get("GEMINI_API_KEY", "")  # raises if no secrets file exists
        if secret:
            return str(secret), "secrets"
    except Exception:  # noqa: BLE001
        pass
    env = os.environ.get("GEMINI_API_KEY", "")
    return (env, "environment") if env else ("", None)


def connect_gemini(api_key: str, source: str, verify: bool = True) -> None:
    """Create the Gemini service. The raw key is never stored in session state - only the client."""
    api_key = (api_key or "").strip()
    if not api_key:
        st.session_state.conn_msg = ("warning", "Please paste a Gemini API key first.")
        return
    service = GeminiService(api_key)
    if not service.available:
        st.session_state.conn_msg = ("error", service.init_error or "Could not initialise Gemini.")
        return
    if verify:
        with st.spinner("Verifying API key..."):
            ok, msg = service.ping()
        if not ok:
            st.session_state.conn_msg = ("error", msg + " Staying in Demo Mode.")
            return
    st.session_state.service = service
    st.session_state.key_source = source
    st.session_state.conn_msg = ("success", "Live Gemini mode enabled.")


def get_service() -> Optional[GeminiService]:
    return st.session_state.get("service")


def is_live() -> bool:
    svc = get_service()
    return bool(svc and svc.available)


def auto_connect_once() -> None:
    if st.session_state.auto_connect_done:
        return
    st.session_state.auto_connect_done = True
    load_dotenv_file()
    key, source = _key_from_secrets_or_env()
    if key:
        connect_gemini(key, source, verify=False)


# =============================================================================
# Shared UI pieces
# =============================================================================
def demo_banner() -> None:
    if not is_live():
        st.warning("\U0001f9ea **Demo Mode Active** \u2014 no Gemini API key supplied. Outputs are realistic sample data. "
                   f"{DEMO_NOTICE}")


def result_banner(meta: Dict[str, Any]) -> None:
    if meta.get("mode") == "live":
        st.success(f"\u2705 Live analysis by Gemini ({meta.get('model')}). {AI_DISCLAIMER}")
    else:
        st.warning(f"\U0001f9ea **{DEMO_NOTICE}** Sample data - the uploaded image was not analysed.")
    if meta.get("notes"):
        with st.expander("Processing notes"):
            for n in meta["notes"]:
                st.write(f"- {n}")


def upload_image(label: str, key: str):
    """File uploader + validation. Returns (image, bytes, filename) or (None, None, None)."""
    ext_txt = ", ".join(e.strip(".").upper() for e in ALLOWED_IMAGE_EXTENSIONS)
    uploaded = st.file_uploader(f"{label} ({ext_txt}, max {MAX_UPLOAD_MB} MB)",
                                type=[e.strip(".") for e in ALLOWED_IMAGE_EXTENSIONS], key=key)
    if uploaded is None:
        return None, None, None
    data = uploaded.getvalue()
    image, error = load_image(uploaded.name, data)
    if error:
        st.error(f"\u274c {error}")
        return None, None, None
    return image, data, uploaded.name


def json_download(label: str, payload: Dict[str, Any], filename: str, key: str) -> None:
    st.download_button(label, data=to_pretty_json(payload), file_name=filename,
                       mime="application/json", key=key)


# =============================================================================
# Sidebar
# =============================================================================
ARCHITECTURE_TEXT = """
UI (Streamlit)  app.py
   |
   |-- utils/  : ui_utils, json_utils, image_utils
   |-- modules/
   |     gemini_service  --> Google Gemini API (or Demo Mode)
   |     safety_analysis     (PPE audit)
   |     crack_analysis      (defect diagnostics)
   |     valuation           (budget, INR, render prompt)
   |     weather_advisor     (rule-based advisories)
   |     construction_assistant (chatbot)
   |     report_generator    (JSON / Markdown)
   |
   '-- st.session_state  (no database)
"""

PAGES: Dict[str, Callable[[], None]] = {}  # filled after page functions are defined


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown(f'<div class="sbrand">\U0001f3d7\ufe0f {APP_SHORT_NAME}</div>', unsafe_allow_html=True)
        st.caption(APP_NAME)

        # --- Mode indicator -------------------------------------------------
        if is_live():
            st.success(f"\U0001f7e2 Live Mode - Gemini connected (key hidden, source: {st.session_state.key_source})")
        else:
            st.warning("\U0001f9ea **Demo Mode Active**")

        # --- API key (never echoed back) ------------------------------------
        if not is_live():
            with st.form("api_key_form", clear_on_submit=True):
                key = st.text_input("Gemini API key", type="password", placeholder="Paste key to enable live AI",
                                    help="Stored only in memory for this session. Get a key at aistudio.google.com/apikey")
                submitted = st.form_submit_button("Connect Gemini")
            if submitted:
                connect_gemini(key, "sidebar", verify=True)
                st.rerun()
        elif st.button("Disconnect / return to Demo Mode"):
            st.session_state.service = None
            st.session_state.key_source = None
            st.session_state.conn_msg = ("info", "Disconnected. Demo Mode active.")
            st.rerun()

        msg = st.session_state.conn_msg
        if msg:
            getattr(st, msg[0])(msg[1])

        st.divider()
        page = st.radio("Navigation", list(PAGES.keys()), key="nav", label_visibility="collapsed")
        st.divider()

        with st.expander("Architecture overview"):
            st.code(ARCHITECTURE_TEXT, language="text")
        with st.expander("Environment check"):
            for name, ok in check_dependencies().items():
                st.write(("\u2705 " if ok else "\u26a0\ufe0f ") + name)
            st.caption("If the Gemini SDK is missing the app still runs in Demo Mode.")
        with st.expander("Project information"):
            st.markdown(f"**{PROJECT_TAG}**  \nVersion {APP_VERSION}  \n"
                        "Stack: Python, Streamlit, Google Gemini, Pillow, Pandas, Plotly.  \n"
                        f"_{AI_DISCLAIMER}_")
    return page


# =============================================================================
# Overview page
# =============================================================================
def page_overview() -> None:
    hero(APP_NAME, "AI-assisted site safety, structural diagnostics, project valuation and daily site guidance.")
    demo_banner()

    done = lambda k: "\u2705 Done" if st.session_state.get(k) else "\u2796 Not run"  # noqa: E731
    show_metric_cards([
        ("Mode", "Live AI" if is_live() else "Demo", "Gemini connected" if is_live() else "No API key"),
        ("PPE Audit", done("ppe"), None),
        ("Crack Diagnostics", done("crack"), None),
        ("Valuation", done("valuation"), None),
    ])
    st.write("")
    c1, c2, c3 = st.columns(3)
    c1.markdown("#### \U0001f9baSafety & Structures\n- PPE audit from site photos\n- Hazard cards with severity\n"
                "- Crack classification & repair guidance")
    c2.markdown("#### \U0001f4b0 Planning\n- Budget, CapEx & valuation in INR\n- Steel & cement estimates\n"
                "- Milestone tracking & AI render prompt")
    c3.markdown("#### \U0001f4ac Daily Operations\n- Weather safety advisories\n- Daily checklists\n"
                "- Construction engineering chatbot")

    st.markdown("#### Quick start")
    st.markdown("1. Pick a module in the sidebar.\n2. Upload an image (or use the calculators).\n"
                "3. Download the JSON report.\n4. Add a Gemini API key in the sidebar to switch from Demo to Live AI.")
    with st.expander("Capstone epic coverage"):
        st.dataframe(pd.DataFrame([
            ("Epic 1", "Requirements & Environment", "Sidebar, config.py, demo mode, key handling"),
            ("Epic 2", "PPE Vision & Crack Diagnostics", "PPE Audit + Crack Diagnostics pages"),
            ("Epic 3", "Planning & Valuation", "Planning & Valuation page"),
            ("Epic 4", "Multimodal AI & JSON Contracts", "gemini_service.py, json_utils.py"),
            ("Epic 5", "Chatbot & Weather Advisory", "Daily Site Assistant page"),
            ("Epic 6", "Interface, Testing & Deployment", "app.py, tests/, README"),
        ], columns=["Epic", "Area", "Where"]), hide_index=True)
    st.info(AI_DISCLAIMER)


# =============================================================================
# EPIC 2a - PPE audit page
# =============================================================================
def show_ppe_results(entry: Dict[str, Any]) -> None:
    a, meta = entry["analysis"], entry["meta"]
    st.divider()
    st.subheader("Audit results")
    result_banner(meta)
    summ = ppe_summary(a)

    g, m = st.columns([1, 2])
    g.plotly_chart(score_gauge(a["safety_score"]))
    with m:
        show_metric_cards([
            ("Overall status", a["overall_status"], None),
            ("PPE detected", f"{summ['detected']}/4", f"{summ['missing']} missing, {summ['unclear']} unclear"),
            ("Hazards found", str(summ["hazards"]), None),
        ])
        st.markdown(status_badge(a["overall_status"]), unsafe_allow_html=True)

    st.markdown("#### PPE checklist")
    cols = st.columns(4)
    for col, (key, label) in zip(cols, PPE_ITEMS):
        item = a["ppe_detection"][key]
        with col:
            st.markdown(f"**{label}**")
            st.markdown(status_badge(item["status"]), unsafe_allow_html=True)
            st.progress(item["confidence"] / 100, text=f"Confidence {item['confidence']}%")

    st.markdown("#### Hazards")
    if a["hazards"]:
        for h in a["hazards"]:
            st.markdown(hazard_card(h["hazard"], h["severity"], h["description"], h["corrective_action"]),
                        unsafe_allow_html=True)
    else:
        st.success("No hazards reported.")

    st.markdown("#### Corrective recommendations")
    for r in a["recommendations"] or ["No recommendations returned."]:
        st.markdown(f"- {r}")

    st.caption(f"{AI_DISCLAIMER} {SAFETY_REFERENCE}")
    payload = {"meta": meta, "source_file": entry.get("filename"), "analysis": a}
    json_download("\u2b07\ufe0f Download JSON Report", payload, "ppe_safety_report.json", "dl_ppe")
    with st.expander("View raw JSON"):
        st.json(payload)


def page_safety() -> None:
    hero("\U0001f9ba Site Safety & PPE Audit", "Upload a site photo to check helmets, vests, boots, harnesses and visible hazards.")
    demo_banner()
    st.caption(SAFETY_REFERENCE + " " + AI_DISCLAIMER)

    image, data, name = upload_image("Upload a construction-site image", "ppe_upload")
    if image is not None:
        c1, c2 = st.columns([3, 2])
        show_image(image, name)
        with c2:
            st.markdown("**What will be checked**")
            for _, label in PPE_ITEMS:
                st.write(f"- {label}")
            st.write("- General worker safety & visible hazards")
            if st.button("\U0001f50d Run PPE Safety Audit", type="primary", key="run_ppe"):
                with st.spinner("Analysing image..."):
                    analysis, meta = analyze_ppe(get_service(), image, data)
                st.session_state.ppe = {"analysis": analysis, "meta": meta, "filename": name}
    else:
        st.info("Upload a JPG/PNG image to begin. No image is analysed until you click **Run PPE Safety Audit**.")

    if st.session_state.ppe:
        show_ppe_results(st.session_state.ppe)


# =============================================================================
# EPIC 2b - Crack diagnostics page
# =============================================================================
def show_crack_results(entry: Dict[str, Any]) -> None:
    a, meta = entry["analysis"], entry["meta"]
    st.divider()
    st.subheader("Diagnostic results")
    result_banner(meta)
    st.error(f"\u26a0\ufe0f {STRUCTURAL_DISCLAIMER}")

    show_metric_cards([
        ("Defect classification", a["defect_type"], None),
        ("Severity", a["severity"], None),
        ("Estimated width", f"{a['estimated_crack_width_mm']} mm", "visual estimate"),
        ("Urgency", a["urgency"], None),
    ])
    st.write("")
    st.markdown(f"Severity {severity_badge(a['severity'])} &nbsp; Urgency "
                f"{badge(a['urgency'], URGENCY_COLORS.get(a['urgency'], '#868e96'))}", unsafe_allow_html=True)
    st.progress(a["confidence"] / 100, text=f"Model confidence {a['confidence']}%")
    st.caption("Crack width from a photo without a scale reference is only a rough estimate.")

    t1, t2, t3, t4 = st.tabs(["Visual observations", "Possible root causes", "Recommended repairs", "Raw JSON"])
    with t1:
        for x in a["visual_observations"] or ["None reported."]:
            st.markdown(f"- {x}")
    with t2:
        for x in a["possible_root_causes"] or ["None reported."]:
            st.markdown(f"- {x}")
    with t3:
        for x in a["recommended_repairs"] or ["None reported."]:
            st.markdown(f"- {x}")
    payload = {"meta": meta, "source_file": entry.get("filename"), "analysis": a,
               "structural_disclaimer": STRUCTURAL_DISCLAIMER}
    with t4:
        st.json(payload)
    json_download("\u2b07\ufe0f Download JSON Report", payload, "crack_diagnostics_report.json", "dl_crack")


def page_crack() -> None:
    hero("\U0001f9f1 Crack Diagnostics & Structural Integrity",
         "Classify visible defects: Hairline, Settlement, Structural Shear, Thermal Expansion, Spalling.")
    demo_banner()
    st.error(f"\u26a0\ufe0f {STRUCTURAL_DISCLAIMER}")

    image, data, name = upload_image("Upload a concrete / wall / structural surface image", "crack_upload")
    if image is not None:
        c1, c2 = st.columns([3, 2])
        show_image(image, name)
        with c2:
            st.write("Tip: use a sharp, well-lit close-up. Place a ruler or coin beside the crack for scale.")
            if st.button("\U0001f50d Analyse Defect", type="primary", key="run_crack"):
                with st.spinner("Analysing surface..."):
                    analysis, meta = analyze_crack(get_service(), image, data)
                st.session_state.crack = {"analysis": analysis, "meta": meta, "filename": name}
    else:
        st.info("Upload a JPG/PNG image to begin.")

    if st.session_state.crack:
        show_crack_results(st.session_state.crack)


# =============================================================================
# EPIC 3 - planning & valuation page
# =============================================================================
def page_planning() -> None:
    import plotly.express as px

    hero("\U0001f3d7\ufe0f Planning & Real Estate Valuation",
         "Conceptual budget, capital expenditure, asset valuation and material estimates in INR.")
    st.info(f"\U0001f4cc {ESTIMATE_DISCLAIMER}")

    c1, c2 = st.columns(2)
    structure = c1.selectbox("Structure type", STRUCTURE_TYPES)
    area = c1.number_input("Built-up area (sq ft)", min_value=100.0, max_value=5_000_000.0,
                           value=2500.0, step=100.0, format="%.0f")
    tier = c2.selectbox("Location tier", LOCATION_TIERS, index=1,
                        help="Tier 1: metros | Tier 2: large cities | Tier 3: smaller towns")
    quality = c2.selectbox("Finish quality", QUALITY_GRADES, index=1)
    completion = st.slider("Completion percentage", 0, 100, 40, format="%d%%")
    description = st.text_area("Optional description for the architectural render prompt", max_chars=400,
                               placeholder="e.g. east-facing facade, rooftop garden, red-brick elevation")

    try:
        result = calculate_project_estimate(structure, area, tier, completion, quality)
    except ValueError as exc:
        st.error(f"\u274c {exc}")
        return
    st.session_state.valuation = result
    f, e = result["formatted"], result["estimates"]

    st.subheader("Estimates")
    show_metric_cards([("Estimated total budget", f["total_project_budget"], f"{e['construction_rate_inr_per_sqft']:,} \u20b9/sq ft"),
                       ("CapEx incurred", f["capital_expenditure_incurred"], f"Remaining {f['remaining_budget']}"),
                       ("Current asset valuation", f["current_market_asset_valuation"],
                        f"Completed value {f['completed_asset_market_value']}")])
    st.write("")
    show_metric_cards([("Steel requirement", f["steel_requirement"], "TMT reinforcement (approx.)"),
                       ("Cement requirement", f["cement_requirement"], "50 kg bags (approx.)"),
                       ("Completion", f"{completion}%", e["current_milestone"])])

    st.markdown("#### Milestone progress")
    st.progress(completion / 100, text=f"{completion}% complete - {e['current_milestone']}")
    for m in result["milestones"]:
        a, b, c, d = st.columns([3, 1, 1.3, 2])
        a.write(m["milestone"])
        b.caption(m["range"])
        c.markdown(status_badge(m["status"]), unsafe_allow_html=True)
        d.progress(m["progress_pct"] / 100)

    t1, t2, t3 = st.tabs(["Charts", "Cost breakdown", "Assumptions"])
    with t1:
        left, right = st.columns(2)
        bars = pd.DataFrame({"Item": ["Total budget", "CapEx incurred", "Current valuation", "Completed value"],
                             "INR Lakh": [e["total_project_budget_inr"] / 1e5, e["capital_expenditure_incurred_inr"] / 1e5,
                                          e["current_market_asset_valuation_inr"] / 1e5,
                                          e["completed_asset_market_value_inr"] / 1e5]})
        left.plotly_chart(px.bar(bars, x="Item", y="INR Lakh", title="Budget vs valuation (INR Lakh)", text_auto=".1f"))
        cost_df = pd.DataFrame(result["cost_breakdown"])
        right.plotly_chart(px.pie(cost_df, names="item", values="amount_inr", title="Budget allocation", hole=0.4))
    with t2:
        cost_df = pd.DataFrame(result["cost_breakdown"])
        cost_df["amount"] = cost_df["amount_inr"].apply(format_inr)
        st.dataframe(cost_df[["item", "share_pct", "amount"]].rename(
            columns={"item": "Work package", "share_pct": "Share %", "amount": "Amount (approx.)"}), hide_index=True)
    with t3:
        for x in result["assumptions"]:
            st.markdown(f"- {x}")
        st.caption(ESTIMATE_DISCLAIMER)
    json_download("\u2b07\ufe0f Download Planning & Valuation JSON", result, "project_valuation_report.json", "dl_val")

    # ---- Architectural rendering prompt ------------------------------------
    st.divider()
    st.subheader("\U0001f3a8 AI architectural rendering prompt")
    st.caption("No image-generation API is configured, so this tool produces a ready-to-use text prompt "
               "for any text-to-image model (Gemini image, Imagen, Midjourney, DALL\u00b7E...). The rest of the app does not depend on it.")
    if st.button("Generate rendering prompt", key="gen_prompt"):
        st.session_state.render_prompt = build_render_prompt(structure, area, tier, completion, description)
    if st.session_state.render_prompt:
        st.code(st.session_state.render_prompt, language="text")
        st.download_button("\u2b07\ufe0f Download prompt (.txt)", st.session_state.render_prompt,
                           file_name="architectural_render_prompt.txt", key="dl_prompt")
        if is_live() and st.button("\u2728 Refine prompt with Gemini", key="refine_prompt"):
            with st.spinner("Refining..."):
                refined = refine_render_prompt(get_service(), st.session_state.render_prompt)
            if refined:
                st.session_state.render_prompt = refined.strip()
                st.rerun()
            else:
                st.warning("Gemini could not refine the prompt right now. The original prompt is unchanged.")


# =============================================================================
# EPIC 5 - daily site assistant (weather + chatbot)
# =============================================================================
def weather_tab() -> None:
    cond = st.radio("Current site weather condition", WEATHER_CONDITIONS, horizontal=True,
                    index=WEATHER_CONDITIONS.index(st.session_state.weather), key="weather_radio")
    st.session_state.weather = cond
    adv = get_advisory(cond)
    risk_color = SEVERITY_COLORS.get(adv["risk_level"], "#868e96")

    show_metric_cards([("Current condition", f"{adv['icon']} {cond}", None),
                       ("Risk level", adv["risk_level"], None),
                       ("Checklist items", str(len(adv["checklist"])), "daily tasks")])
    st.markdown(f"Risk {badge(adv['risk_level'], risk_color)} &nbsp; {adv['summary']}", unsafe_allow_html=True)
    st.caption("Curated rule-based advisory (no live weather feed). Always follow your site safety plan and local regulations.")

    left, right = st.columns(2)
    with left:
        st.markdown("#### \U0001f6a8 Safety alerts")
        for x in adv["alerts"]:
            (st.warning if adv["risk_level"] != "Low" else st.info)(x)
        st.markdown("#### \u2705 Recommended actions")
        for x in adv["actions"]:
            st.markdown(f"- {x}")
    with right:
        st.markdown("#### \u26d4 Prohibited / high-risk activities")
        for x in adv["prohibited"]:
            st.error(x)
        st.markdown("#### \U0001f4cb Daily checklist")
        done = {}
        for i, item in enumerate(adv["checklist"]):
            done[item] = st.checkbox(item, key=f"chk::{cond}::{i}")
        st.session_state.checklist_done = done
        st.progress(sum(done.values()) / len(done), text=f"{sum(done.values())}/{len(done)} completed")


def chat_tab() -> None:
    st.caption("Ask about weather precautions, pre-pour checks, curing, cracks, PPE, excavation and more. "
               + ("Answers come from Gemini." if is_live() else "Demo Mode: answers come from a built-in knowledge base."))
    cols = st.columns(len(SUGGESTED_QUESTIONS))
    for col, q in zip(cols, SUGGESTED_QUESTIONS):
        if col.button(q, key=f"sq::{q}"):
            st.session_state.pending_q = q
    if st.session_state.chat and st.button("Clear conversation", key="clear_chat"):
        st.session_state.chat = []
        st.rerun()

    for m in st.session_state.chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    question = st.chat_input("Ask a construction question...") or st.session_state.pop("pending_q", None)
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                state = {"ppe": st.session_state.ppe, "crack": st.session_state.crack,
                         "valuation": st.session_state.valuation, "weather": st.session_state.weather}
                reply, _info = answer_question(get_service(), question, st.session_state.chat, state)
            st.markdown(reply)
        st.session_state.chat.append({"role": "user", "content": question})
        st.session_state.chat.append({"role": "assistant", "content": reply})


def page_assistant() -> None:
    hero("\U0001f326\ufe0f Daily Site Assistant", "Weather-aware safety advisories and an interactive construction engineering assistant.")
    demo_banner()
    t1, t2 = st.tabs(["\U0001f326\ufe0f Weather advisory", "\U0001f4ac Engineering assistant"])
    with t1:
        weather_tab()
    with t2:
        chat_tab()


# =============================================================================
# Consolidated report page
# =============================================================================
def page_report() -> None:
    hero("\U0001f4c4 Consolidated Project Report", "Everything generated in this session in one downloadable document.")
    demo_banner()
    state = {"ppe": st.session_state.ppe, "crack": st.session_state.crack, "valuation": st.session_state.valuation,
             "weather": st.session_state.weather, "checklist_done": st.session_state.checklist_done}
    report = build_consolidated_report(state)
    show_metric_cards([("PPE audit", report["ppe_safety_audit"]["status"].replace("_", " ").title(), None),
                       ("Crack diagnostics", report["crack_diagnostics"]["status"].replace("_", " ").title(), None),
                       ("Valuation", report["planning_and_valuation"]["status"].replace("_", " ").title(), None),
                       ("Weather", st.session_state.weather, None)])
    if report["meta"].get("contains_demo_data"):
        st.warning(f"\U0001f9ea {DEMO_NOTICE} Sections marked mode = demo contain sample data.")
    if not any(st.session_state.get(k) for k in ("ppe", "crack", "valuation")):
        st.info("Run at least one module (PPE audit, crack analysis or valuation) to enrich this report.")

    c1, c2 = st.columns(2)
    with c1:
        json_download("\u2b07\ufe0f Download consolidated JSON", report, "consolidated_site_report.json", "dl_all_json")
    md = report_to_markdown(report)
    c2.download_button("\u2b07\ufe0f Download Markdown report", md, file_name="consolidated_site_report.md", key="dl_all_md")
    tab1, tab2 = st.tabs(["Readable preview", "JSON"])
    with tab1:
        st.markdown(md)
    with tab2:
        st.json(report)


# =============================================================================
# Main
# =============================================================================
PAGES.update({
    "\U0001f3e0 Overview": page_overview,
    "\U0001f9ba Site Safety & PPE Audit": page_safety,
    "\U0001f9f1 Crack Diagnostics": page_crack,
    "\U0001f3d7\ufe0f Planning & Valuation": page_planning,
    "\U0001f326\ufe0f Daily Site Assistant": page_assistant,
    "\U0001f4c4 Consolidated Report": page_report,
})


def main() -> None:
    init_session_state()
    inject_css()
    auto_connect_once()
    page = render_sidebar()
    try:
        PAGES[page]()
    except Exception:  # noqa: BLE001 - last line of defence: never show a raw traceback
        LOG.exception("Unhandled error while rendering page %s", page)
        st.error("\u274c Something went wrong while loading this page. Please try again or choose another module. "
                 "Your other results are kept.")


main()
