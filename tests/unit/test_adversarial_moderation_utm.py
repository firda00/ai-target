"""
Adversarial Stress Test Suite for Moderation and UTM Utilities (Milestone 1).
Targets:
- src/ai_target/utils/moderation.py (validate_telegram_copy, validate_telegram_ads_copy, validate_richads_copy)
- src/ai_target/utils/utm.py (build_utm_url, append_utm_params)

Authored by Challenger M1-2.
"""

import unicodedata
from urllib.parse import parse_qs, urlsplit
import pytest

from ai_target.utils.moderation import (
    ModerationError,
    validate_richads_copy,
    validate_telegram_ads_copy,
    validate_telegram_copy,
)
from ai_target.utils.utm import append_utm_params, build_utm_url


# ============================================================================
# 1. Telegram Ads Character Limit Boundaries & Unicode Suite
# ============================================================================

class TestTelegramCharacterLimitBoundaries:
    """Rigorous boundary and Unicode codepoint testing for Telegram Ads copy."""

    def test_exactly_160_ascii_characters_passes(self):
        copy_160 = "a" * 160
        valid, reason = validate_telegram_copy(copy_160)
        assert valid is True
        assert reason is None

    def test_exactly_161_ascii_characters_fails(self):
        copy_161 = "a" * 161
        valid, reason = validate_telegram_copy(copy_161)
        assert valid is False
        assert "exceeds maximum allowed 160 characters" in reason

    def test_exactly_160_cyrillic_characters_passes(self):
        cyr_160 = "ж" * 160
        assert len(cyr_160.encode("utf-8")) == 320  # 320 bytes, 160 codepoints
        valid, reason = validate_telegram_copy(cyr_160)
        assert valid is True
        assert reason is None

    def test_exactly_161_cyrillic_characters_fails(self):
        cyr_161 = "ж" * 161
        valid, reason = validate_telegram_copy(cyr_161)
        assert valid is False
        assert "exceeds maximum allowed 160 characters" in reason

    def test_mixed_single_codepoint_emoji_and_cyrillic_160_passes(self):
        text_160 = ("🚀" * 10) + ("а" * 150)
        assert len(text_160) == 160
        valid, reason = validate_telegram_copy(text_160)
        assert valid is True
        assert reason is None

    def test_mixed_single_codepoint_emoji_and_cyrillic_161_fails(self):
        text_161 = ("🚀" * 10) + ("а" * 151)
        assert len(text_161) == 161
        valid, reason = validate_telegram_copy(text_161)
        assert valid is False
        assert "exceeds maximum allowed 160 characters" in reason

    def test_nfd_combining_characters_normalized_to_nfc(self):
        nfd_text = "e\u0301" * 80  # 160 code points in NFD, compresses to 80 chars in NFC
        valid, reason = validate_telegram_copy(nfd_text)
        assert valid is True
        assert reason is None

    def test_trailing_whitespace_stripped_before_length_check(self):
        text_160_with_spaces = ("a" * 160) + "    "
        valid, reason = validate_telegram_copy(text_160_with_spaces)
        assert valid is True
        assert reason is None

    def test_validate_telegram_ads_copy_raises_moderation_error(self):
        with pytest.raises(ModerationError, match="exceeds maximum allowed 160 characters"):
            validate_telegram_ads_copy("b" * 161)

        with pytest.raises(ModerationError, match="Raw external URLs"):
            validate_telegram_ads_copy("Check out https://evil.com for free money")


# ============================================================================
# 2. RichAds Character Caps Boundaries Suite
# ============================================================================

class TestRichAdsCharacterBoundaries:
    """Boundary testing for RichAds push notifications."""

    def test_richads_exact_max_limits_pass(self):
        valid, reason = validate_richads_copy("Т" * 30, "Б" * 45)
        assert valid is True
        assert reason is None

    def test_richads_title_31_fails(self):
        valid, reason = validate_richads_copy("Т" * 31, "Б" * 45)
        assert valid is False
        assert "title length (31) exceeds maximum allowed 30 characters" in reason

    def test_richads_body_46_fails(self):
        valid, reason = validate_richads_copy("Т" * 30, "Б" * 46)
        assert valid is False
        assert "body length (46) exceeds maximum allowed 45 characters" in reason

    def test_richads_whitespace_only_fails(self):
        valid, reason = validate_richads_copy("   ", "Valid body")
        assert valid is False
        assert "RichAds title must be a non-empty string" in reason

        valid_b, reason_b = validate_richads_copy("Valid title", "   ")
        assert valid_b is False
        assert "RichAds body must be a non-empty string" in reason_b


# ============================================================================
# 3. UTM Parameter Builder Adversarial Suite
# ============================================================================

class TestUTMBuilderAdversarial:
    """Stress-testing URL parameter builder against injection, duplicates, and fragments."""

    def test_spaces_encoded_properly(self):
        url = build_utm_url(
            base_url="https://example.com/promo",
            utm_source="meta ads",
            utm_medium="reels feed",
            utm_campaign="summer launch 2026",
            utm_content="hook variant A & B",
        )
        assert " " not in url
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        assert params["utm_source"] == ["meta ads"]
        assert params["utm_medium"] == ["reels feed"]

    def test_xss_and_sqli_payloads_safely_encoded(self):
        url_xss = build_utm_url(
            base_url="https://example.com",
            utm_source="meta",
            utm_medium="reels",
            utm_campaign="<script>alert(1)</script>",
            utm_content="v1",
        )
        assert "<script>" not in url_xss
        assert "%3Cscript%3E" in url_xss or "%3cscript%3e" in url_xss

        url_sqli = build_utm_url(
            base_url="https://example.com",
            utm_source="meta",
            utm_medium="reels",
            utm_campaign="'; DROP TABLE campaigns; --",
            utm_content="v1",
        )
        parsed = urlsplit(url_sqli)
        params = parse_qs(parsed.query)
        assert params["utm_campaign"] == ["'; DROP TABLE campaigns; --"]

    def test_existing_duplicate_utms_overwritten(self):
        url = build_utm_url(
            base_url="https://example.com/?utm_source=old1&utm_source=old2",
            utm_source="new_source",
            utm_medium="cpc",
            utm_campaign="c1",
            utm_content="v1",
        )
        params = parse_qs(urlsplit(url).query)
        assert params["utm_source"] == ["new_source"]

    def test_hash_fragment_and_spa_route_preservation(self):
        url_frag = build_utm_url(
            base_url="https://example.com/pricing#pro-tier",
            utm_source="meta",
            utm_medium="cpc",
            utm_campaign="c1",
            utm_content="v1",
        )
        p = urlsplit(url_frag)
        assert p.fragment == "pro-tier"
        assert "utm_source=meta" in p.query

        url_spa = build_utm_url(
            base_url="https://example.com/#/dashboard/profile",
            utm_source="meta",
            utm_medium="cpc",
            utm_campaign="c1",
            utm_content="v1",
        )
        p_spa = urlsplit(url_spa)
        assert p_spa.fragment == "/dashboard/profile"
        assert "utm_source=meta" in p_spa.query

    def test_multi_value_non_utm_query_parameters_preserved(self):
        """
        Adversarial check: build_utm_url should NOT drop multi-value non-UTM query parameters.
        e.g. ?tag=shoes&tag=sneakers -> both values must remain.
        """
        url = build_utm_url(
            base_url="https://example.com/catalog?tag=shoes&tag=sneakers",
            utm_source="meta",
            utm_medium="cpc",
            utm_campaign="c1",
            utm_content="v1",
        )
        params = parse_qs(urlsplit(url).query)
        # Empirical test: currently params_dict[k] = v drops 'shoes'
        assert params.get("tag") == ["shoes", "sneakers"], (
            f"Expected ['shoes', 'sneakers'], but got {params.get('tag')} (Silent data loss bug)"
        )


# ============================================================================
# 4. Telegram Ads URL Evasion Adversarial Challenge Suite
# ============================================================================

class TestTelegramURLEvasionVulnerabilities:
    """
    Empirical adversarial probes testing URL evasion techniques against validate_telegram_copy.
    These tests expose known evasion gaps where external links bypass moderation.
    """

    @pytest.mark.parametrize(
        "evasion_input, desc",
        [
            ("Заходи на crypto[.]com прямо сейчас", "Defanged dot with brackets domain[.]com"),
            ("Заходи на crypto(.)com прямо сейчас", "Defanged dot with parentheses domain(.)com"),
            ("Заходи на crypto .com прямо сейчас", "Space before dot in domain .com"),
            ("Подробности на bit.ly/bonus в канале", "Popular shortener bit.ly (.ly missing from TLD regex)"),
            ("Подробности на is.gd/bonus в канале", "Shortener is.gd (.gd missing from TLD regex)"),
            ("Подробности на t.co/abc в канале", "Single-letter domain t.co bypassed by {2,} quantifier"),
            ("Подробности на x.com/abc в канале", "Single-letter domain x.com bypassed by {2,} quantifier"),
            ("Переходи t\u200b.me/invite за бонусом", "Zero-width space U+200B inside t.me link"),
            ("Переходи domain\u200b.com за бонусом", "Zero-width space U+200B inside domain name"),
            ("Переходи t\xad.me/promo за бонусом", "Soft-hyphen U+00AD inside t.me link"),
            ("Сервер 0x7f000001 ждет тебя", "Hex-encoded IPv4 address 0x7f000001"),
            ("Сервер 2001:db8::1 ждет тебя", "IPv6 address 2001:db8::1"),
            ("Переходи на @channel.com за инфой", "Disguised domain @channel.com abusing handle masker"),
        ],
    )
    def test_evasion_attempts_must_be_blocked(self, evasion_input: str, desc: str):
        """
        Adversarial test: Each evasion vector MUST be detected and rejected.
        Failure of this test indicates a moderation bypass vulnerability.
        """
        valid, reason = validate_telegram_copy(evasion_input)
        assert valid is False, (
            f"VULNERABILITY CONFIRMED: Evasion vector '{desc}' bypassed moderation!\n"
            f"Input: {evasion_input}\n"
            f"Returned: valid=True, reason=None"
        )
