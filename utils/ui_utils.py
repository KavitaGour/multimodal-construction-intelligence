"""Reusable Streamlit UI helpers (Epic 6 - Interface)."""
from __future__ import annotations

import html
import importlib
from typing import Dict, Optional

import streamlit as st

SEVERITY_COLORS = {"Low": "#2e9e5b", "Medium": "#d99a00", "High": "#e8590c", "Critical": "#c92a2a"}
STATUS_COLORS = {"Detected": "#2e9e5b", "Not Detected": "#c92a2a", "Unclear": "#868e96",
                 "Compliant": "#2e9e5b", "Needs Improvement": "#d99a00", "Non-Compliant": "#c92a2a",
                 "Completed": "#2e9e5b", "In Progress": "#d99a00", "Pending": "#868e96"}
URGENCY_COLORS = {"Monitor": "#2e9e5b", "Repair Soon": "#d99a00", "Urgent": "#e8590c", "Immediate": "#c92a2a"}

CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 1250px;}
.hero {background: linear-gradient(120deg,#0b3d91 0%,#1c7ed6 60%,#22b8cf 100%); color:#fff;
       padding: 1.4rem 1.6rem; border-radius: 16px; margin-bottom: 1rem;}
.hero h1 {margin:0; font-size:1.7rem; color:#fff;} .hero p {margin:.3rem 0 0 0; opacity:.92;}
.badge {display:inline-block; padding:2px 11px; border-radius:999px; color:#fff; font-size:.78rem;
        font-weight:600; letter-spacing:.2px; white-space:nowrap;}
.mcard {border:1px solid rgba(128,128,128,.28); border-radius:14px; padding:.8rem 1rem; height:100%;
        background: rgba(128,128,128,.06);}
.mcard .lbl {font-size:.78rem; opacity:.7; text-transform:uppercase; letter-spacing:.5px;}
.mcard .val {font-size:1.45rem; font-weight:700; line-height:1.25; margin-top:.15rem;}
.mcard .sub {font-size:.78rem; opacity:.7; margin-top:.1rem;}
.hcard {border-left: 5px solid; border-radius: 10px; padding:.7rem .95rem; margin-bottom:.6rem;
        background: rgba(128,128,128,.07);}
.sbrand {font-size:1.25rem; font-weight:800; margin-bottom:.1rem;}
.small-muted {font-size:.8rem; opacity:.7;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(text: object) -> str:
    return html.escape(str(text))


def badge(text: str, color: str = "#868e96") -> str:
    return f'<span class="badge" style="background:{color}">{esc(text)}</span>'


def severity_badge(sev: str) -> str:
    return badge(sev, SEVERITY_COLORS.get(sev, "#868e96"))


def status_badge(status: str) -> str:
    return badge(status, STATUS_COLORS.get(status, "#868e96"))


def metric_card(label: str, value: str, sub: Optional[str] = None) -> str:
    sub_html = f'<div class="sub">{esc(sub)}</div>' if sub else ""
    return f'<div class="mcard"><div class="lbl">{esc(label)}</div><div class="val">{esc(value)}</div>{sub_html}</div>'


def show_metric_cards(cards: list) -> None:
    """cards = [(label, value, sub_or_None), ...] rendered in equal columns."""
    cols = st.columns(len(cards))
    for col, (label, value, sub) in zip(cols, cards):
        col.markdown(metric_card(label, value, sub), unsafe_allow_html=True)


def hazard_card(title: str, severity: str, body: str, action: str) -> str:
    color = SEVERITY_COLORS.get(severity, "#868e96")
    return (f'<div class="hcard" style="border-color:{color}"><b>{esc(title)}</b> &nbsp;{severity_badge(severity)}'
            f'<div style="margin-top:.35rem">{esc(body)}</div>'
            f'<div style="margin-top:.35rem"><b>Corrective action:</b> {esc(action)}</div></div>')


def hero(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="hero"><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div>', unsafe_allow_html=True)


def score_gauge(score: int, title: str = "Safety Score"):
    """Plotly gauge (imported lazily so a missing plotly never breaks the app)."""
    import plotly.graph_objects as go

    color = "#2e9e5b" if score >= 80 else "#d99a00" if score >= 50 else "#c92a2a"
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score, title={"text": title},
        gauge={"axis": {"range": [0, 100]}, "bar": {"color": color},
               "steps": [{"range": [0, 50], "color": "rgba(201,42,42,.18)"},
                         {"range": [50, 80], "color": "rgba(217,154,0,.18)"},
                         {"range": [80, 100], "color": "rgba(46,158,91,.18)"}]}))
    fig.update_layout(height=260, margin=dict(l=20, r=20, t=50, b=10))
    return fig


def show_image(image, caption: Optional[str] = None) -> None:
    """Full-width image that works on both new (width='stretch') and older Streamlit versions."""
    try:
        st.image(image, caption=caption, width="stretch")
    except TypeError:
        st.image(image, caption=caption, use_container_width=True)


def check_dependencies() -> Dict[str, bool]:
    """Epic 1 - dependency validation. True = importable."""
    result = {}
    for label, module in (("streamlit", "streamlit"), ("Pillow", "PIL"), ("pandas", "pandas"),
                          ("plotly", "plotly"), ("google-genai (Gemini SDK)", "google.genai")):
        try:
            importlib.import_module(module)
            result[label] = True
        except Exception:  # noqa: BLE001
            result[label] = False
    return result
