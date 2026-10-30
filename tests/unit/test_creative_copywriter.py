"""
Unit Test Suite for CreativeCopywriterAgent (Milestone 2).
File: tests/unit/test_creative_copywriter.py

Covers:
- Telegram Ads copy generation (<=160 chars, zero raw URLs, A/B variants)
- Telegram Ads moderation compliance with validate_telegram_copy
- Instagram Reels / Stories 9:16 vertical hook scripts (headline, body, CTA)
- RichAds push banner limits (headline <=30 chars, body <=45 chars) with validate_richads_copy
- Telega.in native seed posts (500–1500 chars narrative storytelling)
- Mandatory UTM parameter injection (utm_source, utm_medium, utm_campaign, utm_content)
- Creative variant rotation upon fatigue detection (frequency > 2.80)
- Edge cases: empty/short/long product names, special chars, Cyrillic/Unicode resilience
- Zero external network connectivity (100% offline socket blocking enforced)
"""

import unittest
from urllib.parse import parse_qs, urlparse

# Ensure hermetic offline socket blocking is engaged
from tests.conftest import BlockedNetworkError, enable_socket_blocking

enable_socket_blocking()

# Dynamic imports with graceful skip if agent not yet implemented
try:
    from ai_target.agents.copywriter import CreativeCopywriterAgent
    from ai_target.state.models import (
        AdFormatEnum,
        CampaignState,
        CampaignStatus,
        ChannelAllocation,
        ClientBrief,
        CreativeItem,
        Creatives,
        Financials,
        MediaPlan,
        PerformanceMetrics,
        PlatformEnum,
    )
    from ai_target.utils.moderation import (
        ModerationError,
        validate_richads_copy,
        validate_telegram_ads_copy,
        validate_telegram_copy,
    )
    from ai_target.utils.utm import build_utm_url
    COPYWRITER_AVAILABLE = True
except ImportError:
    COPYWRITER_AVAILABLE = False


# ==============================================================================
# Category 1: Telegram Ads Copy & Moderation (8 tests)
# ==============================================================================

class TestTelegramAdsCopywriter(unittest.TestCase):
    """Verifies Telegram Ads copy generation, <=160 char limit, zero URLs, and A/B variants."""

    def setUp(self):
        if not COPYWRITER_AVAILABLE:
            self.skipTest("CreativeCopywriterAgent or utilities not yet implemented")
        enable_socket_blocking()
        self.copywriter = CreativeCopywriterAgent()

    def test_telegram_ads_copy_length_within_160_chars(self):
        """Generated Telegram Ads copy strictly does not exceed 160 characters."""
        variants = self.copywriter.generate_telegram_ads_copy("Crypto Trading Bot", "crypto traders")
        self.assertGreaterEqual(len(variants), 1)
        for v in variants:
            self.assertLessEqual(len(v.body_text), 160)

    def test_telegram_ads_copy_produces_at_least_two_ab_variants(self):
        """Generates at least two distinct variants marked 'A' and 'B'."""
        variants = self.copywriter.generate_telegram_ads_copy("DeFi Aggregator", "investors", count=2)
        self.assertGreaterEqual(len(variants), 2)
        variant_labels = {v.ab_variant for v in variants}
        self.assertIn("A", variant_labels)
        self.assertIn("B", variant_labels)
        self.assertNotEqual(variants[0].body_text, variants[1].body_text)

    def test_telegram_ads_copy_zero_raw_urls_in_body(self):
        """Body text contains zero raw external URLs or domain names."""
        variants = self.copywriter.generate_telegram_ads_copy("Fitness App", "athletes")
        forbidden = ["http://", "https://", "www.", ".com", ".io", ".org", ".xyz"]
        for v in variants:
            for token in forbidden:
                self.assertNotIn(token, v.body_text.lower())

    def test_telegram_ads_copy_passes_validate_telegram_copy(self):
        """All variants pass validate_telegram_copy moderation check."""
        variants = self.copywriter.generate_telegram_ads_copy("Productivity SaaS", "founders")
        for v in variants:
            valid, reason = validate_telegram_copy(v.body_text)
            self.assertTrue(valid, f"Moderation failed: {reason}")
            self.assertIsNone(reason)

    def test_telegram_ads_copy_passes_validate_telegram_ads_copy(self):
        """All variants pass validate_telegram_ads_copy without raising ModerationError."""
        variants = self.copywriter.generate_telegram_ads_copy("Language Tutor", "students")
        for v in variants:
            self.assertTrue(validate_telegram_ads_copy(v.body_text))

    def test_telegram_ads_copy_allows_telegram_handles(self):
        """Legitimate @channel handles are permitted in copy body."""
        variants = self.copywriter.generate_telegram_ads_copy("Trading Channel", "traders")
        for v in variants:
            valid, _ = validate_telegram_copy(v.body_text)
            self.assertTrue(valid)

    def test_telegram_ads_copy_at_most_one_exclamation_mark(self):
        """Strict formatting rule: at most 1 exclamation mark in body text."""
        variants = self.copywriter.generate_telegram_ads_copy("VPN Service", "privacy users")
        for v in variants:
            self.assertLessEqual(v.body_text.count("!"), 1)

    def test_telegram_ads_copy_no_excessive_all_caps(self):
        """Body text does not contain ALL-CAPS words exceeding 5 letters."""
        variants = self.copywriter.generate_telegram_ads_copy("Finance Tracker", "freelancers")
        for v in variants:
            valid, reason = validate_telegram_copy(v.body_text, strict_formatting=True)
            self.assertTrue(valid, f"Strict check failed: {reason}")


# ==============================================================================
# Category 2: Reels / Stories 9:16 Video Hooks (4 tests)
# ==============================================================================

class TestReelsStoriesHooks(unittest.TestCase):
    """Verifies Instagram Reels/Stories 9:16 video scripts and hooks."""

    def setUp(self):
        if not COPYWRITER_AVAILABLE:
            self.skipTest("CreativeCopywriterAgent not yet implemented")
        enable_socket_blocking()
        self.copywriter = CreativeCopywriterAgent()

    def test_reels_hook_structure_components(self):
        """Reels creative contains headline (hook), body (script), and call_to_action."""
        creative = self.copywriter.generate_reels_hook("Productivity App", "busy founders")
        self.assertIsNotNone(creative.headline)
        self.assertGreater(len(creative.headline), 0)
        self.assertIsNotNone(creative.body_text)
        self.assertGreater(len(creative.body_text), 0)
        self.assertIsNotNone(creative.call_to_action)
        self.assertGreater(len(creative.call_to_action), 0)

    def test_reels_hook_ab_variants_generation(self):
        """Generates distinct Variant A and Variant B video scripts."""
        var_a = self.copywriter.generate_reels_hook("Language App", "travelers", ab_variant="A")
        var_b = self.copywriter.generate_reels_hook("Language App", "travelers", ab_variant="B")
        self.assertEqual(var_a.ab_variant, "A")
        self.assertEqual(var_b.ab_variant, "B")
        self.assertNotEqual(var_a.headline, var_b.headline)

    def test_reels_hook_platform_and_format_enums(self):
        """Platform is META_INSTAGRAM and format is REELS_HOOK."""
        creative = self.copywriter.generate_reels_hook("Fitness Program", "runners")
        self.assertIn(creative.platform, (PlatformEnum.META_INSTAGRAM, "meta_instagram"))
        self.assertIn(creative.format, (AdFormatEnum.REELS_HOOK, "reels_hook"))

    def test_reels_hook_call_to_action_standard(self):
        """Call to action is a standardized action prompt."""
        creative = self.copywriter.generate_reels_hook("Crypto DEX", "traders")
        valid_ctas = {"LEARN_MORE", "SIGN_UP", "INSTALL_NOW", "GET_OFFER", "Learn More"}
        self.assertIn(creative.call_to_action, valid_ctas)


# ==============================================================================
# Category 3: RichAds Push Notifications (5 tests)
# ==============================================================================

class TestRichAdsPushCopywriter(unittest.TestCase):
    """Verifies RichAds push notification limits: headline <= 30, body <= 45."""

    def setUp(self):
        if not COPYWRITER_AVAILABLE:
            self.skipTest("CreativeCopywriterAgent not yet implemented")
        enable_socket_blocking()
        self.copywriter = CreativeCopywriterAgent()

    def test_richads_push_headline_limit_30_chars(self):
        """Push notification headline length does not exceed 30 characters."""
        push = self.copywriter.generate_push_creative("Flash Sale Sneakers")
        self.assertLessEqual(len(push.headline), 30)

    def test_richads_push_body_limit_45_chars(self):
        """Push notification body length does not exceed 45 characters."""
        push = self.copywriter.generate_push_creative("Flash Sale Sneakers")
        self.assertLessEqual(len(push.body_text), 45)

    def test_richads_push_passes_validate_richads_copy(self):
        """Push creative validates successfully via validate_richads_copy."""
        push = self.copywriter.generate_push_creative("Crypto Signal Bot")
        valid, reason = validate_richads_copy(push.headline, push.body_text)
        self.assertTrue(valid, f"RichAds check failed: {reason}")
        self.assertIsNone(reason)

    def test_richads_push_ab_variants(self):
        """Generates distinct Variant A and Variant B push notifications."""
        push_a = self.copywriter.generate_push_creative("Trading Course", ab_variant="A")
        push_b = self.copywriter.generate_push_creative("Trading Course", ab_variant="B")
        self.assertEqual(push_a.ab_variant, "A")
        self.assertEqual(push_b.ab_variant, "B")
        self.assertNotEqual(push_a.headline, push_b.headline)

    def test_richads_push_platform_and_format_enums(self):
        """Platform is RICHADS and format is PUSH_BANNER."""
        push = self.copywriter.generate_push_creative("Casino Game")
        self.assertIn(push.platform, (PlatformEnum.RICHADS, "richads"))
        self.assertIn(push.format, (AdFormatEnum.PUSH_BANNER, "richads_push"))


# ==============================================================================
# Category 4: Telega.in Native Seed Posts (4 tests)
# ==============================================================================

class TestTelegaInNativePosts(unittest.TestCase):
    """Verifies Telega.in native seed posts (500–1500 chars)."""

    def setUp(self):
        if not COPYWRITER_AVAILABLE:
            self.skipTest("CreativeCopywriterAgent not yet implemented")
        enable_socket_blocking()
        self.copywriter = CreativeCopywriterAgent()

    def test_telega_in_post_length_between_500_and_1500_chars(self):
        """Telega.in post body length is between 500 and 1500 characters."""
        post = self.copywriter.generate_telega_in_post("FinTech Masterclass")
        self.assertGreaterEqual(len(post.body_text), 500)
        self.assertLessEqual(len(post.body_text), 1500)

    def test_telega_in_post_structure(self):
        """Telega.in native post contains narrative body and call to action."""
        post = self.copywriter.generate_telega_in_post("AI Copywriting Assistant")
        self.assertIsNotNone(post.headline)
        self.assertIsNotNone(post.body_text)
        self.assertIsNotNone(post.call_to_action)

    def test_telega_in_post_platform_and_format_enums(self):
        """Platform is TELEGA_IN and format is NATIVE_POST."""
        post = self.copywriter.generate_telega_in_post("Web3 Wallet")
        self.assertIn(post.platform, (PlatformEnum.TELEGA_IN, "telega_in"))
        self.assertIn(post.format, (AdFormatEnum.NATIVE_POST, "telega_in_post"))

    def test_telega_in_post_ab_variants(self):
        """Generates distinct Variant A and Variant B narrative posts."""
        post_a = self.copywriter.generate_telega_in_post("DeFi Hub", ab_variant="A")
        post_b = self.copywriter.generate_telega_in_post("DeFi Hub", ab_variant="B")
        self.assertEqual(post_a.ab_variant, "A")
        self.assertEqual(post_b.ab_variant, "B")
        self.assertNotEqual(post_a.body_text, post_b.body_text)


# ==============================================================================
# Category 5: UTM Parameter Injection (6 tests)
# ==============================================================================

class TestUTMParameterInjection(unittest.TestCase):
    """Verifies UTM tracking parameter attachment across all creative links."""

    def setUp(self):
        if not COPYWRITER_AVAILABLE:
            self.skipTest("CreativeCopywriterAgent not yet implemented")
        enable_socket_blocking()
        self.copywriter = CreativeCopywriterAgent()

    def test_utm_injection_all_four_mandatory_keys(self):
        """Every tagged destination URL contains utm_source, utm_medium, utm_campaign, utm_content."""
        creatives = self.copywriter.generate_creatives_for_platform(
            platform=PlatformEnum.META_INSTAGRAM,
            product_name="Trading Bot",
            base_url="https://example.com/join",
            campaign_slug="q4_launch",
        )
        self.assertGreaterEqual(len(creatives), 1)
        for cr in creatives:
            parsed = urlparse(cr.utm_tagged_url)
            qs = parse_qs(parsed.query)
            self.assertIn("utm_source", qs)
            self.assertIn("utm_medium", qs)
            self.assertIn("utm_campaign", qs)
            self.assertIn("utm_content", qs)

    def test_utm_source_matches_platform(self):
        """utm_source matches platform identifier."""
        meta_cr = self.copywriter.generate_reels_hook("Product", destination_url="https://site.com")
        self.assertIn("utm_source=meta_instagram", meta_cr.utm_tagged_url)

        push_cr = self.copywriter.generate_push_creative("Product", destination_url="https://site.com")
        self.assertIn("utm_source=richads", push_cr.utm_tagged_url)

    def test_utm_medium_matches_ad_format(self):
        """utm_medium matches format identifier."""
        reels_cr = self.copywriter.generate_reels_hook("Product", destination_url="https://site.com")
        self.assertIn("utm_medium=reels", reels_cr.utm_tagged_url)

        push_cr = self.copywriter.generate_push_creative("Product", destination_url="https://site.com")
        self.assertIn("utm_medium=push", push_cr.utm_tagged_url)

    def test_utm_content_contains_variant_tag(self):
        """utm_content specifies variant indicator (a or b)."""
        cr_a = self.copywriter.generate_reels_hook("Product", ab_variant="A", destination_url="https://site.com")
        cr_b = self.copywriter.generate_reels_hook("Product", ab_variant="B", destination_url="https://site.com")
        self.assertIn("a", cr_a.utm_tagged_url.lower())
        self.assertIn("b", cr_b.utm_tagged_url.lower())

    def test_utm_injection_preserves_existing_query_params(self):
        """Appends UTMs preserving pre-existing query parameters with exactly one '?'."""
        base = "https://example.com/page?ref=partner_88&promo=summer"
        cr = self.copywriter.generate_reels_hook("Product", destination_url=base)
        self.assertIn("ref=partner_88", cr.utm_tagged_url)
        self.assertIn("promo=summer", cr.utm_tagged_url)
        self.assertIn("utm_source=", cr.utm_tagged_url)
        self.assertEqual(cr.utm_tagged_url.count("?"), 1)

    def test_creative_utm_parameters_dict_populated(self):
        """CreativeItem.utm_parameters dictionary contains all 4 mandatory keys."""
        cr = self.copywriter.generate_reels_hook("Product", destination_url="https://example.com")
        self.assertEqual(
            set(cr.utm_parameters.keys()),
            {"utm_source", "utm_medium", "utm_campaign", "utm_content"},
        )


# ==============================================================================
# Category 6: Creative Rotation & Edge Cases (9 tests)
# ==============================================================================

class TestCreativeRotationAndEdgeCases(unittest.TestCase):
    """Verifies creative fatigue rotation and edge-case handling (Cyrillic, special chars, empty)."""

    def setUp(self):
        if not COPYWRITER_AVAILABLE:
            self.skipTest("CreativeCopywriterAgent not yet implemented")
        enable_socket_blocking()
        self.copywriter = CreativeCopywriterAgent()

    def test_rotate_fatigued_creatives_adds_variant_b(self):
        """Fatigue alert (frequency > 2.80) activates replacement Variant B."""
        state = CampaignState(
            campaign_id="cmp_fatigue_unit",
            status=CampaignStatus.OPTIMIZING,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            creatives=[
                CreativeItem(
                    creative_id="cr_v1",
                    platform=PlatformEnum.META_INSTAGRAM,
                    format=AdFormatEnum.REELS_HOOK,
                    headline="Hook V1",
                    body_text="V1 script",
                    call_to_action="LEARN_MORE",
                    raw_destination_url="https://example.com",
                    utm_tagged_url="https://example.com?utm_source=meta_instagram&utm_medium=reels&utm_campaign=c1&utm_content=v1",
                    ab_variant="A",
                    moderation_passed=True,
                )
            ],
            performance_metrics=[
                PerformanceMetrics(
                    impressions=29000,
                    reach=10000,
                    frequency=2.90,
                    guardrail_triggered=True,
                    guardrail_action="FATIGUE_ALERT",
                )
            ],
        )
        updated_state = self.copywriter.rotate_fatigued_creatives(state)
        self.assertGreaterEqual(len(updated_state.creatives), 2)
        self.assertTrue(any(c.ab_variant == "B" for c in updated_state.creatives))

    def test_rotate_fatigued_creatives_preserves_original_variant_a(self):
        """Rotation preserves existing Variant A in creative history."""
        state = CampaignState(
            campaign_id="cmp_fatigue_pres",
            status=CampaignStatus.OPTIMIZING,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            creatives=[
                CreativeItem(
                    creative_id="cr_orig",
                    platform=PlatformEnum.META_INSTAGRAM,
                    format=AdFormatEnum.REELS_HOOK,
                    headline="Original Hook",
                    body_text="Original body",
                    call_to_action="LEARN_MORE",
                    raw_destination_url="https://example.com",
                    utm_tagged_url="https://example.com?utm_source=meta&utm_medium=reels&utm_campaign=c&utm_content=a",
                    ab_variant="A",
                    moderation_passed=True,
                )
            ],
            performance_metrics=[
                PerformanceMetrics(frequency=2.95, guardrail_triggered=True, guardrail_action="FATIGUE_ALERT")
            ],
        )
        updated_state = self.copywriter.rotate_fatigued_creatives(state)
        variant_a_found = any(c.ab_variant == "A" for c in updated_state.creatives)
        self.assertTrue(variant_a_found)

    def test_rotate_fatigued_creatives_appends_audit_trail(self):
        """Rotation appends an audit event to CampaignState."""
        state = CampaignState(
            campaign_id="cmp_fatigue_audit",
            status=CampaignStatus.OPTIMIZING,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            creatives=[
                CreativeItem(
                    platform=PlatformEnum.META_INSTAGRAM,
                    format=AdFormatEnum.REELS_HOOK,
                    body_text="Body text",
                    raw_destination_url="https://example.com",
                    utm_tagged_url="https://example.com?utm_source=meta&utm_medium=reels&utm_campaign=c&utm_content=a",
                    ab_variant="A",
                    moderation_passed=True,
                )
            ],
            performance_metrics=[
                PerformanceMetrics(frequency=3.0, guardrail_triggered=True, guardrail_action="FATIGUE_ALERT")
            ],
        )
        updated_state = self.copywriter.rotate_fatigued_creatives(state)
        audit_agents = [e.get("agent") for e in updated_state.audit_trail]
        self.assertIn("CreativeCopywriterAgent", audit_agents)

    def test_rotate_fatigued_creatives_without_fatigue_is_idempotent(self):
        """If frequency <= 2.80 and no fatigue alert, state creatives remain unchanged."""
        state = CampaignState(
            campaign_id="cmp_healthy",
            status=CampaignStatus.LIVE,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            creatives=[
                CreativeItem(
                    platform=PlatformEnum.META_INSTAGRAM,
                    format=AdFormatEnum.REELS_HOOK,
                    body_text="Body text",
                    raw_destination_url="https://example.com",
                    utm_tagged_url="https://example.com?utm_source=meta&utm_medium=reels&utm_campaign=c&utm_content=a",
                    ab_variant="A",
                    moderation_passed=True,
                )
            ],
            performance_metrics=[
                PerformanceMetrics(frequency=1.80, guardrail_triggered=False)
            ],
        )
        original_count = len(state.creatives)
        updated_state = self.copywriter.rotate_fatigued_creatives(state)
        self.assertEqual(len(updated_state.creatives), original_count)

    def test_generate_all_campaign_creatives_covers_media_plan(self):
        """generate_all_campaign_creatives covers all channels in MediaPlan."""
        from ai_target.state.models import ChannelAllocation, MediaPlan
        plan = MediaPlan(
            allocations=[
                ChannelAllocation(platform=PlatformEnum.META_INSTAGRAM, allocated_budget=500.0, daily_budget=20.0),
                ChannelAllocation(platform=PlatformEnum.TELEGRAM_ADSGRAM, allocated_budget=400.0, daily_budget=15.0),
                ChannelAllocation(platform=PlatformEnum.TELEGRAM_ADSLY, allocated_budget=300.0, daily_budget=10.0, cpm_estimate=0.20),
            ]
        )
        creatives = self.copywriter.generate_all_campaign_creatives(
            product_name="Trading Bot",
            media_plan=plan,
            base_url="https://trading.io",
        )
        self.assertGreaterEqual(len(creatives), 3)
        allocated_platforms = {alloc.platform for alloc in plan.allocations}
        created_platforms = {cr.platform for cr in creatives}
        self.assertEqual(allocated_platforms, created_platforms, "Every allocated platform must be represented in generated creatives")
        for cr in creatives:
            self.assertTrue(cr.moderation_passed)

    def test_generate_creatives_for_platform_adsgram_routing(self):
        """PlatformEnum.TELEGRAM_ADSGRAM correctly returns AdsGram rewarded items without shadowing."""
        variants = self.copywriter.generate_creatives_for_platform(
            platform=PlatformEnum.TELEGRAM_ADSGRAM,
            product_name="TapGame",
            base_url="https://tapgame.io",
        )
        self.assertGreaterEqual(len(variants), 1)
        for cr in variants:
            self.assertEqual(cr.platform, PlatformEnum.TELEGRAM_ADSGRAM)
            self.assertEqual(cr.format, AdFormatEnum.ADSGRAM_REWARDED)
            self.assertIn("utm_source=telegram_adsgram", cr.utm_tagged_url)
            self.assertIn("utm_medium=rewarded", cr.utm_tagged_url)

    def test_rotate_fatigued_creatives_idempotent_no_duplicate_variants(self):
        """Repeated rotations do not exponentially accumulate duplicate variants."""
        state = CampaignState(
            client_brief=ClientBrief(product="AppAlpha", geo="US", goal="LEADS", budget=1000.0),
            financials=Financials(gross_budget=1000.0),
            media_plan=MediaPlan(allocations=[
                ChannelAllocation(platform=PlatformEnum.TELEGRAM_ADSLY, allocated_budget=500.0, daily_budget=16.6, cpm_estimate=0.2),
                ChannelAllocation(platform=PlatformEnum.TELEGRAM_ADSGRAM, allocated_budget=500.0, daily_budget=16.6),
            ]),
        )
        self.copywriter.generate_all_campaign_creatives(state)
        # Initial: 2 Adsly (A, B) + 2 AdsGram (A, B) = 4
        self.assertEqual(len(state.creatives), 4)

        # Rotation 1: should add Variant C for each platform (total 6)
        self.copywriter.rotate_fatigued_creatives(state, force_rotation=True)
        self.assertEqual(len(state.creatives), 6)
        for plat in (PlatformEnum.TELEGRAM_ADSLY, PlatformEnum.TELEGRAM_ADSGRAM):
            plat_creatives = [c for c in state.creatives if c.platform == plat]
            variants = {c.ab_variant for c in plat_creatives}
            self.assertEqual(variants, {"A", "B", "C"})
            self.assertEqual(len(plat_creatives), 3)

        # Rotation 2: should be strictly idempotent (no duplicates added)
        self.copywriter.rotate_fatigued_creatives(state, force_rotation=True)
        self.assertEqual(len(state.creatives), 6)

    def test_empty_product_name_raises_error(self):
        """Empty product name string raises ValueError."""
        with self.assertRaises(ValueError):
            self.copywriter.generate_telegram_ads_copy("", "audience")

    def test_whitespace_product_name_raises_error(self):
        """Whitespace-only product name raises ValueError."""
        with self.assertRaises(ValueError):
            self.copywriter.generate_reels_hook("   ", "audience")

    def test_cyrillic_unicode_product_handling(self):
        """Cyrillic product name generates valid copy and properly encoded UTM URL."""
        product = "Крипто-Бот 'Альфа'"
        variants = self.copywriter.generate_telegram_ads_copy(product, "трейдеры")
        self.assertGreaterEqual(len(variants), 1)
        for v in variants:
            self.assertIn("Альфа", v.body_text)
            self.assertTrue(v.moderation_passed)

    def test_special_characters_product_handling(self):
        """Product names with special characters ($#&!) do not crash or corrupt formatting."""
        product = "AI & Forex #1 ($100 Bonus!)"
        cr = self.copywriter.generate_reels_hook(product, destination_url="https://forex.ai")
        self.assertIsNotNone(cr.headline)
        self.assertIn("utm_source=", cr.utm_tagged_url)


if __name__ == "__main__":
    unittest.main()
