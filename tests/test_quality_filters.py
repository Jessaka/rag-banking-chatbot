"""Unit tests for src.ingestion.quality_filters."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from src.ingestion.quality_filters import (
    has_repeated_char_patterns,
    has_corrupted_ocr,
    has_low_alpha_ratio,
    has_broken_diacritics,
    has_excessive_symbol_noise,
    is_scrambled_text,
    is_garbage_text,
    is_low_information,
    is_navigation_chunk,
    is_garbage_chunk,
    is_duplicate_chunk,
    is_blacklisted_section,
    score_chunk_quality,
    content_signature,
    filter_pricing_rows,
    is_valid_pricing_row,
    PricingQualityStats,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Garbage / OCR detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestHasRepeatedCharPatterns:
    def test_doubled_chars_czech(self):
        """PPoojjiiššttěěnníí → True (3+ double groups)"""
        assert has_repeated_char_patterns("PPoojjiiššttěěnníí")

    def test_doubled_chars_processing(self):
        """ZZpprraaccoovváánníí → True"""
        assert has_repeated_char_patterns("ZZpprraaccoovváánníí")

    def test_normal_text(self):
        """Normal Czech text → False"""
        assert not has_repeated_char_patterns("Vedení účtu")
        assert not has_repeated_char_patterns("Poplatek za vedení")

    def test_empty(self):
        assert not has_repeated_char_patterns("")

    def test_single_double(self):
        """Only one double group → False"""
        assert not has_repeated_char_patterns("Aapples")


class TestHasCorruptedOcr:
    def test_scattered_letters(self):
        """'Z Z p r a c o v á n í' → scattered letters pattern"""
        assert has_corrupted_ocr("Z Z p r a c o v á n í")

    def test_dot_noise(self):
        """'43..24.. ZZpprraaccoovváánníí' → dot_noise"""
        assert has_corrupted_ocr("43..24.. ZZpprraaccoovváánníí")

    def test_normal_text(self):
        assert not has_corrupted_ocr("Vedení účtu měsíčně 25 Kč")

    def test_repeated_punctuation(self):
        assert has_corrupted_ocr("Toto je text.... s tečkami")


class TestHasLowAlphaRatio:
    def test_pure_digits(self):
        assert has_low_alpha_ratio("12345 67890 11111")

    def test_garbage_symbols(self):
        assert has_low_alpha_ratio("43..24.. 11..22.. ///***")

    def test_valid_text(self):
        assert not has_low_alpha_ratio("Vedení účtu měsíčně")

    def test_czech_banking(self):
        assert not has_low_alpha_ratio("Poplatek za vedení běžného účtu")


class TestHasBrokenDiacritics:
    def test_private_use_area(self):
        """\ue646 characters → broken unicode"""
        assert has_broken_diacritics("\ue646Frekvence \ue646Dualkonto")

    def test_normal_unicode(self):
        assert not has_broken_diacritics("Pojištění odpovědnosti")

    def test_empty(self):
        assert not has_broken_diacritics("")


class TestHasExcessiveSymbolNoise:
    def test_many_symbols(self):
        assert has_excessive_symbol_noise("... /// +++ --- ***")

    def test_valid_text(self):
        assert not has_excessive_symbol_noise("Poplatek za vedení účtu 25 Kč")

    def test_empty(self):
        assert has_excessive_symbol_noise("")


class TestIsScrambledText:
    def test_scrambled_banking(self):
        """Single-char tokens scrambled"""
        assert is_scrambled_text("CB ěEa ž n é Ú Sč tr tay n ma 3i m zo 1 0 t r if y a c e n o")

    def test_scrambled_product(self):
        assert is_scrambled_text("CB ěEa ž n é Ú Sč tr tay n ma 3i m zo 1 0 t r if y a c e n o")

    def test_normal_text(self):
        assert not is_scrambled_text("Vedení běžného účtu měsíčně")


class TestIsGarbageText:
    def test_doubled_chars(self):
        assert is_garbage_text("PPoojjiiššttěěnníí")

    def test_scrambled_ocr(self):
        assert is_garbage_text("43..24.. ZZpprraaccoovváánníí")

    def test_normal_czech(self):
        assert not is_garbage_text("Vedení účtu měsíčně 25 Kč")

    def test_valid_banking(self):
        assert not is_garbage_text("Poplatek za vedení běžného účtu")

    def test_too_short(self):
        assert is_garbage_text("ab")

    def test_empty(self):
        assert is_garbage_text("")


# ═══════════════════════════════════════════════════════════════════════════════
# Chunk-level quality
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsLowInformation:
    def test_empty(self):
        assert is_low_information("")

    def test_whitespace(self):
        assert is_low_information("   \n\n  ")

    def test_short_text(self):
        assert is_low_information("Ahoj")

    def test_pure_numbers(self):
        assert is_low_information("12345")

    def test_valid_text(self):
        assert not is_low_information("Vedení účtu měsíčně 25 Kč")


class TestIsNavigationChunk:
    def test_menu_text(self):
        assert is_navigation_chunk("Menu Navigace Přihlášení Registrace Kontakt")

    def test_cookie_banner(self):
        assert is_navigation_chunk("Cookie banner GDPR Ochrana osobních údajů")

    def test_valid_banking(self):
        assert not is_navigation_chunk("Poplatek za vedení účtu 25 Kč měsíčně")

    def test_social_media_noise(self):
        assert is_navigation_chunk("Sdílet Facebook Instagram LinkedIn YouTube")


class TestIsGarbageChunk:
    def test_low_information(self):
        assert is_garbage_chunk("Ahoj")

    def test_ocr_garbage(self):
        assert is_garbage_chunk("PPoojjiiššttěěnníí")

    def test_navigation(self):
        assert is_garbage_chunk("Menu Navigace Přihlášení")

    def test_valid_chunk(self):
        assert not is_garbage_chunk("Vedení účtu měsíčně 25 Kč")


class TestScoreChunkQuality:
    def test_valid_chunk_scores_high(self):
        score = score_chunk_quality("Vedení běžného účtu měsíčně 25 Kč")
        assert score["quality_score"] >= 0.60
        assert not score["is_garbage"]
        assert not score["is_navigation"]

    def test_garbage_scores_low(self):
        score = score_chunk_quality("PPoojjiiššttěěnníí")
        assert score["quality_score"] < 0.50
        assert score["is_garbage"]

    def test_navigation_detected(self):
        score = score_chunk_quality("Menu Navigace Přihlášení Cookies")
        assert score["is_navigation"]


class TestIsDuplicateChunk:
    def test_identical_text(self):
        sigs: set[str] = set()
        assert not is_duplicate_chunk("Vedení účtu 25 Kč", sigs)
        assert is_duplicate_chunk("Vedení účtu 25 Kč", sigs)

    def test_normalized_match(self):
        sigs: set[str] = set()
        assert not is_duplicate_chunk("Vedení účtu 25 Kč", sigs)
        assert is_duplicate_chunk("Vedení účtu 25 Kč", sigs)


class TestContentSignature:
    def test_deterministic(self):
        assert content_signature("Vedení účtu") == content_signature("Vedení účtu")

    def test_normalizes_whitespace(self):
        assert content_signature("Vedení   účtu") == content_signature("Vedení účtu")


# ═══════════════════════════════════════════════════════════════════════════════
# Section blacklist
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsBlacklistedSection:
    def test_pro_media(self):
        assert is_blacklisted_section("/pro-media/tiskova-zprava")

    def test_blog(self):
        assert is_blacklisted_section("/blog/novinky")

    def test_kariera(self):
        assert is_blacklisted_section("/kariera/pozice")

    def test_normal_pricing(self):
        assert not is_blacklisted_section("/osobni/ucty/sazebnik")

    def test_full_url(self):
        assert is_blacklisted_section("https://www.rb.cz/pro-media/tiskova-zprava")


# ═══════════════════════════════════════════════════════════════════════════════
# Pricing row validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsValidPricingRow:
    def test_valid_row(self):
        row = {
            "fee_type": "Vedení účtu",
            "product_name": "Osobní účet BASIC",
            "fee_value": "25 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "confidence": 0.9,
        }
        valid, reason = is_valid_pricing_row(row)
        assert valid, f"Expected valid, got: {reason}"

    def test_header_artifact(self):
        row = {
            "fee_type": "Název položky",
            "product_name": "Osobní účet",
            "fee_value": "25 Kč",
        }
        valid, reason = is_valid_pricing_row(row)
        assert not valid
        assert reason == "header_artifact"

    def test_sloupec_product(self):
        row = {
            "fee_type": "Vedení",
            "product_name": "Sloupec 3",
            "fee_value": "25 Kč",
        }
        valid, reason = is_valid_pricing_row(row)
        assert not valid
        assert reason in ("header_artifact", "merged_column")

    def test_missing_fee_value(self):
        row = {
            "fee_type": "Vedení účtu",
            "product_name": "Osobní účet",
            "fee_value": "",
            "confidence": 0.9,
        }
        valid, reason = is_valid_pricing_row(row)
        assert not valid
        assert reason == "missing_fields"

    def test_ocr_garbage_fee(self):
        row = {
            "fee_type": "PPoojjiiššttěěnníí",
            "product_name": "Osobní účet",
            "fee_value": "25 Kč",
        }
        valid, reason = is_valid_pricing_row(row)
        assert not valid

    def test_broken_unicode(self):
        row = {
            "fee_type": "\ue646Frekvence",
            "product_name": "Dualkonto",
            "fee_value": "25 Kč",
        }
        valid, reason = is_valid_pricing_row(row)
        assert not valid
        assert reason == "broken_unicode"

    def test_low_confidence(self):
        row = {
            "fee_type": "Vedení účtu",
            "product_name": "Osobní účet",
            "fee_value": "25 Kč",
            "confidence": 0.3,
        }
        valid, reason = is_valid_pricing_row(row)
        assert not valid
        assert reason == "low_confidence"

    def test_scrambled_product(self):
        row = {
            "fee_type": "Vedení",
            "product_name": "CB ěEa ž n é Ú Sč tr tay n ma",
            "fee_value": "25 Kč",
        }
        valid, reason = is_valid_pricing_row(row)
        assert not valid
        assert reason == "garbage_text"

    def test_dataclass_like(self):
        """Test with a dict that has __dataclass_fields__ like behavior."""

        class FakeRow:
            __dataclass_fields__ = {"fee_type", "product_name", "fee_value", "currency", "period", "confidence", "conditions"}

            def __init__(self):
                self.fee_type = "Vedení účtu"
                self.product_name = "Osobní účet BASIC"
                self.fee_value = "25 Kč"
                self.currency = "CZK"
                self.period = "měsíčně"
                self.confidence = 0.9
                self.conditions = ""

        row = FakeRow()
        valid, reason = is_valid_pricing_row(row)
        assert valid, f"Expected valid dataclass, got: {reason}"

    def test_merged_column_fee_type(self):
        """fee_type containing a pricing value indicates merge"""
        row = {
            "fee_type": "Vedení 25 Kč",
            "product_name": "Osobní účet",
            "fee_value": "25 Kč",
            "confidence": 0.9,
        }
        valid, reason = is_valid_pricing_row(row)
        assert not valid
        assert reason == "merged_column"

    def test_valid_czech_banking_long(self):
        row = {
            "fee_type": "1. Cena tarifu",
            "product_name": "Osobní účet EXKLUSIVNÍ",
            "fee_value": "299 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "confidence": 1.0,
        }
        valid, reason = is_valid_pricing_row(row)
        assert valid, f"Expected valid, got: {reason}"


# ═══════════════════════════════════════════════════════════════════════════════
# Batch filter
# ═══════════════════════════════════════════════════════════════════════════════


class TestFilterPricingRows:
    def test_mixed_valid_and_garbage(self):
        rows = [
            {"fee_type": "Vedení účtu", "product_name": "Osobní účet", "fee_value": "25 Kč", "confidence": 0.9},
            {"fee_type": "Název položky", "product_name": "Osobní účet", "fee_value": "25 Kč", "confidence": 0.9},
            {"fee_type": "PPoojjiiššttěěnníí", "product_name": "Osobní účet", "fee_value": "25 Kč", "confidence": 0.9},
            {"fee_type": "Sloupec 1", "product_name": "Osobní účet", "fee_value": "25 Kč", "confidence": 0.9},
            {"fee_type": "", "product_name": "", "fee_value": "", "confidence": 0.0},
        ]
        valid, stats = filter_pricing_rows(rows)
        assert len(valid) == 1, f"Expected 1 valid, got {len(valid)}"
        assert stats.total_input == 5
        assert stats.valid_output == 1
        assert stats.total_filtered == 4

    def test_empty_input(self):
        valid, stats = filter_pricing_rows([])
        assert len(valid) == 0
        assert stats.total_input == 0

    def test_all_valid(self):
        rows = [
            {"fee_type": "Vedení účtu", "product_name": "Osobní účet BASIC", "fee_value": "25 Kč", "confidence": 1.0},
            {"fee_type": "1. Cena tarifu", "product_name": "Osobní účet EXKLUSIVNÍ", "fee_value": "299 Kč", "confidence": 1.0},
        ]
        valid, stats = filter_pricing_rows(rows)
        assert len(valid) == 2

    def test_rejects_orphan_product_context(self):
        row = {
            "fee_type": "1. Vedení jednoho běžného účtu",
            "product_name": "1. Vedení jednoho běžného účtu",
            "fee_value": "500 Kč",
            "currency": "CZK",
            "period": "měsíčně",
            "confidence": 0.95,
        }
        valid, reason = is_valid_pricing_row(row)
        assert not valid
        assert reason == "orphan_product_context"

    def test_rejects_missing_strict_currency_period(self):
        row = {
            "fee_type": "Poplatek za výpis",
            "product_name": "Osobní účet BASIC",
            "fee_value": "25",
            "confidence": 0.95,
        }
        valid, reason = is_valid_pricing_row(row)
        assert not valid
        assert reason in {"missing_currency", "missing_period"}


# ═══════════════════════════════════════════════════════════════════════════════
# Stats
# ═══════════════════════════════════════════════════════════════════════════════


class TestPricingQualityStats:
    def test_summary_format(self):
        stats = PricingQualityStats(
            total_input=100,
            valid_output=85,
            filtered_header_artifact=10,
            filtered_garbage_ocr=5,
        )
        s = stats.summary()
        assert "100" in s
        assert "85" in s
        assert "header=10" in s
        assert "garbage_ocr=5" in s

    def test_total_filtered(self):
        stats = PricingQualityStats(
            total_input=100,
            filtered_header_artifact=10,
            filtered_garbage_ocr=5,
            filtered_broken_unicode=2,
        )
        assert stats.total_filtered == 17

    def test_to_dict(self):
        stats = PricingQualityStats(total_input=100, valid_output=80)
        d = stats.to_dict()
        assert d["total_input"] == 100
        assert d["valid_output"] == 80


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
