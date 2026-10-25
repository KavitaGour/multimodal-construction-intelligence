"""Gemini API wrapper (Epic 4 - Multimodal AI).

* Never raises raw SDK exceptions to the UI: everything is converted to GeminiError
  with a user-friendly message.
* The API key is only held in memory (never logged, never rendered).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from config import DEFAULT_GEMINI_MODEL
from utils.json_utils import parse_json_safely


class GeminiError(Exception):
    """Raised with a message that is safe to show to end users."""


def friendly_error(exc: Exception) -> str:
    """Translate SDK / network exceptions into plain-language messages."""
    msg = str(exc).lower()
    if any(k in msg for k in ("api key", "api_key", "401", "403", "permission", "unauthenticated")):
        return "Gemini rejected the API key. Please check that the key is correct and enabled."
    if any(k in msg for k in ("429", "quota", "resource_exhausted", "rate limit")):
        return "Gemini rate limit or quota reached. Wait a minute and try again."
    if any(k in msg for k in ("timeout", "timed out", "connection", "network", "unreachable", "dns", "ssl")):
        return "Network problem while contacting Gemini. Check your internet connection and retry."
    if any(k in msg for k in ("safety", "blocked", "prohibited")):
        return "Gemini blocked this request for safety reasons. Try a different image or question."
    if "not found" in msg or "404" in msg:
        return "The configured Gemini model was not found. Update DEFAULT_GEMINI_MODEL in config.py."
    return "Gemini request failed. Please try again in a moment."


class GeminiService:
    """Thin wrapper around the `google-genai` SDK."""

    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL):
        self.model = model
        self.init_error: Optional[str] = None
        self._client: Any = None
        self._types: Any = None
        try:
            from google import genai  # imported lazily so Demo Mode works without the SDK
            from google.genai import types

            self._client = genai.Client(api_key=api_key)
            self._types = types
        except ImportError:
            self.init_error = "The 'google-genai' package is not installed (pip install google-genai)."
        except Exception as exc:  # noqa: BLE001
            self.init_error = friendly_error(exc)

    @property
    def available(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------ core
    def _generate(self, contents: List[Any], system: Optional[str] = None,
                  json_mode: bool = False, temperature: float = 0.2) -> str:
        if not self.available:
            raise GeminiError(self.init_error or "Gemini client is not initialised.")
        cfg: Dict[str, Any] = {"temperature": temperature}
        if system:
            cfg["system_instruction"] = system
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        config = self._types.GenerateContentConfig(**cfg)

        last_exc: Optional[Exception] = None
        for attempt in range(2):  # one retry for transient failures
            try:
                resp = self._client.models.generate_content(
                    model=self.model, contents=contents, config=config)
                text = getattr(resp, "text", None)
                if not text:
                    raise GeminiError("Gemini returned an empty response (possibly blocked by safety filters).")
                return text
            except GeminiError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                text_msg = str(exc).lower()
                if any(k in text_msg for k in ("api key", "api_key", "401", "403", "permission")):
                    break  # retrying will not help
                time.sleep(1.0)
        raise GeminiError(friendly_error(last_exc or Exception("unknown")))

    # ------------------------------------------------------------- public API
    def generate_text(self, prompt: str, image: Any = None, system: Optional[str] = None) -> str:
        contents: List[Any] = [prompt] if image is None else [image, prompt]
        return self._generate(contents, system=system, temperature=0.4)

    def generate_json(self, prompt: str, image: Any = None,
                      system: Optional[str] = None) -> Tuple[Dict[str, Any], List[str]]:
        """Call Gemini expecting a JSON object. Retries once if the reply is malformed.

        Returns (parsed_dict, notes). Raises GeminiError if no usable JSON is obtained.
        """
        contents: List[Any] = [prompt] if image is None else [image, prompt]
        notes: List[str] = []
        raw = self._generate(contents, system=system, json_mode=True)
        data, parse_notes = parse_json_safely(raw)
        notes.extend(parse_notes)
        if data is None:
            retry_prompt = prompt + "\n\nYour previous reply was not valid JSON. Reply with ONLY the JSON object."
            contents = [retry_prompt] if image is None else [image, retry_prompt]
            raw = self._generate(contents, system=system, json_mode=True)
            data, parse_notes = parse_json_safely(raw)
            notes.append("First reply was not valid JSON; retried once.")
            notes.extend(parse_notes)
        if data is None:
            raise GeminiError("Gemini returned a response that could not be parsed as JSON.")
        return data, notes

    def ping(self) -> Tuple[bool, str]:
        """Cheap connectivity/key check used when the user connects an API key."""
        try:
            self._generate(["Reply with the single word: OK"], temperature=0.0)
            return True, "Connected to Gemini."
        except GeminiError as exc:
            return False, str(exc)
