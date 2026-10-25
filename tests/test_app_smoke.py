"""UI smoke tests using Streamlit's AppTest (run: python -m unittest discover -s tests -v).

File uploads and download-button clicks are not supported by AppTest, so those are
covered by module tests and the manual checklist in the README.
"""
import io
import os
import unittest

from PIL import Image

from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), (90, 100, 110)).save(buf, format="PNG")
    return buf.getvalue()


def fresh_app() -> AppTest:
    os.environ.pop("GEMINI_API_KEY", None)
    return AppTest.from_file(APP, default_timeout=60).run()


class AppSmokeTests(unittest.TestCase):
    def test_starts_without_api_key_in_demo_mode(self):
        at = fresh_app()
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(any("Demo Mode Active" in w.value for w in at.sidebar.warning))

    def test_every_page_renders(self):
        at = fresh_app()
        for page in at.sidebar.radio[0].options:
            at.sidebar.radio[0].set_value(page).run()
            self.assertEqual(len(at.exception), 0, page)

    def test_valuation_inputs_and_invalid_values(self):
        at = fresh_app()
        at.sidebar.radio[0].set_value([o for o in at.sidebar.radio[0].options if "Planning" in o][0]).run()
        at.slider[0].set_value(75).run()
        self.assertEqual(len(at.exception), 0)
        self.assertIn("75%", " ".join(m.value for m in at.markdown))
        at.selectbox[0].set_value("Industrial").run()
        at.number_input[0].set_value(50000.0).run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.error), 0)

    def test_weather_and_chat(self):
        at = fresh_app()
        at.sidebar.radio[0].set_value([o for o in at.sidebar.radio[0].options if "Assistant" in o][0]).run()
        at.radio(key="weather_radio").set_value("High Wind").run()
        self.assertEqual(len(at.exception), 0)
        self.assertIn("crane", " ".join(m.value for m in at.markdown).lower() + " ".join(w.value for w in at.warning).lower())
        at.chat_input[0].set_value("What should I check before concrete pouring?").run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.session_state["chat"]), 2)
        self.assertIn("Demonstration result", at.session_state["chat"][1]["content"])

    def test_bogus_api_key_does_not_crash(self):
        at = fresh_app()
        at.sidebar.text_input[0].set_value("not-a-real-key").run()
        at.sidebar.button[0].click().run()
        self.assertEqual(len(at.exception), 0)
        # offline / invalid key -> must stay in Demo Mode and show a friendly message
        self.assertIsNone(at.session_state["service"])

    def _open(self, at, keyword):
        at.sidebar.radio[0].set_value([o for o in at.sidebar.radio[0].options if keyword in o][0]).run()

    def test_ppe_and_crack_upload_flow(self):
        at = fresh_app()
        for keyword, button_key, state_key in (("PPE", "run_ppe", "ppe"), ("Crack", "run_crack", "crack")):
            self._open(at, keyword)
            at.file_uploader[0].upload("bad.png", b"garbage", "image/png").run()
            self.assertTrue(any("could not be read" in e.value for e in at.error))
            at.file_uploader[0].upload("empty.png", b"", "image/png").run()
            self.assertTrue(any("empty" in e.value for e in at.error))
            at.file_uploader[0].upload("site.png", png_bytes(), "image/png").run()
            at.button(key=button_key).click().run()
            self.assertEqual(len(at.exception), 0)
            self.assertEqual(at.session_state[state_key]["meta"]["mode"], "demo")
            self.assertTrue(any("Demonstration result" in w.value for w in at.warning))
        self._open(at, "Report")
        self.assertEqual(len(at.exception), 0)


if __name__ == "__main__":
    unittest.main()
