"""
Unit tests for UTM Parameter Engine and Creative Copy Moderation Engine.
Location: tests/unit/test_utm_and_moderation.py
"""

import unittest
from urllib.parse import parse_qs, urlsplit

from ai_target.utils.moderation import (
    ModerationError,
    validate_richads_copy,
    validate_telegram_copy,
)
from ai_target.utils.utm import append_utm_params, build_utm_url


class TestUTMEngine(unittest.TestCase):
    """Test suite for build_utm_url and append_utm_params."""

    def test_build_utm_url_clean_happy_path(self):
        url = build_utm_url(
            base_url="https://example.com/landing",
            utm_source="meta",
            utm_medium="reels",
            utm_campaign="launch_q4",
            utm_content="hook_v1",
        )
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "example.com")
        self.assertEqual(parsed.path, "/landing")
        self.assertEqual(params["utm_source"], ["meta"])
        self.assertEqual(params["utm_medium"], ["reels"])
        self.assertEqual(params["utm_campaign"], ["launch_q4"])
        self.assertEqual(params["utm_content"], ["hook_v1"])

    def test_build_utm_url_preserves_existing_query_params(self):
        base = "https://example.com/shop?category=electronics&partner_id=88"
        url = build_utm_url(
            base_url=base,
            utm_source="tiktok",
            utm_medium="cpm",
            utm_campaign="spring_deals",
            utm_content="video_b",
        )
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)

        self.assertEqual(params["category"], ["electronics"])
        self.assertEqual(params["partner_id"], ["88"])
        self.assertEqual(params["utm_source"], ["tiktok"])
        self.assertEqual(params["utm_campaign"], ["spring_deals"])

    def test_build_utm_url_overwrites_existing_utm_params(self):
        base = "https://example.com/?utm_source=old_source&utm_campaign=old_camp"
        url = build_utm_url(
            base_url=base,
            utm_source="adsgram",
            utm_medium="rewarded",
            utm_campaign="new_camp",
            utm_content="hook_1",
        )
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["utm_source"], ["adsgram"])
        self.assertEqual(params["utm_campaign"], ["new_camp"])

    def test_build_utm_url_preserves_fragment(self):
        base = "https://example.com/pricing#tier-pro"
        url = build_utm_url(
            base_url=base,
            utm_source="telegram_ads",
            utm_medium="cpc",
            utm_campaign="ton_launch",
            utm_content="text_ad_1",
        )
        parsed = urlsplit(url)
        self.assertEqual(parsed.fragment, "tier-pro")
        self.assertIn("utm_source=telegram_ads", parsed.query)

    def test_build_utm_url_encodes_spaces_and_special_characters(self):
        url = build_utm_url(
            base_url="https://example.com/checkout",
            utm_source="meta",
            utm_medium="stories",
            utm_campaign="summer promo & discount",
            utm_content="variant/A+B",
        )
        self.assertIn("summer+promo+%26+discount", url)
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        self.assertEqual(params["utm_campaign"], ["summer promo & discount"])
        self.assertEqual(params["utm_content"], ["variant/A+B"])

    def test_build_utm_url_extra_parameters(self):
        url = build_utm_url(
            base_url="https://example.com",
            utm_source="richads",
            utm_medium="push",
            utm_campaign="crypto_bot",
            utm_content="push_v1",
            term="defi",
            custom_ref="partner_99",
        )
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["utm_term"], ["defi"])
        self.assertEqual(params["custom_ref"], ["partner_99"])

    def test_build_utm_url_missing_mandatory_raises_value_error(self):
        # Empty source
        with self.assertRaises(ValueError):
            build_utm_url("https://example.com", "", "medium", "camp", "cont")
        # None medium
        with self.assertRaises(ValueError):
            build_utm_url("https://example.com", "source", None, "camp", "cont")
        # Whitespace campaign
        with self.assertRaises(ValueError):
            build_utm_url("https://example.com", "source", "medium", "   ", "cont")
        # Empty content
        with self.assertRaises(ValueError):
            build_utm_url("https://example.com", "source", "medium", "camp", "")

    def test_build_utm_url_invalid_base_url_raises_value_error(self):
        with self.assertRaises(ValueError):
            build_utm_url("", "src", "med", "cmp", "cnt")
        with self.assertRaises(ValueError):
            build_utm_url("not_a_valid_url", "src", "med", "cmp", "cnt")

    def test_append_utm_params_alias(self):
        url1 = build_utm_url("https://example.com", "meta", "reels", "c1", "hook1")
        url2 = append_utm_params("https://example.com", "meta", "reels", "c1", "hook1")
        self.assertEqual(url1, url2)


class TestTelegramModeration(unittest.TestCase):
    """Test suite for validate_telegram_copy."""

    def test_valid_telegram_copy(self):
        copy = "Узнайте о запуске платформы в канале @ton_crypto_bot! Подробности в закрепе."
        valid, reason = validate_telegram_copy(copy)
        self.assertTrue(valid)
        self.assertIsNone(reason)

    def test_telegram_copy_length_boundaries(self):
        # 160 characters exact
        copy_160 = "a" * 160
        valid_160, reason_160 = validate_telegram_copy(copy_160)
        self.assertTrue(valid_160)
        self.assertIsNone(reason_160)

        # 161 characters
        copy_161 = "a" * 161
        valid_161, reason_161 = validate_telegram_copy(copy_161)
        self.assertFalse(valid_161)
        self.assertIn("exceeds maximum allowed 160 characters", reason_161)

    def test_telegram_copy_unicode_emojis(self):
        # Emojis and Cyrillic
        copy = "🚀 Премиальные сигналы TON: аналитика от экспертов @crypto_signals! Вступай."
        self.assertLessEqual(len(copy), 160)
        valid, reason = validate_telegram_copy(copy)
        self.assertTrue(valid)

    def test_telegram_copy_rejects_http_and_https_urls(self):
        copies = [
            "Подписывайтесь на https://example.com прямо сейчас!",
            "Переходи по ссылке http://ton-defi.io/join!",
        ]
        for copy in copies:
            valid, reason = validate_telegram_copy(copy)
            self.assertFalse(valid)
            self.assertIn("Raw external URLs", reason)

    def test_telegram_copy_rejects_www_prefix(self):
        copy = "Посетите www.crypto-arbitrage.com для бонуса."
        valid, reason = validate_telegram_copy(copy)
        self.assertFalse(valid)
        self.assertIn("www.", reason)

    def test_telegram_copy_rejects_tme_link(self):
        copy = "Вступайте в закрытый чат t.me/super_signals_pro!"
        valid, reason = validate_telegram_copy(copy)
        self.assertFalse(valid)
        self.assertIn("t.me", reason)

    def test_telegram_copy_rejects_raw_domain_names(self):
        copy = "Лучший обменник toncoin.org с мгновенным выводом."
        valid, reason = validate_telegram_copy(copy)
        self.assertFalse(valid)
        self.assertIn("Raw domain name or external link detected", reason)

    def test_telegram_copy_rejects_ip_addresses(self):
        copy = "Подключайтесь к серверу 192.168.1.100 для майнинга."
        valid, reason = validate_telegram_copy(copy)
        self.assertFalse(valid)
        self.assertIn("IP addresses are strictly prohibited", reason)

    def test_telegram_copy_rejects_obfuscated_links(self):
        copy = "Заходите на сайт cryptotrading[dot]com прямо сейчас."
        valid, reason = validate_telegram_copy(copy)
        self.assertFalse(valid)
        self.assertIn("Obfuscated domain name detected", reason)

    def test_telegram_copy_allows_valid_handles(self):
        copy = "Следите за новостями в @ton_official_channel и пишите @support_bot."
        valid, reason = validate_telegram_copy(copy)
        self.assertTrue(valid)
        self.assertIsNone(reason)

    def test_telegram_copy_exclamation_mark_limit(self):
        # 1 exclamation mark -> valid
        valid, _ = validate_telegram_copy("Отличная новость для криптоэнтузиастов!")
        self.assertTrue(valid)

        # 2 exclamation marks -> rejected
        valid_2, reason_2 = validate_telegram_copy("Отличная новость! Регистрируйся!")
        self.assertFalse(valid_2)
        self.assertIn("exclamation mark", reason_2)

    def test_telegram_copy_excessive_capitalization(self):
        # 5 letters ALL CAPS -> allowed
        valid_4, _ = validate_telegram_copy("Забирай свой БОНУС в канале @bonus_bot.")
        self.assertTrue(valid_4)

        # 10 letters ALL CAPS -> rejected
        valid_8, reason_8 = validate_telegram_copy("Большая РАСПРОДАЖА токенов в @ton_bot.")
        self.assertFalse(valid_8)
        self.assertIn("Excessive capitalization", reason_8)


class TestRichAdsModeration(unittest.TestCase):
    """Test suite for validate_richads_copy."""

    def test_valid_richads_copy(self):
        title = "TON Airdrop 2026"
        body = "Claim your exclusive 50 TON welcome bonus."
        valid, reason = validate_richads_copy(title, body)
        self.assertTrue(valid)
        self.assertIsNone(reason)

    def test_richads_title_boundary(self):
        # 30 chars
        title_30 = "A" * 30
        valid_30, _ = validate_richads_copy(title_30, "Valid body text")
        self.assertTrue(valid_30)

        # 31 chars
        title_31 = "A" * 31
        valid_31, reason_31 = validate_richads_copy(title_31, "Valid body text")
        self.assertFalse(valid_31)
        self.assertIn("title length (31) exceeds maximum", reason_31)

    def test_richads_body_boundary(self):
        # 45 chars
        body_45 = "B" * 45
        valid_45, _ = validate_richads_copy("Valid title", body_45)
        self.assertTrue(valid_45)

        # 46 chars
        body_46 = "B" * 46
        valid_46, reason_46 = validate_richads_copy("Valid title", body_46)
        self.assertFalse(valid_46)
        self.assertIn("body length (46) exceeds maximum", reason_46)

    def test_richads_empty_inputs(self):
        valid, reason = validate_richads_copy("", "Some body")
        self.assertFalse(valid)
        valid, reason = validate_richads_copy("Some title", "")
        self.assertFalse(valid)


if __name__ == "__main__":
    unittest.main()
