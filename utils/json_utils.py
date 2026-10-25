"""Reusable JSON helpers (Epic 4 - JSON contracts).

Pipeline for model output:
    1. extract_json_block  -> find the JSON object inside free text / code fences
    2. repair_json         -> fix common LLM mistakes (trailing commas, truncation ...)
    3. parse_json_safely   -> try direct parse, then repaired parse
    4. coerce_* helpers    -> validate / clamp individual fields
Nothing in here ever raises on bad input; callers get None / defaults instead.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

_SMART_QUOTES = {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"}
_STRING_RE = re.compile(r'("(?:\\.|[^"\\])*")')


def extract_json_block(text: Optional[str]) -> Optional[str]:
    """Return the first top-level {...} block found in `text` (or None)."""
    if not text or not isinstance(text, str):
        return None
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    start = cleaned.find("{")
    if start == -1:
        return None

    depth, in_str, escaped = 0, False, False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start:i + 1]
    return cleaned[start:]  # truncated output - repair_json will try to close it


def _apply_outside_strings(text: str, fn) -> str:
    """Apply `fn` only to the parts of `text` that are not inside JSON strings."""
    parts = _STRING_RE.split(text)
    for i in range(0, len(parts), 2):
        parts[i] = fn(parts[i])
    return "".join(parts)


def repair_json(candidate: str) -> str:
    """Best-effort repair of malformed JSON text."""
    s = candidate
    for bad, good in _SMART_QUOTES.items():
        s = s.replace(bad, good)

    def fix_literals(seg: str) -> str:
        seg = re.sub(r"\bTrue\b", "true", seg)
        seg = re.sub(r"\bFalse\b", "false", seg)
        return re.sub(r"\bNone\b", "null", seg)

    s = _apply_outside_strings(s, fix_literals)
    s = _apply_outside_strings(s, lambda seg: re.sub(r",\s*([}\]])", r"\1", seg))

    # Close an unterminated string and any unbalanced brackets (truncated output).
    stack: List[str] = []
    in_str, escaped = False, False
    for ch in s:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    if in_str:
        s += '"'
    s = s.rstrip()
    if s.endswith(","):
        s = s[:-1]
    if s.endswith(":"):
        s += " null"
    s += "".join(reversed(stack))
    return _apply_outside_strings(s, lambda seg: re.sub(r",\s*([}\]])", r"\1", seg))


def parse_json_safely(text: Optional[str]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Parse model output into a dict. Returns (data_or_None, notes)."""
    notes: List[str] = []
    block = extract_json_block(text)
    if block is None:
        return None, ["No JSON object found in the model response."]
    attempts = (("direct", block), ("repaired", None))
    for label, cand in attempts:
        try:
            candidate = cand if cand is not None else repair_json(block)
            data = json.loads(candidate)
            if isinstance(data, dict):
                if label == "repaired":
                    notes.append("Model JSON was malformed and was repaired automatically.")
                return data, notes
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            notes.append(f"{label} parse failed: {exc}")
    return None, notes


# ----------------------------- field coercion -----------------------------
def coerce_number(value: Any, lo: Optional[float] = None, hi: Optional[float] = None,
                  default: float = 0.0, as_int: bool = False) -> Any:
    """Convert to a clamped number; falls back to `default` for junk input."""
    try:
        if isinstance(value, str):
            value = re.sub(r"[^\d.\-]", "", value)
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            raise ValueError("not finite")
    except (TypeError, ValueError):
        num = float(default)
    if lo is not None:
        num = max(lo, num)
    if hi is not None:
        num = min(hi, num)
    return int(round(num)) if as_int else round(num, 2)


def coerce_choice(value: Any, choices: Sequence[str], default: str) -> str:
    """Map `value` onto one of `choices` (case-insensitive, substring tolerant)."""
    if isinstance(value, str):
        v = value.strip().lower()
        for choice in choices:
            if v == choice.lower():
                return choice
        for choice in choices:
            if choice.lower() in v:
                return choice
    return default


def coerce_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def coerce_str_list(value: Any, limit: int = 12) -> List[str]:
    """Always return a clean list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out = [str(v).strip() for v in value if v is not None and str(v).strip()]
    return out[:limit]


# ------------------------------ misc helpers ------------------------------
def to_pretty_json(obj: Any) -> str:
    """Clean, human-readable JSON (used for downloads and previews)."""
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_meta(mode: str, module: str, model: Optional[str] = None,
               notes: Optional[List[str]] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Metadata block attached to every report (mode = 'live' | 'demo')."""
    from config import AI_DISCLAIMER, APP_NAME, DEMO_NOTICE

    meta: Dict[str, Any] = {
        "application": APP_NAME,
        "module": module,
        "mode": mode,
        "model": model if mode == "live" else None,
        "generated_at_utc": utc_timestamp(),
        "disclaimer": AI_DISCLAIMER,
        "notes": notes or [],
    }
    if mode != "live":
        meta["demo_notice"] = DEMO_NOTICE
    if extra:
        meta.update(extra)
    return meta
