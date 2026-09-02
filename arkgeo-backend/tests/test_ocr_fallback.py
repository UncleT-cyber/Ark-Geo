"""OCR extractor fallback tests.

The OcrTextExtractor is supposed to be deterministic: when the vision LLM
fails or returns zero text regions it must fall back to the local
pytesseract engine (when present) rather than exiting empty or fabricating
evidence.
"""
from unittest.mock import patch

import pytest

from app.brain.clue_extractors.ocr_text import OcrTextExtractor, _fallback_ocr
from app.models import VisualEvidenceTag


_IMG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture
def extractor():
    return OcrTextExtractor()


@pytest.fixture(autouse=True)
def reset_tesseract_cache():
    from app.brain.clue_extractors import ocr_text

    ocr_text._tesseract_check.update({"checked": False, "ok": False})
    yield
    ocr_text._tesseract_check.update({"checked": False, "ok": False})


class TestOcrExtractor:
    def test_uses_llm_tags_when_present(self, extractor):
        llm_data = {
            "extracted_texts": [{"text": "VICTORIA ISLAND", "confidence": 0.85}],
            "geo_probabilistic_indicators": [
                {"indicator": "street signs", "weight": 0.7},
            ],
        }
        with patch("app.brain.clue_extractors.base.llm_client.vision_query",
                   return_value=llm_data):
            with patch("app.brain.clue_extractors.ocr_text._fallback_ocr") as m_fb:
                result = extractor.extract(_IMG)

        assert result is not None
        m_fb.assert_not_called()
        labels = {t.label for t in result.evidence_tags}
        assert "VICTORIA ISLAND" in labels
        assert "street signs" in labels
        assert any(t.category == "ocr" for t in result.evidence_tags)

    def test_falls_back_when_llm_returns_none(self, extractor):
        with patch("app.brain.clue_extractors.base.llm_client.vision_query",
                   return_value=None):
            with patch("app.brain.clue_extractors.ocr_text._fallback_ocr",
                       return_value=[VisualEvidenceTag(category="ocr", label="LAGOS", confidence=0.6)]):
                result = extractor.extract(_IMG)

        assert result is not None
        assert [t.label for t in result.evidence_tags] == ["LAGOS"]
        assert result.source == "ocr"

    def test_falls_back_when_llm_returns_zero_text_regions(self, extractor):
        """Vision model answers with infrastructure only, no text → OCR."""
        llm_data = {"extracted_texts": [], "geo_probabilistic_indicators": []}
        with patch("app.brain.clue_extractors.base.llm_client.vision_query",
                   return_value=llm_data):
            with patch("app.brain.clue_extractors.ocr_text._fallback_ocr",
                       return_value=[VisualEvidenceTag(category="ocr", label="NIGERIA", confidence=0.6)]):
                result = extractor.extract(_IMG)

        assert result is not None
        assert [t.label for t in result.evidence_tags] == ["NIGERIA"]

    def test_returns_none_honestly_when_both_paths_fail(self, extractor):
        with patch("app.brain.clue_extractors.base.llm_client.vision_query",
                   return_value=None):
            with patch("app.brain.clue_extractors.ocr_text._fallback_ocr", return_value=[]):
                result = extractor.extract(_IMG)

        assert result is None


class TestFallbackOcrEngine:
    def test_missing_tesseract_yields_no_tags(self):
        with patch("app.brain.clue_extractors.ocr_text._tesseract_available",
                   return_value=False):
            assert _fallback_ocr(_IMG) == []

    def test_engine_error_never_raises(self):
        with patch("app.brain.clue_extractors.ocr_text._tesseract_available",
                   return_value=True):
            with patch("pytesseract.image_to_string", side_effect=RuntimeError("boom")):
                assert _fallback_ocr(_IMG) == []

    @pytest.mark.skipif(
        not pytest.importorskip("pytesseract"),
        reason="pytesseract not installed",
    )
    def test_real_engine_extracts_text(self):
        import shutil

        if shutil.which("tesseract") is None:
            pytest.skip("tesseract binary not installed")
        from PIL import Image, ImageDraw

        from io import BytesIO

        img = Image.new("RGB", (640, 240), "white")
        ImageDraw.Draw(img).text((30, 90), "VICTORIA ISLAND", fill="black")
        buf = BytesIO()
        img.save(buf, format="JPEG")

        tags = _fallback_ocr(buf.getvalue())
        assert tags
        joined = " ".join(t.label.upper() for t in tags)
        assert "VICTORIA" in joined
        assert all(t.category == "ocr" for t in tags)
