"""
Milestone 2 Iteration 2 Adversarial Stress Verification Test Suite.
File: tests/unit/test_adversarial_copywriter_iter2.py
Location: C:\\Users\\firda\\ии таргет\\tests\\unit\\test_adversarial_copywriter_iter2.py

Challenger subagent: challenger_m2_iter2_1
Parent Orchestrator: 617a01f9-65c1-4b93-a377-31018f3d06b1

Target:
- src/ai_target/agents/copywriter.py (CreativeCopywriterAgent)
- src/ai_target/state/models.py (CampaignState, Creatives, CreativeItem)

Empirical Objectives:
1. Verify generate_creatives_for_platform(PlatformEnum.TELEGRAM_ADSGRAM) strictly returns
   PlatformEnum.TELEGRAM_ADSGRAM and AdFormatEnum.ADSGRAM_REWARDED without substring shadowing.
2. Run 5 consecutive cycles of rotate_fatigued_creatives(state, force_rotation=True) across
   multi-channel media plans (Meta, AdsGram, Adsly, TikTok, Google Ads).
3. Invariant check: Verify that duplicate variant items are NEVER accumulated, and set of
   (platform, ab_variant) is strictly unique across all channels and cycles.
4. Stress test boundary conditions: asymmetrical initial sets, list vs Creatives container,
   telemetry-driven fatigue triggering, and creative moderation integrity.
"""

import unittest
from typing import List, Set, Tuple
from urllib.parse import parse_qs, urlparse

from tests.conftest import enable_socket_blocking

enable_socket_blocking()

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
    validate_richads_copy,
    validate_telegram_copy,
)


class TestAdsGramDispatchDirectVerification(unittest.TestCase):
    """
    Adversarial verification of AdsGram dispatch logic:
    Verifies generate_creatives_for_platform(PlatformEnum.TELEGRAM_ADSGRAM) returns
    PlatformEnum.TELEGRAM_ADSGRAM and format AdFormatEnum.ADSGRAM_REWARDED without substring shadowing.
    """

    def setUp(self):
        enable_socket_blocking()
        self.agent = CreativeCopywriterAgent()

    def test_adsgram_dispatch_with_enum(self):
        """Passing PlatformEnum.TELEGRAM_ADSGRAM returns AdsGram platform and ADSGRAM_REWARDED format."""
        variants = self.agent.generate_creatives_for_platform(
            platform=PlatformEnum.TELEGRAM_ADSGRAM,
            product="TonBattleGame",
            base_url="https://tonbattle.io",
            count=3,
        )
        self.assertEqual(len(variants), 3)
        for v in variants:
            self.assertEqual(
                v.platform,
                PlatformEnum.TELEGRAM_ADSGRAM,
                f"Expected PlatformEnum.TELEGRAM_ADSGRAM, got {v.platform}",
            )
            self.assertEqual(
                v.format,
                AdFormatEnum.ADSGRAM_REWARDED,
                f"Expected AdFormatEnum.ADSGRAM_REWARDED, got {v.format}",
            )
            self.assertTrue(v.moderation_passed)
            self.assertLessEqual(len(v.body_text), 160)
            self.assertIn("utm_source=telegram_adsgram", v.utm_tagged_url)
            self.assertIn("utm_medium=rewarded", v.utm_tagged_url)

    def test_adsgram_dispatch_with_string_variants(self):
        """String inputs ('telegram_adsgram', 'TELEGRAM_ADSGRAM', 'adsgram', 'AdsGram') route to AdsGram."""
        string_inputs = [
            "telegram_adsgram",
            "TELEGRAM_ADSGRAM",
            "adsgram",
            "AdsGram",
            "Telegram_AdsGram",
        ]
        for plat_input in string_inputs:
            variants = self.agent.generate_creatives_for_platform(
                platform=plat_input,
                product="HamsterTap",
                base_url="https://hamstertap.xyz",
                count=2,
            )
            self.assertEqual(len(variants), 2, f"Failed for input {plat_input}")
            for v in variants:
                self.assertEqual(
                    v.platform,
                    PlatformEnum.TELEGRAM_ADSGRAM,
                    f"String {plat_input} failed to map to PlatformEnum.TELEGRAM_ADSGRAM",
                )
                self.assertEqual(
                    v.format,
                    AdFormatEnum.ADSGRAM_REWARDED,
                    f"String {plat_input} failed to map to AdFormatEnum.ADSGRAM_REWARDED",
                )
                self.assertIn("utm_source=telegram_adsgram", v.utm_tagged_url)

    def test_adsgram_no_substring_shadowing_by_telegram_ads(self):
        """
        Anti-Shadowing Invariant: 'telegram_adsgram' contains 'telegram_ads', but must NEVER
        be intercepted by the Telegram Ads / Adsly text dispatcher.
        """
        variants = self.agent.generate_creatives_for_platform(
            platform=PlatformEnum.TELEGRAM_ADSGRAM,
            product="CryptoQuest",
            count=2,
        )
        for v in variants:
            # Must NOT be TELEGRAM_ADS_TEXT
            self.assertNotEqual(
                v.format,
                AdFormatEnum.TELEGRAM_ADS_TEXT,
                "Shadowing defect: AdsGram was intercepted by telegram_ads_text dispatcher!",
            )
            self.assertNotEqual(
                v.platform,
                PlatformEnum.TELEGRAM_ADSLY,
                "Shadowing defect: AdsGram platform was routed to telegram_adsly!",
            )
            self.assertEqual(v.platform, PlatformEnum.TELEGRAM_ADSGRAM)
            self.assertEqual(v.format, AdFormatEnum.ADSGRAM_REWARDED)

    def test_adsgram_variant_differentiation_a_b_c(self):
        """AdsGram produces distinct copy variants for A, B, and C."""
        variants = self.agent.generate_creatives_for_platform(
            platform=PlatformEnum.TELEGRAM_ADSGRAM,
            product="MiniAppEmpire",
            count=3,
        )
        self.assertEqual(len(variants), 3)
        var_labels = [v.ab_variant for v in variants]
        self.assertEqual(var_labels, ["A", "B", "C"])

        # All body texts must be mutually distinct
        bodies = [v.body_text for v in variants]
        self.assertEqual(len(bodies), len(set(bodies)), "AdsGram A/B/C variants have duplicate body text")

        # All UTM content tags must match variant
        for v in variants:
            expected_content = f"banner_{v.ab_variant.lower()}"
            self.assertIn(f"utm_content={expected_content}", v.utm_tagged_url)
            self.assertEqual(v.utm_parameters.get("utm_content"), expected_content)


class TestMultiChannel5ConsecutiveRotationCycles(unittest.TestCase):
    """
    Empirical stress testing of fatigue rotation deduplication across 5 consecutive cycles.
    Targets multi-channel media plans containing Meta, AdsGram, Adsly, TikTok, and Google Ads.
    """

    def setUp(self):
        enable_socket_blocking()
        self.agent = CreativeCopywriterAgent()

    def _create_5_channel_state(self) -> CampaignState:
        """Helper to create a standard 5-channel CampaignState."""
        return CampaignState(
            campaign_id="cmp_stress_5ch",
            status=CampaignStatus.LIVE,
            client_brief=ClientBrief(
                product="FinTechMaster",
                geo="US, UK, DE",
                goal="LEADS",
                budget=5000.0,
            ),
            financials=Financials(gross_budget=5000.0, payment_verified=True),
            media_plan=MediaPlan(
                allocations=[
                    ChannelAllocation(platform=PlatformEnum.META_INSTAGRAM, allocated_budget=1000.0, daily_budget=33.3),
                    ChannelAllocation(platform=PlatformEnum.TELEGRAM_ADSGRAM, allocated_budget=1000.0, daily_budget=33.3),
                    ChannelAllocation(platform=PlatformEnum.TELEGRAM_ADSLY, allocated_budget=1000.0, daily_budget=33.3, cpm_estimate=0.25),
                    ChannelAllocation(platform=PlatformEnum.TIKTOK, allocated_budget=1000.0, daily_budget=33.3),
                    ChannelAllocation(platform=PlatformEnum.GOOGLE_ADS, allocated_budget=1000.0, daily_budget=33.3),
                ]
            ),
        )

    def test_5_consecutive_cycles_across_5_channel_media_plan(self):
        """
        Primary Challenger Objective:
        1. Initialize state with 5 channels (Meta, AdsGram, Adsly, TikTok, Google Ads).
        2. Generate initial creatives -> 5 channels x 2 variants (A, B) = 10 items.
        3. Run Cycle 1 of rotate_fatigued_creatives(state, force_rotation=True) -> adds Variant C (total 15).
        4. Run Cycles 2, 3, 4, 5 consecutively.
        5. Invariant: Duplicate variant items are NEVER accumulated, and set of (platform, ab_variant)
           is strictly unique at every single cycle. Count remains exactly 15 from cycle 1 to 5.
        """
        state = self._create_5_channel_state()
        self.agent.generate_all_campaign_creatives(state)

        # Step 0: Verify initial generation
        self.assertEqual(len(state.creatives), 10, "Initial generation must produce 10 items (5 channels x 2)")
        initial_keys = [(c.platform, c.ab_variant) for c in state.creatives]
        self.assertEqual(len(initial_keys), len(set(initial_keys)), "Initial creatives contained duplicate keys")
        for plat in [
            PlatformEnum.META_INSTAGRAM,
            PlatformEnum.TELEGRAM_ADSGRAM,
            PlatformEnum.TELEGRAM_ADSLY,
            PlatformEnum.TIKTOK,
            PlatformEnum.GOOGLE_ADS,
        ]:
            plat_variants = {c.ab_variant for c in state.creatives if c.platform == plat}
            self.assertEqual(plat_variants, {"A", "B"}, f"Platform {plat} missing initial A or B")

        # Consecutive Cycles 1 to 5
        cycle_counts = []
        for cycle_idx in range(1, 6):
            self.agent.rotate_fatigued_creatives(state, force_rotation=True)
            current_count = len(state.creatives)
            cycle_counts.append(current_count)

            # Extract (platform, ab_variant) keys
            keys = [(c.platform, c.ab_variant) for c in state.creatives]
            unique_keys = set(keys)

            # Invariant 1: Total items must equal unique (platform, ab_variant) pairs
            self.assertEqual(
                len(keys),
                len(unique_keys),
                f"Cycle {cycle_idx} VIOLATION: Duplicate (platform, ab_variant) pairs detected! "
                f"Total items: {len(keys)}, Unique keys: {len(unique_keys)}",
            )

            # Invariant 2: Creative IDs must be unique
            creative_ids = [c.creative_id for c in state.creatives]
            self.assertEqual(
                len(creative_ids),
                len(set(creative_ids)),
                f"Cycle {cycle_idx} VIOLATION: Duplicate creative_ids detected!",
            )

            # Invariant 3: Cycle 1 must reach 15 (adds Variant C for all 5 platforms)
            if cycle_idx == 1:
                self.assertEqual(
                    current_count,
                    15,
                    f"Cycle 1 expected 15 items (5 channels x 3 variants A/B/C), got {current_count}",
                )
                for plat in [
                    PlatformEnum.META_INSTAGRAM,
                    PlatformEnum.TELEGRAM_ADSGRAM,
                    PlatformEnum.TELEGRAM_ADSLY,
                    PlatformEnum.TIKTOK,
                    PlatformEnum.GOOGLE_ADS,
                ]:
                    plat_vars = sorted([c.ab_variant for c in state.creatives if c.platform == plat])
                    self.assertEqual(
                        plat_vars,
                        ["A", "B", "C"],
                        f"Platform {plat} does not have exactly ['A', 'B', 'C'] after Cycle 1",
                    )

            # Invariant 4: Cycles 2 through 5 must remain strictly idempotent at 15 items
            if cycle_idx > 1:
                self.assertEqual(
                    current_count,
                    15,
                    f"Cycle {cycle_idx} VIOLATION: Duplicate variants accumulated! "
                    f"Expected 15, got {current_count}",
                )

        # Audit trail must document each cycle
        rotation_events = [e for e in state.audit_trail if e.get("action") == "ROTATE_FATIGUED_CREATIVES"]
        self.assertEqual(len(rotation_events), 5, "Audit trail must record exactly 5 rotation events")
        # In cycle 1, 5 variants were added
        self.assertEqual(len(rotation_events[0]["details"]["added_variants"]), 5)
        # In cycles 2 to 5, 0 variants were added (idempotent)
        for r_event in rotation_events[1:]:
            self.assertEqual(len(r_event["details"]["added_variants"]), 0)

    def test_7_channel_full_portfolio_5_consecutive_cycles(self):
        """
        Stress test across all 7 platform formats:
        Meta, AdsGram, Adsly, TikTok, Google Ads, RichAds, Telega.in.
        Initial: 7 x 2 = 14 items.
        Cycle 1: 7 x 3 = 21 items.
        Cycles 2..5: strictly 21 items, 0 duplicates.
        """
        all_platforms = [
            PlatformEnum.META_INSTAGRAM,
            PlatformEnum.TELEGRAM_ADSGRAM,
            PlatformEnum.TELEGRAM_ADSLY,
            PlatformEnum.TIKTOK,
            PlatformEnum.GOOGLE_ADS,
            PlatformEnum.RICHADS,
            PlatformEnum.TELEGA_IN,
        ]
        state = CampaignState(
            campaign_id="cmp_stress_7ch",
            status=CampaignStatus.LIVE,
            client_brief=ClientBrief(product="GlobalSaaS", geo="Global", goal="SALES", budget=7000.0),
            financials=Financials(gross_budget=7000.0, payment_verified=True),
            media_plan=MediaPlan(
                allocations=[
                    ChannelAllocation(platform=p, allocated_budget=1000.0, daily_budget=33.3, cpm_estimate=0.20)
                    for p in all_platforms
                ]
            ),
        )
        self.agent.generate_all_campaign_creatives(state)
        self.assertEqual(len(state.creatives), 14)

        for cycle_idx in range(1, 6):
            self.agent.rotate_fatigued_creatives(state, force_rotation=True)
            self.assertEqual(
                len(state.creatives),
                21,
                f"7-channel portfolio failed at cycle {cycle_idx}: expected 21, got {len(state.creatives)}",
            )
            keys = [(c.platform, c.ab_variant) for c in state.creatives]
            self.assertEqual(
                len(keys),
                len(set(keys)),
                f"7-channel portfolio duplicate detected at cycle {cycle_idx}",
            )

    def test_single_variant_initial_state_5_cycles(self):
        """
        Adversarial Boundary: Initial state contains ONLY Variant A for each channel.
        Cycle 1: adds Variant B (total 10).
        Cycle 2: adds Variant C (total 15).
        Cycles 3, 4, 5: strictly idempotent at 15 items.
        """
        state = self._create_5_channel_state()
        # Manually populate only Variant A for each of the 5 channels
        items_a = []
        for plat in [
            PlatformEnum.META_INSTAGRAM,
            PlatformEnum.TELEGRAM_ADSGRAM,
            PlatformEnum.TELEGRAM_ADSLY,
            PlatformEnum.TIKTOK,
            PlatformEnum.GOOGLE_ADS,
        ]:
            cr = self.agent.generate_creatives_for_platform(plat, product="Alpha", count=1)[0]
            cr.ab_variant = "A"
            items_a.append(cr)

        state.creatives = Creatives(items=items_a)
        self.assertEqual(len(state.creatives), 5)

        # Cycle 1: should add Variant B
        self.agent.rotate_fatigued_creatives(state, force_rotation=True)
        self.assertEqual(len(state.creatives), 10)
        keys_c1 = [(c.platform, c.ab_variant) for c in state.creatives]
        self.assertEqual(len(keys_c1), len(set(keys_c1)))

        # Cycle 2: should add Variant C
        self.agent.rotate_fatigued_creatives(state, force_rotation=True)
        self.assertEqual(len(state.creatives), 15)
        keys_c2 = [(c.platform, c.ab_variant) for c in state.creatives]
        self.assertEqual(len(keys_c2), len(set(keys_c2)))

        # Cycles 3, 4, 5: idempotent
        for cycle_idx in (3, 4, 5):
            self.agent.rotate_fatigued_creatives(state, force_rotation=True)
            self.assertEqual(len(state.creatives), 15, f"Failed at cycle {cycle_idx}")
            keys_cx = [(c.platform, c.ab_variant) for c in state.creatives]
            self.assertEqual(len(keys_cx), len(set(keys_cx)))

    def test_asymmetrical_initial_variant_mix_5_cycles(self):
        """
        Adversarial Edge Case: Channel 1 has [A], Channel 2 has [A, B], Channel 3 has [A, B, C],
        Channel 4 has [B], Channel 5 has [C].
        Verify rotate_fatigued_creatives does not duplicate variants, correctly fills gaps,
        and stabilizes at strictly unique (platform, ab_variant) pairs.
        """
        state = self._create_5_channel_state()

        # Build asymmetrical list
        asym_items = []
        # Ch 1 (Meta): A
        asym_items.append(self.agent.generate_reels_hook("Product", ab_variant="A"))
        # Ch 2 (AdsGram): A, B
        ag_vars = self.agent.generate_creatives_for_platform(PlatformEnum.TELEGRAM_ADSGRAM, product="Product", count=2)
        asym_items.extend(ag_vars)
        # Ch 3 (Adsly): A, B, C
        tg_vars = self.agent.generate_telegram_ads_copy("Product", count=3)
        asym_items.extend(tg_vars)
        # Ch 4 (TikTok): B
        asym_items.append(
            CreativeItem(
                platform=PlatformEnum.TIKTOK,
                format=AdFormatEnum.REELS_HOOK,
                headline="Hook B",
                body_text="Body B",
                call_to_action="LEARN_MORE",
                raw_destination_url="https://example.com",
                utm_tagged_url="https://example.com?utm_source=tiktok&utm_medium=video&utm_campaign=c&utm_content=b",
                ab_variant="B",
                moderation_passed=True,
            )
        )
        # Ch 5 (Google Ads): C
        asym_items.append(
            CreativeItem(
                platform=PlatformEnum.GOOGLE_ADS,
                format=AdFormatEnum.STORIES,
                headline="Google C",
                body_text="Google Body C",
                call_to_action="LEARN_MORE",
                raw_destination_url="https://example.com",
                utm_tagged_url="https://example.com?utm_source=google_ads&utm_medium=search&utm_campaign=c&utm_content=c",
                ab_variant="C",
                moderation_passed=True,
            )
        )

        state.creatives = Creatives(items=asym_items)
        initial_len = len(state.creatives)

        # Run 5 cycles
        for cycle_idx in range(1, 6):
            self.agent.rotate_fatigued_creatives(state, force_rotation=True)
            keys = [(c.platform, c.ab_variant) for c in state.creatives]
            self.assertEqual(
                len(keys),
                len(set(keys)),
                f"Asymmetrical mix produced duplicates in cycle {cycle_idx}: {keys}",
            )

        # After stabilization, no platform should have more than 3 variants
        for plat in [
            PlatformEnum.META_INSTAGRAM,
            PlatformEnum.TELEGRAM_ADSGRAM,
            PlatformEnum.TELEGRAM_ADSLY,
            PlatformEnum.TIKTOK,
            PlatformEnum.GOOGLE_ADS,
        ]:
            plat_vars = [c.ab_variant for c in state.creatives if c.platform == plat]
            self.assertEqual(len(plat_vars), len(set(plat_vars)), f"Duplicates in platform {plat}")
            self.assertLessEqual(len(plat_vars), 3)

    def test_creatives_container_plain_list_support(self):
        """
        Container Polymorphism: state.creatives may be initialized as a plain list
        instead of Creatives Pydantic container.
        Verify 5 rotation cycles succeed without AttributeError and maintain deduplication.
        """
        state = self._create_5_channel_state()
        self.agent.generate_all_campaign_creatives(state)
        # Convert state.creatives explicitly to plain python list
        state.creatives = list(state.creatives)
        self.assertIsInstance(state.creatives, list)

        for cycle_idx in range(1, 6):
            self.agent.rotate_fatigued_creatives(state, force_rotation=True)
            keys = [(c.platform, c.ab_variant) for c in state.creatives]
            self.assertEqual(len(keys), len(set(keys)), f"Duplicate keys with list container at cycle {cycle_idx}")

        self.assertEqual(len(state.creatives), 15)

    def test_telemetry_driven_fatigue_rotation_idempotent(self):
        """
        Telemetry-Driven Rotation: frequency=3.10 triggers fatigue rotation without force_rotation=True.
        Subsequent cycles with persisting frequency=3.10 remain strictly idempotent (0 duplicates added).
        """
        state = self._create_5_channel_state()
        self.agent.generate_all_campaign_creatives(state)
        self.assertEqual(len(state.creatives), 10)

        # Ingest fatigue telemetry (frequency 3.10 > 2.80 threshold)
        state.performance_metrics.append(
            PerformanceMetrics(
                platform=PlatformEnum.META_INSTAGRAM,
                impressions=31000,
                reach=10000,
                frequency=3.10,
                guardrail_triggered=True,
                guardrail_action="FATIGUE_ALERT",
            )
        )

        # Cycle 1: Triggered via telemetry
        self.agent.rotate_fatigued_creatives(state)
        self.assertEqual(len(state.creatives), 15)

        # Cycles 2..5: Same telemetry persists, must NOT add duplicates
        for cycle_idx in range(2, 6):
            self.agent.rotate_fatigued_creatives(state)
            self.assertEqual(
                len(state.creatives),
                15,
                f"Telemetry fatigue rotation illegally added duplicates in cycle {cycle_idx}",
            )
            keys = [(c.platform, c.ab_variant) for c in state.creatives]
            self.assertEqual(len(keys), len(set(keys)))

    def test_creative_integrity_post_5_rotations(self):
        """
        Moderation & Compliance Post-Rotation Verification:
        Every single creative present after 5 rotation cycles must:
        1. Have moderation_passed == True and moderation_flags == []
        2. Have complete 4-key UTM parameters
        3. Have body_text conforming to platform moderation (Telegram <= 160, RichAds <= 45)
        """
        state = self._create_5_channel_state()
        self.agent.generate_all_campaign_creatives(state)
        for _ in range(5):
            self.agent.rotate_fatigued_creatives(state, force_rotation=True)

        self.assertEqual(len(state.creatives), 15)

        for c in state.creatives:
            self.assertTrue(c.moderation_passed, f"Creative {c.creative_id} failed moderation: {c.moderation_flags}")
            self.assertEqual(len(c.moderation_flags), 0)

            # UTM dictionary completeness
            for utm_key in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
                self.assertIn(utm_key, c.utm_parameters)
                self.assertIn(f"{utm_key}=", c.utm_tagged_url)

            # Platform character bounds
            if c.platform in (PlatformEnum.TELEGRAM_ADSLY, PlatformEnum.TELEGRAM_ADSGRAM):
                self.assertLessEqual(len(c.body_text), 160)
                valid, reason = validate_telegram_copy(c.body_text, strict_formatting=True)
                self.assertTrue(valid, f"Telegram copy invalid: {reason} | {c.body_text}")


if __name__ == "__main__":
    unittest.main()
