"""Unit tests (run: python -m unittest discover -s tests -v). No API key or network needed."""
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from modules.construction_assistant import answer_question, demo_answer
from modules.crack_analysis import analyze_crack, validate_crack_result
from modules.gemini_service import GeminiError
from modules.report_generator import build_consolidated_report, report_to_markdown
from modules.safety_analysis import analyze_ppe, validate_ppe_result
from modules.valuation import build_render_prompt, calculate_project_estimate, format_inr
from modules.weather_advisor import ADVISORIES, WEATHER_CONDITIONS, get_advisory
from utils.image_utils import load_image
from utils.json_utils import coerce_choice, coerce_number, parse_json_safely


def make_png(size=(200, 150), color=(120, 120, 120)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class FakeService:
    """Stands in for GeminiService to test live-mode code paths offline."""
    available = True
    model = "fake-model"

    def __init__(self, json_reply=None, text_reply="ok", error=None):
        self.json_reply, self.text_reply, self.error = json_reply, text_reply, error

    def generate_json(self, prompt, image=None, system=None):
        if self.error:
            raise GeminiError(self.error)
        return self.json_reply, ["fake"]

    def generate_text(self, prompt, image=None, system=None):
        if self.error:
            raise GeminiError(self.error)
        return self.text_reply


class JsonTests(unittest.TestCase):
    def test_fenced_json(self):
        d, _ = parse_json_safely('Here:\n```json\n{"a": 1}\n```')
        self.assertEqual(d, {"a": 1})

    def test_trailing_comma_and_python_literals(self):
        d, notes = parse_json_safely('{"a": True, "b": [1,2,], "c": None,}')
        self.assertEqual(d, {"a": True, "b": [1, 2], "c": None})
        self.assertTrue(notes)

    def test_truncated_json_is_closed(self):
        d, _ = parse_json_safely('{"safety_score": 70, "hazards": [{"hazard": "Edge", "severity": "Hi')
        self.assertIsNotNone(d)
        self.assertEqual(d["safety_score"], 70)

    def test_string_content_not_corrupted(self):
        d, _ = parse_json_safely('{"t": "None of the True workers",}')
        self.assertEqual(d["t"], "None of the True workers")

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_json_safely("no json here")[0])
        self.assertIsNone(parse_json_safely("")[0])
        self.assertIsNone(parse_json_safely(None)[0])

    def test_coercion(self):
        self.assertEqual(coerce_number("85%", 0, 100, as_int=True), 85)
        self.assertEqual(coerce_number(500, 0, 100), 100)
        self.assertEqual(coerce_number("abc", 0, 100, default=7), 7)
        self.assertEqual(coerce_choice("HIGH risk", ["Low", "High"], "Low"), "High")


class ValidationTests(unittest.TestCase):
    def test_ppe_validation_repairs_bad_values(self):
        out = validate_ppe_result({"safety_score": 250, "ppe_detection": {"helmet": {"status": "yes", "confidence": "90"}},
                                   "hazards": [{"hazard": "X", "severity": "extreme"}, "junk", {}],
                                   "recommendations": "wear PPE"})
        self.assertEqual(out["safety_score"], 100)
        self.assertEqual(out["ppe_detection"]["helmet"], {"status": "Unclear", "confidence": 90})
        self.assertEqual(set(out["ppe_detection"]), {"helmet", "high_visibility_vest", "steel_toe_boots", "safety_harness"})
        self.assertEqual(len(out["hazards"]), 1)
        self.assertEqual(out["hazards"][0]["severity"], "Medium")
        self.assertEqual(out["recommendations"], ["wear PPE"])

    def test_ppe_non_compliant_not_mistaken(self):
        res = validate_ppe_result({"safety_score": 20, "overall_status": "Non-Compliant"})
        self.assertEqual(res["overall_status"], "Non-Compliant")

    def test_crack_validation(self):
        out = validate_crack_result({"defect_type": "spalling damage", "severity": "bad",
                                     "estimated_crack_width_mm": "3.5 mm"})
        self.assertEqual(out["defect_type"], "Spalling")
        self.assertEqual(out["estimated_crack_width_mm"], 3.5)
        self.assertEqual(out["severity"], "Medium")

    def test_non_dict_input(self):
        self.assertEqual(validate_ppe_result(None)["safety_score"], 0)
        self.assertEqual(validate_crack_result("x")["defect_type"], "Hairline")


class AnalysisFlowTests(unittest.TestCase):
    def test_demo_ppe_is_labelled_and_deterministic(self):
        a1, m1 = analyze_ppe(None, None, make_png())
        a2, _ = analyze_ppe(None, None, make_png())
        self.assertEqual(a1, a2)
        self.assertEqual(m1["mode"], "demo")
        self.assertIn("Demonstration result", m1["demo_notice"])
        self.assertTrue(0 <= a1["safety_score"] <= 100)

    def test_demo_crack(self):
        a, m = analyze_crack(None, None, make_png())
        self.assertEqual(m["mode"], "demo")
        self.assertIn(a["defect_type"], ["Hairline", "Settlement", "Structural Shear", "Thermal Expansion", "Spalling"])

    def test_live_path_with_messy_model_output(self):
        svc = FakeService(json_reply={"safety_score": "77", "overall_status": "Needs Improvement"})
        a, m = analyze_ppe(svc, None, b"x")
        self.assertEqual(m["mode"], "live")
        self.assertEqual(a["safety_score"], 77)

    def test_live_failure_falls_back_to_demo(self):
        for fn in (analyze_ppe, analyze_crack):
            a, m = fn(FakeService(error="rate limit"), None, b"x")
            self.assertEqual(m["mode"], "demo")
            self.assertTrue(any("rate limit" in n for n in m["notes"]))

    def test_every_demo_scenario_is_valid(self):
        for i in range(60):
            a, _ = analyze_ppe(None, None, bytes([i]) * 8)
            self.assertEqual(a, validate_ppe_result(a))
            c, _ = analyze_crack(None, None, bytes([i]) * 8)
            self.assertEqual(c, validate_crack_result(c))


class ImageTests(unittest.TestCase):
    def test_valid_png(self):
        img, err = load_image("a.png", make_png())
        self.assertIsNone(err)
        self.assertEqual(img.mode, "RGB")

    def test_bad_inputs(self):
        self.assertIn("Unsupported", load_image("a.gif", make_png())[1])
        self.assertIn("empty", load_image("a.png", b"")[1])
        self.assertIn("could not be read", load_image("a.png", b"not an image")[1])
        self.assertIn("too small", load_image("a.png", make_png((8, 8)))[1])
        self.assertIsNotNone(load_image("a.jpg", make_png()[:60])[1])  # truncated file


class ValuationTests(unittest.TestCase):
    def test_calculation(self):
        r = calculate_project_estimate("Residential", 2500, "Tier 2", 40)
        e = r["estimates"]
        self.assertEqual(e["total_project_budget_inr"], 4_500_000)
        self.assertEqual(e["capital_expenditure_incurred_inr"], 1_800_000)
        self.assertEqual(e["steel_requirement_tonnes"], 10.0)
        self.assertEqual(e["cement_requirement_bags_50kg"], 1000)
        self.assertEqual(e["current_milestone"], "RCC superstructure")
        self.assertIn("conceptual", r["disclaimer"].lower())

    def test_tier_ordering(self):
        v = [calculate_project_estimate("Commercial", 5000, t, 100)["estimates"]["current_market_asset_valuation_inr"]
             for t in ("Tier 1", "Tier 2", "Tier 3")]
        self.assertTrue(v[0] > v[1] > v[2])

    def test_edges(self):
        zero = calculate_project_estimate("Other", 1000, "Tier 3", 0)
        self.assertEqual(zero["estimates"]["capital_expenditure_incurred_inr"], 0)
        full = calculate_project_estimate("Other", 1000, "Tier 3", 100)
        self.assertEqual(full["milestones"][-1]["status"], "Completed")

    def test_invalid_inputs_raise_valueerror(self):
        bad = [("Residential", -5, "Tier 1", 10), ("Residential", "abc", "Tier 1", 10),
               ("Residential", 1000, "Tier 1", 101), ("Castle", 1000, "Tier 1", 10),
               ("Residential", 1000, "Tier 9", 10), ("Residential", float("nan"), "Tier 1", 10),
               ("Residential", 10 ** 9, "Tier 1", 10)]
        for args in bad:
            with self.assertRaises(ValueError):
                calculate_project_estimate(*args)

    def test_inr_format(self):
        self.assertEqual(format_inr(12_50_00_000), "\u20b912.50 Cr")
        self.assertEqual(format_inr(4_50_000), "\u20b94.50 Lakh")
        self.assertEqual(format_inr(9_999), "\u20b99,999")

    def test_render_prompt(self):
        p = build_render_prompt("Commercial", 12000, "Tier 1", 70, "glass facade")
        for word in ("commercial", "12,000", "70%", "glass facade"):
            self.assertIn(word, p)


class WeatherAndChatTests(unittest.TestCase):
    def test_all_conditions_complete(self):
        for c in WEATHER_CONDITIONS:
            a = get_advisory(c)
            for k in ("risk_level", "alerts", "actions", "prohibited", "checklist"):
                self.assertTrue(a[k], f"{c}.{k} empty")
        self.assertEqual(get_advisory("bogus")["condition"], "Normal")
        self.assertEqual(set(ADVISORIES), set(WEATHER_CONDITIONS))

    def test_demo_chat_topics(self):
        self.assertIn("Heavy rain", demo_answer("What precautions should I take during heavy rain?"))
        self.assertIn("Pre-pour", demo_answer("What should I check before concrete pouring?"))
        self.assertIn("cracks", demo_answer("Why are cracks appearing on this wall?").lower())
        self.assertIn("I can help", demo_answer("tell me a joke"))

    def test_chat_never_raises(self):
        r, info = answer_question(None, "", [], {})
        self.assertEqual(info["mode"], "demo")
        r, info = answer_question(FakeService(error="network"), "heavy rain?", [], {})
        self.assertEqual(info["mode"], "demo")
        self.assertIn("Demonstration result", r)
        r, info = answer_question(FakeService(text_reply="Live answer"), "heavy rain?", [], {})
        self.assertEqual(info["mode"], "live")
        self.assertIn("Live answer", r)

    def test_chat_uses_crack_context(self):
        a, m = analyze_crack(None, None, b"1")
        r = demo_answer("why are there cracks on the wall", {"crack": {"analysis": a}})
        self.assertIn(a["defect_type"], r)


class ReportTests(unittest.TestCase):
    def test_empty_and_full_report_serialise(self):
        empty = build_consolidated_report({})
        json.dumps(empty)
        self.assertEqual(empty["ppe_safety_audit"]["status"], "not_run")
        a, m = analyze_ppe(None, None, b"1")
        c, cm = analyze_crack(None, None, b"1")
        full = build_consolidated_report({
            "ppe": {"analysis": a, "meta": m, "filename": "x.png"},
            "crack": {"analysis": c, "meta": cm, "filename": "y.png"},
            "valuation": calculate_project_estimate("Industrial", 9000, "Tier 3", 55),
            "weather": "Heavy Rain"})
        self.assertTrue(full["meta"]["contains_demo_data"])
        md = report_to_markdown(full)
        self.assertIn("Heavy Rain", md)
        self.assertIn("Demonstration result", md)
        json.dumps(full)


if __name__ == "__main__":
    unittest.main()
