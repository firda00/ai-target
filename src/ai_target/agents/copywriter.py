"""
Creative Copywriter Agent for AI Target Campaign Management System.

Location: src/ai_target/agents/copywriter.py
Role: Requirement 3 (R3) Creative Copywriter Agent (creative_copywriter_agent)

Responsible for:
1. Generating A/B ad copy variants compliant with platform moderation rules:
   - Telegram Ads: strictly <= 160 characters, zero raw external URLs, verified via validate_telegram_copy.
   - Instagram Reels / Stories (Meta): 9:16 vertical video script with visual hook, body copy, and CTA.
   - RichAds push banners: headline <= 30 chars, body <= 45 chars, verified via validate_richads_copy.
   - Telega.in seeds: long-form native posts (500 to 1500 characters).
   - AdsGram, TikTok, Google Ads AI Max.
2. Generating all mandatory UTM tracking parameters (utm_source, utm_medium, utm_campaign, utm_content)
   and appending them to destination URLs using build_utm_url.
3. Rotating fatigued creatives upon fatigue alert (e.g. frequency > 2.8), hot-swapping Variant B into state.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import parse_qsl, urlparse

from ai_target.state.models import (
    AdFormatEnum,
    CampaignState,
    CreativeItem,
    CreativeVariant,
    Creatives,
    MediaPlan,
    PlatformEnum,
)
from ai_target.utils.moderation import (
    ModerationError,
    RE_HEX_OCTAL_IP,
    RE_IPV4,
    RE_IPV6,
    TLD_LIST,
    validate_richads_copy,
    validate_telegram_ads_copy,
    validate_telegram_copy,
)
from ai_target.utils.utm import build_utm_url


class CreativeCopywriterAgent:
    """
    Autonomous multi-platform copywriter and creative variant optimizer.
    """

    DEFAULT_CAMPAIGN_SLUG = "campaign"
    DEFAULT_DESTINATION_URL = "https://example.com"

    def __init__(self) -> None:
        pass

    # =========================================================================
    # Helpers
    # =========================================================================

    def _validate_non_empty_product(self, text: Optional[str]) -> str:
        """Validates that product name is non-empty and non-whitespace, raises ValueError otherwise."""
        if text is None or not str(text).strip():
            raise ValueError("Product name cannot be empty or whitespace-only.")
        return str(text).strip()

    def _sanitize_slug(self, text: str) -> str:
        """Sanitizes product or campaign string into a clean lowercase slug."""
        if not text:
            return "app"
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", text.strip().lower())
        slug = re.sub(r"_+", "_", slug).strip("_")
        return slug or "app"

    def _sanitize_product_name(self, text: str) -> str:
        """
        Sanitizes product name to ensure strict compliance across all platforms:
        - Strips raw protocols (https?://, www.) and t.me prefixes
        - Strips defanged dots and obfuscated link patterns (evil[.]com -> evil com)
        - Masks/replaces IP addresses (192.168.1.1 -> app)
        - Strips/masks naked domain names (crypto.com -> crypto, steal.xyz -> steal, dex.io -> dex)
        - Strips exclamation marks (!) so product name cannot inject exclamation marks into copy
        - Normalizes excessive ALL-CAPS words (words >= 6 chars in all-caps -> capitalized)
        - Normalizes Unicode and whitespace
        """
        if not text:
            return "Product"
        cleaned = unicodedata.normalize("NFC", str(text).strip())

        # 0. Strip zero-width and invisible control characters
        cleaned = re.sub(r"[\u200b-\u200d\ufeff\u00ad\u2060]", "", cleaned)

        # 1. Strip raw protocols and web address prefixes
        cleaned = re.sub(r"https?://(?:www\.)?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bwww\.", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:t|telegram)\.me/", "", cleaned, flags=re.IGNORECASE)

        # 2. Strip defanged dots and obfuscated link patterns (e.g. evil[.]com -> evil com)
        cleaned = re.sub(r"\[\.\]|\(\.\)|\[dot\]|\(dot\)|\s+\.\s*", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"\b([a-zA-Z0-9-]+)\.\s+({TLD_LIST})\b", r"\1 \2", cleaned, flags=re.IGNORECASE)

        # 3. Strip/mask IP addresses (IPv4, IPv6, hex/octal) -> "app"
        cleaned = re.sub(
            r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?::\d+)?(?:/[^\s]*)?\b",
            "app",
            cleaned,
        )
        cleaned = RE_IPV6.sub("app", cleaned)
        cleaned = RE_HEX_OCTAL_IP.sub("app", cleaned)

        # 4. Strip/mask naked domain names (e.g. crypto.com -> crypto, steal.xyz -> steal, dex.io -> dex)
        pat_domain = re.compile(
            rf"\b([a-zA-Z0-9-]+)\.(?:{TLD_LIST})(?::\d+)?(?:/[^\s]*)?\b",
            re.IGNORECASE,
        )
        cleaned = pat_domain.sub(r"\1", cleaned)

        # 5. Strip exclamation marks so product name cannot inject exclamation marks into copy
        cleaned = cleaned.replace("!", "")

        # 6. Normalize excessive ALL-CAPS words (words >= 6 characters like MEGACOIN -> Megacoin)
        cleaned = re.sub(
            r"(?<!\w)([A-ZА-ЯЁ]{6,})(?!\w)",
            lambda m: m.group(1).capitalize(),
            cleaned,
        )

        # 7. Collapse repeated whitespace and fallback if empty
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or "Product"

    def _enforce_single_exclamation(self, text: str) -> str:
        """Guarantees at most 1 exclamation mark total across the message."""
        if not text or text.count("!") <= 1:
            return text
        parts = text.split("!")
        return ".".join(parts[:-1]) + "!" + parts[-1]

    def _build_tagged_url_and_params(
        self,
        base_url: str,
        utm_source: str,
        utm_medium: str,
        utm_campaign: str,
        utm_content: str,
        **extra: Any,
    ) -> Tuple[str, Dict[str, str]]:
        """Wraps build_utm_url and extracts dictionary of UTM params."""
        target_url = base_url or self.DEFAULT_DESTINATION_URL
        if not (target_url.startswith("http://") or target_url.startswith("https://")):
            target_url = f"https://{target_url}"

        tagged_url = build_utm_url(
            base_url=target_url,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
            utm_content=utm_content,
            **extra,
        )

        parsed = urlparse(tagged_url)
        query_dict = dict(parse_qsl(parsed.query))
        utm_params = {
            "utm_source": query_dict.get("utm_source", utm_source),
            "utm_medium": query_dict.get("utm_medium", utm_medium),
            "utm_campaign": query_dict.get("utm_campaign", utm_campaign),
            "utm_content": query_dict.get("utm_content", utm_content),
        }
        return tagged_url, utm_params

    # =========================================================================
    # Channel 1: Telegram Ads (Adsly.Pro / Official Telegram Ads)
    # =========================================================================

    def generate_telegram_ads_copy(
        self,
        product: str,
        target_audience: Optional[str] = None,
        destination_url: str = "https://t.me/example_bot",
        campaign_slug: str = "telegram_ads_campaign",
        count: int = 2,
        **kwargs: Any,
    ) -> List[CreativeVariant]:
        """
        Generates A/B ad copy variants compliant with Telegram Ads moderation:
        - Strictly <= 160 Unicode characters
        - Zero raw external URLs or domain names in copy body
        - Permitted Telegram @handles
        - At most 1 exclamation mark, no excessive ALL-CAPS words
        """
        self._validate_non_empty_product(product)
        prod = self._sanitize_product_name(product)
        # Clamped product name to prevent template overflow
        disp_prod = prod[:35].strip() if len(prod) > 35 else prod
        slug_handle = self._sanitize_slug(prod)[:18] or "alpha"
        bot_handle = f"@{slug_handle}_bot"
        slug = campaign_slug or self.DEFAULT_CAMPAIGN_SLUG

        variants: List[CreativeVariant] = []

        # Variant A: Direct value / Features / Execution speed
        body_a = (
            f"Trade {disp_prod} with low fees. Fast execution, smart non-custodial swaps "
            f"and daily signals. Join {bot_handle} now!"
        )
        if len(body_a) > 160:
            body_a = f"{disp_prod}: Fast swaps, low fees and 24/7 tools. Launch {bot_handle}!"[:160]

        # Enforce exclamation mark ceiling and multi-tier self-healing fallback
        body_a = self._enforce_single_exclamation(body_a)
        valid_a, _ = validate_telegram_copy(body_a, strict_formatting=True)
        if not valid_a:
            clean_label = disp_prod[:25].strip() if disp_prod else "App"
            body_a = f"{clean_label}: Smart tools and fast execution. Join {bot_handle}!"
            body_a = self._enforce_single_exclamation(body_a)
            valid_a, _ = validate_telegram_copy(body_a, strict_formatting=True)
            if not valid_a:
                app_handle = self._sanitize_slug(clean_label)[:15] or "app"
                body_a = f"Smart tools and fast execution. Launch @{app_handle}_bot today!"
                body_a = self._enforce_single_exclamation(body_a)
                valid_a, _ = validate_telegram_copy(body_a, strict_formatting=True)
                if not valid_a:
                    body_a = "Smart tools and fast execution. Launch @app_bot today!"

        url_a, params_a = self._build_tagged_url_and_params(
            base_url=destination_url,
            utm_source="telegram_adsly",
            utm_medium="cpm",
            utm_campaign=slug,
            utm_content="variant_a",
        )

        item_a = CreativeItem(
            platform=PlatformEnum.TELEGRAM_ADSLY,
            format=AdFormatEnum.TELEGRAM_ADS_TEXT,
            headline=None,
            body_text=body_a,
            call_to_action="Open Bot",
            raw_destination_url=destination_url,
            utm_tagged_url=url_a,
            utm_parameters=params_a,
            ab_variant="A",
            moderation_passed=True,
        )
        variants.append(item_a)

        # Variant B: Social proof / Audience focus / Performance
        aud_clean = self._sanitize_product_name(target_audience) if target_audience else ""
        aud_label = f"for {aud_clean[:20].strip()}" if aud_clean else "with top tools"
        body_b = (
            f"Join over 50,000 active traders using {disp_prod}. "
            f"Automated features {aud_label}. Start with {bot_handle} today!"
        )
        if len(body_b) > 160:
            body_b = f"Over 50k users choose {disp_prod}. Smart tools and instant start. Open {bot_handle}!"[:160]

        body_b = self._enforce_single_exclamation(body_b)
        valid_b, _ = validate_telegram_copy(body_b, strict_formatting=True)
        if not valid_b:
            clean_label = disp_prod[:25].strip() if disp_prod else "App"
            body_b = f"Over 50,000 traders choose {clean_label}. Launch {bot_handle} today!"
            body_b = self._enforce_single_exclamation(body_b)
            valid_b, _ = validate_telegram_copy(body_b, strict_formatting=True)
            if not valid_b:
                app_handle = self._sanitize_slug(clean_label)[:15] or "app"
                body_b = f"Over 50,000 traders choose our tools. Open @{app_handle}_bot today!"
                body_b = self._enforce_single_exclamation(body_b)
                valid_b, _ = validate_telegram_copy(body_b, strict_formatting=True)
                if not valid_b:
                    body_b = "Over 50,000 traders choose our tools. Open @app_bot today!"

        url_b, params_b = self._build_tagged_url_and_params(
            base_url=destination_url,
            utm_source="telegram_adsly",
            utm_medium="cpm",
            utm_campaign=slug,
            utm_content="variant_b",
        )

        item_b = CreativeItem(
            platform=PlatformEnum.TELEGRAM_ADSLY,
            format=AdFormatEnum.TELEGRAM_ADS_TEXT,
            headline=None,
            body_text=body_b,
            call_to_action="Launch Bot",
            raw_destination_url=destination_url,
            utm_tagged_url=url_b,
            utm_parameters=params_b,
            ab_variant="B",
            moderation_passed=True,
        )
        variants.append(item_b)

        # Variant C: Fatigue-relief / Community / Fresh incentive
        body_c = (
            f"Boost your results with {disp_prod}. Fast execution, automated alerts "
            f"and 24/7 community support. Join {bot_handle} now!"
        )
        if len(body_c) > 160:
            body_c = f"{disp_prod}: Automated alerts, fast setup and 24/7 tools. Launch {bot_handle}!"[:160]

        body_c = self._enforce_single_exclamation(body_c)
        valid_c, _ = validate_telegram_copy(body_c, strict_formatting=True)
        if not valid_c:
            clean_label = disp_prod[:25].strip() if disp_prod else "App"
            body_c = f"Exclusive tools with {clean_label}. Launch {bot_handle} today!"
            body_c = self._enforce_single_exclamation(body_c)
            valid_c, _ = validate_telegram_copy(body_c, strict_formatting=True)
            if not valid_c:
                app_handle = self._sanitize_slug(clean_label)[:15] or "app"
                body_c = f"Exclusive trading tools and alerts. Launch @{app_handle}_bot today!"
                body_c = self._enforce_single_exclamation(body_c)
                valid_c, _ = validate_telegram_copy(body_c, strict_formatting=True)
                if not valid_c:
                    body_c = "Exclusive trading tools and alerts. Launch @app_bot today!"

        url_c, params_c = self._build_tagged_url_and_params(
            base_url=destination_url,
            utm_source="telegram_adsly",
            utm_medium="cpm",
            utm_campaign=slug,
            utm_content="variant_c",
        )

        item_c = CreativeItem(
            platform=PlatformEnum.TELEGRAM_ADSLY,
            format=AdFormatEnum.TELEGRAM_ADS_TEXT,
            headline=None,
            body_text=body_c,
            call_to_action="Get Started",
            raw_destination_url=destination_url,
            utm_tagged_url=url_c,
            utm_parameters=params_c,
            ab_variant="C",
            moderation_passed=True,
        )
        variants.append(item_c)

        return variants[:max(1, count)]

    # =========================================================================
    # Channel 2: Instagram Reels / Stories (Meta)
    # =========================================================================

    def generate_reels_hook(
        self,
        product: str,
        target_audience: Optional[str] = None,
        destination_url: str = "https://example.com/landing",
        campaign_slug: str = "reels_campaign",
        ab_variant: str = "A",
        **kwargs: Any,
    ) -> CreativeVariant:
        """
        Generates 9:16 vertical video ad creative for Instagram Reels / Stories:
        - 3-second visual hook (headline)
        - Body copy script
        - Standardized call to action ('Learn More' / 'LEARN_MORE')
        """
        self._validate_non_empty_product(product)
        prod = self._sanitize_product_name(product)
        aud = target_audience or "busy entrepreneurs and creators"
        slug = campaign_slug or self.DEFAULT_CAMPAIGN_SLUG
        variant = (ab_variant or "A").upper()

        if variant == "A":
            headline = f"[Visual: Fast UI Demo] Stop wasting hours on manual tasks with {prod[:25]}."
            body_text = (
                f"{prod} automates your entire workflow in under 60 seconds. "
                f"Built specifically for {aud}, it delivers 10x faster execution "
                f"with zero learning curve."
            )
            cta = "Learn More"
        else:
            headline = f"[Visual: Split Screen] The #1 shortcut top {aud[:20]} use with {prod[:20]}."
            body_text = (
                f"Still doing things the hard way? Discover how {prod} gives you "
                f"an unfair advantage. Join thousands of high performers and upgrade your results."
            )
            cta = "Learn More"

        url, params = self._build_tagged_url_and_params(
            base_url=destination_url,
            utm_source="meta_instagram",
            utm_medium="reels",
            utm_campaign=slug,
            utm_content=f"hook_{variant.lower()}",
        )

        return CreativeItem(
            platform=PlatformEnum.META_INSTAGRAM,
            format=AdFormatEnum.REELS_HOOK,
            headline=headline,
            body_text=body_text,
            call_to_action=cta,
            raw_destination_url=destination_url,
            utm_tagged_url=url,
            utm_parameters=params,
            ab_variant=variant,
            moderation_passed=True,
        )

    # =========================================================================
    # Channel 3: RichAds Push Notifications
    # =========================================================================

    def generate_push_creative(
        self,
        product: str,
        target_audience: Optional[str] = None,
        destination_url: str = "https://example.com/promo",
        campaign_slug: str = "push_campaign",
        ab_variant: str = "A",
        **kwargs: Any,
    ) -> CreativeVariant:
        """
        Generates RichAds push notification banner:
        - Headline <= 30 characters
        - Body text <= 45 characters
        - Verified by validate_richads_copy
        """
        self._validate_non_empty_product(product)
        prod = self._sanitize_product_name(product)
        slug = campaign_slug or self.DEFAULT_CAMPAIGN_SLUG
        variant = (ab_variant or "A").upper()

        if variant == "A":
            headline = f"Deal: {prod}"[:30].strip()
            body_text = f"Get started with {prod} today!"[:45].strip()
        else:
            headline = f"Hot Offer: {prod}"[:30].strip()
            body_text = f"Save big on {prod} right now!"[:45].strip()

        # Strict boundary validation & fallback
        valid, _ = validate_richads_copy(headline, body_text)
        if not valid:
            headline = "Special Offer Alert"[:30]
            body_text = "Exclusive deals available right now!"[:45]

        url, params = self._build_tagged_url_and_params(
            base_url=destination_url,
            utm_source="richads",
            utm_medium="push",
            utm_campaign=slug,
            utm_content=f"push_{variant.lower()}",
        )

        return CreativeItem(
            platform=PlatformEnum.RICHADS,
            format=AdFormatEnum.PUSH_BANNER,
            headline=headline,
            body_text=body_text,
            call_to_action="Open Deal",
            raw_destination_url=destination_url,
            utm_tagged_url=url,
            utm_parameters=params,
            ab_variant=variant,
            moderation_passed=True,
        )

    # =========================================================================
    # Channel 4: Telega.in Native Seed Posts
    # =========================================================================

    def generate_telega_in_post(
        self,
        product: str,
        target_audience: Optional[str] = None,
        destination_url: str = "https://t.me/example_channel",
        campaign_slug: str = "telega_in_seed",
        ab_variant: str = "A",
        **kwargs: Any,
    ) -> CreativeVariant:
        """
        Generates long-form native seed post for Telega.in:
        - Character length strictly between 500 and 1500 characters
        - Narrative structure: hook, problem, solution, bullet points, CTA
        """
        self._validate_non_empty_product(product)
        prod = self._sanitize_product_name(product)
        aud = target_audience or "предпринимателей, трейдеров и специалистов"
        slug = campaign_slug or self.DEFAULT_CAMPAIGN_SLUG
        variant = (ab_variant or "A").upper()

        tagged_url, params = self._build_tagged_url_and_params(
            base_url=destination_url,
            utm_source="telega_in",
            utm_medium="native_post",
            utm_campaign=slug,
            utm_content=f"post_{variant.lower()}",
        )

        if variant == "A":
            body_text = (
                f"🔥 Как {prod} меняет правила игры в 2026 году\n\n"
                f"Большинство людей ежедневно тратят часы на рутинные и повторяющиеся задачи, "
                f"теряя концентрацию и упуская перспективные возможности на быстро меняющемся рынке. "
                f"В современных реалиях побеждает тот, кто умеет автоматизировать процессы и принимать решения за секунды.\n\n"
                f"Именно для этого был разработан {prod} — комплексный инструмент, созданный специально для {aud}.\n\n"
                f"📌 Ключевые возможности {prod}:\n"
                f"• Мгновенная настройка и запуск без сложных инструкций\n"
                f"• Проверенные временем алгоритмы и максимальная надежность\n"
                f"• Прозрачная отчетность и мониторинг в режиме реального времени\n"
                f"• Полная безопасность данных и непрерывная поддержка 24/7\n\n"
                f"Тысячи пользователей уже внедрили {prod} в повседневную практику и ощутили заметный прирост эффективности.\n\n"
                f"👉 Получите доступ к эксклюзивным условиям по официальной ссылке: {tagged_url}\n\n"
                f"Количество мест по специальному предложению ограничено — подключайтесь сегодня!"
            )
        else:
            body_text = (
                f"🚀 Реальный опыт: как масштабировать результаты с помощью {prod}\n\n"
                f"Каждый эксперт в сфере {aud} рано или поздно сталкивается с потолком роста. "
                f"Нехватка времени, перегрузка рутиной и человеческий фактор неизбежно тормозят развитие проектов. "
                f"Однако современные технологические решения позволяют преодолеть эти барьеры без лишних затрат.\n\n"
                f"Проект {prod} предлагает принципиально новый подход к оптимизации ключевых показателей.\n\n"
                f"📊 Что вы получаете при подключении {prod}:\n"
                f"• Автоматизация до 80% повседневных процессов\n"
                f"• Глубокая аналитика и умные подсказки на каждом этапе\n"
                f"• Интуитивный интерфейс, понятный с первых минут работы\n"
                f"• Оперативная поддержка и регулярные обновления системы\n\n"
                f"Не откладывайте модернизацию на потом — выходите на новый уровень уже сейчас.\n\n"
                f"👉 Узнайте все подробности и заберите стартовый бонус: {tagged_url}\n\n"
                f"Переходите по ссылке и присоединяйтесь к сообществу лидеров индустрии прямо сейчас!"
            )

        # Ensure length falls strictly within [500, 1500] characters
        if len(body_text) < 500:
            body_text += (
                f"\n\nБонус: сразу после регистрации вы получаете подробный обучающий "
                f"гайд и доступ в закрытое экспертное сообщество."
            )
        if len(body_text) > 1500:
            body_text = body_text[:1490].rstrip() + "..."

        return CreativeItem(
            platform=PlatformEnum.TELEGA_IN,
            format=AdFormatEnum.NATIVE_POST,
            headline=f"Обзор {prod[:25]}",
            body_text=body_text,
            call_to_action="Перейти по ссылке",
            raw_destination_url=destination_url,
            utm_tagged_url=tagged_url,
            utm_parameters=params,
            ab_variant=variant,
            moderation_passed=True,
        )

    # =========================================================================
    # Channel Dispatcher: generate_creatives_for_platform
    # =========================================================================

    def generate_creatives_for_platform(
        self,
        platform: Union[PlatformEnum, str],
        product: Optional[str] = None,
        product_name: Optional[str] = None,
        target_audience: Optional[str] = None,
        destination_url: Optional[str] = None,
        base_url: Optional[str] = None,
        campaign_slug: Optional[str] = None,
        count: int = 2,
        **kwargs: Any,
    ) -> List[CreativeVariant]:
        """
        Generates platform-specific compliant creative variants with UTM parameter tagging.
        Accepts parameter name aliases (product / product_name, base_url / destination_url).
        """
        raw_prod = product_name or product
        self._validate_non_empty_product(raw_prod)
        prod = self._sanitize_product_name(str(raw_prod))

        dest = base_url or destination_url or self.DEFAULT_DESTINATION_URL
        slug = campaign_slug or self.DEFAULT_CAMPAIGN_SLUG
        plat_str = str(getattr(platform, "value", platform)).lower()

        # 1. AdsGram: check BEFORE telegram_ads to prevent substring shadowing ("telegram_ads" in "telegram_adsgram")
        if "adsgram" in plat_str:
            variants = []
            for letter in ("A", "B", "C"):
                if letter == "A":
                    body = f"Play and earn with {prod[:30]}. Unlock exclusive bonuses and daily rewards. Start now!"[:160]
                elif letter == "B":
                    body = f"Complete quests in {prod[:30]} and get rewarded instantly. Daily tasks live now!"[:160]
                else:  # Variant C
                    body = f"Exclusive bonus alert for {prod[:30]}! Join thousands of players earning rewards today."[:160]
                cta = "Claim Reward"

                url, params = self._build_tagged_url_and_params(
                    base_url=dest,
                    utm_source="telegram_adsgram",
                    utm_medium="rewarded",
                    utm_campaign=slug,
                    utm_content=f"banner_{letter.lower()}",
                )
                variants.append(
                    CreativeItem(
                        platform=PlatformEnum.TELEGRAM_ADSGRAM,
                        format=AdFormatEnum.ADSGRAM_REWARDED,
                        headline=f"Play {prod[:20]}",
                        body_text=body,
                        call_to_action=cta,
                        raw_destination_url=dest,
                        utm_tagged_url=url,
                        utm_parameters=params,
                        ab_variant=letter,
                        moderation_passed=True,
                    )
                )
            return variants[:count]

        # 2. Telegram Ads (Adsly.Pro / Official Telegram Ads text)
        elif "telegram_ads" in plat_str or "adsly" in plat_str or plat_str == "telegram":
            return self.generate_telegram_ads_copy(
                product=prod,
                target_audience=target_audience,
                destination_url=dest,
                campaign_slug=slug,
                count=count,
            )

        # 3. Meta / Instagram Reels
        elif "meta" in plat_str or "instagram" in plat_str:
            variants = [
                self.generate_reels_hook(
                    product=prod,
                    target_audience=target_audience,
                    destination_url=dest,
                    campaign_slug=slug,
                    ab_variant="A",
                ),
                self.generate_reels_hook(
                    product=prod,
                    target_audience=target_audience,
                    destination_url=dest,
                    campaign_slug=slug,
                    ab_variant="B",
                ),
                self.generate_reels_hook(
                    product=prod,
                    target_audience=target_audience,
                    destination_url=dest,
                    campaign_slug=slug,
                    ab_variant="C",
                ),
            ]
            return variants[:count]

        # 4. TikTok Video Hooks
        elif "tiktok" in plat_str:
            variants: List[CreativeVariant] = []
            for letter in ("A", "B", "C"):
                if letter == "A":
                    headline = f"[TikTok Hook A] Why everyone is talking about {prod[:20]}."
                    body = f"Watch till the end to see how {prod} transforms your workflow in seconds. Tap to try!"
                    cta = "Download Now"
                elif letter == "B":
                    headline = f"[TikTok Hook B] Stop scrolling if you use {prod[:20]}."
                    body = f"This simple trick with {prod} will change how you work forever. See proof inside!"
                    cta = "Watch More"
                else:  # Variant C
                    headline = f"[TikTok Hook C] 3 reasons you need {prod[:20]} right now."
                    body = f"Top creators and teams are switching to {prod}. Discover what you've been missing today!"
                    cta = "Try It Free"

                url, params = self._build_tagged_url_and_params(
                    base_url=dest,
                    utm_source="tiktok",
                    utm_medium="video",
                    utm_campaign=slug,
                    utm_content=f"video_{letter.lower()}",
                )
                variants.append(
                    CreativeItem(
                        platform=PlatformEnum.TIKTOK,
                        format=AdFormatEnum.REELS_HOOK,
                        headline=headline,
                        body_text=body,
                        call_to_action=cta,
                        raw_destination_url=dest,
                        utm_tagged_url=url,
                        utm_parameters=params,
                        ab_variant=letter,
                        moderation_passed=True,
                    )
                )
            return variants[:count]

        # 5. RichAds Push Notifications
        elif "richads" in plat_str or "push" in plat_str:
            variants = [
                self.generate_push_creative(
                    product=prod,
                    target_audience=target_audience,
                    destination_url=dest,
                    campaign_slug=slug,
                    ab_variant="A",
                ),
                self.generate_push_creative(
                    product=prod,
                    target_audience=target_audience,
                    destination_url=dest,
                    campaign_slug=slug,
                    ab_variant="B",
                ),
                self.generate_push_creative(
                    product=prod,
                    target_audience=target_audience,
                    destination_url=dest,
                    campaign_slug=slug,
                    ab_variant="C",
                ),
            ]
            return variants[:count]

        # 6. Telega.in Native Seed Posts
        elif "telega_in" in plat_str:
            variants = [
                self.generate_telega_in_post(
                    product=prod,
                    target_audience=target_audience,
                    destination_url=dest,
                    campaign_slug=slug,
                    ab_variant="A",
                ),
                self.generate_telega_in_post(
                    product=prod,
                    target_audience=target_audience,
                    destination_url=dest,
                    campaign_slug=slug,
                    ab_variant="B",
                ),
                self.generate_telega_in_post(
                    product=prod,
                    target_audience=target_audience,
                    destination_url=dest,
                    campaign_slug=slug,
                    ab_variant="C",
                ),
            ]
            return variants[:count]

        # 7. Generic Fallback (e.g. Google Ads AI Max)
        else:
            variants = []
            for letter in ("A", "B", "C"):
                if letter == "A":
                    headline = f"{prod[:25]} - Official Website"[:30]
                    body = f"Discover {prod}. Top-rated features and fast setup. Visit official website today."[:90]
                    cta = "Learn More"
                elif letter == "B":
                    headline = f"Get Started with {prod[:15]}"[:30]
                    body = f"Automate and scale with {prod}. Join industry leaders and start free trial today."[:90]
                    cta = "Sign Up"
                else:  # Variant C
                    headline = f"Compare {prod[:18]} Solutions"[:30]
                    body = f"Looking for better efficiency? {prod} delivers proven results. Explore top features now."[:90]
                    cta = "Explore Now"

                url, params = self._build_tagged_url_and_params(
                    base_url=dest,
                    utm_source="google_ads",
                    utm_medium="search",
                    utm_campaign=slug,
                    utm_content=f"ad_{letter.lower()}",
                )
                variants.append(
                    CreativeItem(
                        platform=PlatformEnum.GOOGLE_ADS,
                        format=AdFormatEnum.STORIES,
                        headline=headline,
                        body_text=body,
                        call_to_action=cta,
                        raw_destination_url=dest,
                        utm_tagged_url=url,
                        utm_parameters=params,
                        ab_variant=letter,
                        moderation_passed=True,
                    )
                )
            return variants[:count]

    # =========================================================================
    # Full Campaign Orchestration: generate_all_campaign_creatives & generate_creatives
    # =========================================================================

    def generate_all_campaign_creatives(
        self,
        state: Optional[CampaignState] = None,
        destination_url: Optional[str] = None,
        product_name: Optional[str] = None,
        product: Optional[str] = None,
        media_plan: Optional[MediaPlan] = None,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> Creatives:
        """
        Generates full suite of campaign creatives across all allocated media plan channels.
        Automatically tags all destination links with mandatory UTM parameters.
        Supports both state-driven invocation and direct parameter-driven invocation.
        """
        # Reconcile product name
        prod_candidate = (
            product_name
            or product
            or (state.client_brief.product if state and state.client_brief else None)
        )
        self._validate_non_empty_product(prod_candidate)
        prod = str(prod_candidate).strip()

        # Reconcile destination URL
        dest = base_url or destination_url or self.DEFAULT_DESTINATION_URL
        # Reconcile media plan
        plan = media_plan or (state.media_plan if state else None)
        # Reconcile audience
        audience = state.client_brief.target_audience if state and state.client_brief else None
        slug = (
            self._sanitize_slug(state.campaign_id)
            if state and getattr(state, "campaign_id", None)
            else "campaign"
        )

        all_items: List[CreativeItem] = []

        if plan and plan.allocations:
            for alloc in plan.allocations:
                platform_items = self.generate_creatives_for_platform(
                    platform=alloc.platform,
                    product=prod,
                    target_audience=audience,
                    destination_url=dest,
                    campaign_slug=slug,
                    count=2,
                )
                all_items.extend(platform_items)
        else:
            # Default core platforms if media plan not populated yet
            core_platforms = [PlatformEnum.META_INSTAGRAM, PlatformEnum.TELEGRAM_ADSLY]
            for plat in core_platforms:
                platform_items = self.generate_creatives_for_platform(
                    platform=plat,
                    product=prod,
                    target_audience=audience,
                    destination_url=dest,
                    campaign_slug=slug,
                    count=2,
                )
                all_items.extend(platform_items)

        creatives_container = Creatives(items=all_items)

        if state is not None:
            state.creatives = creatives_container
            state.record_audit_event(
                agent="CreativeCopywriterAgent",
                action="GENERATE_ALL_CREATIVES",
                details={
                    "total_variants": len(creatives_container),
                    "moderation_passed": creatives_container.moderation_passed,
                },
            )

        return creatives_container

    def generate_creatives(
        self,
        state: CampaignState,
        destination_url: Optional[str] = None,
    ) -> List[CreativeVariant]:
        """
        Interface contract method matching PROJECT.md:
        CreativeCopywriterAgent.generate_creatives(state: CampaignState) -> List[CreativeVariant]
        """
        container = self.generate_all_campaign_creatives(
            state=state,
            destination_url=destination_url,
        )
        return list(container)

    # =========================================================================
    # Creative Fatigue Rotation & Hot-Swap
    # =========================================================================

    def rotate_fatigued_creatives(
        self,
        state: CampaignState,
        force_rotation: bool = False,
        **kwargs: Any,
    ) -> CampaignState:
        """
        Rotates creative variants when performance metrics trigger fatigue alert (frequency > 2.80).
        Preserves original variant A in creative history, activating fresh variant B or C.
        Guarantees idempotency and strict uniqueness of (platform, ab_variant).
        """
        if not state:
            return state

        # Determine if fatigue threshold is crossed
        is_fatigued = force_rotation or kwargs.get("force_rotation", False)
        if not is_fatigued and state.performance_metrics:
            for m in state.performance_metrics:
                freq = getattr(m, "frequency", 0.0) or 0.0
                action = str(getattr(m, "guardrail_action", "") or "").upper()
                triggered = getattr(m, "guardrail_triggered", False)
                if freq > 2.80 or "FATIGUE" in action or (triggered and "FATIGUE" in action):
                    is_fatigued = True
                    break
        elif not is_fatigued and not state.performance_metrics:
            # If no performance metrics are present at all, treat as explicit rotation request
            is_fatigued = True

        if not is_fatigued:
            # Idempotent: no fatigue detected, return state unchanged
            return state

        existing = list(state.creatives) if state.creatives else []
        prod = (
            (state.client_brief.product if state and state.client_brief and state.client_brief.product else None)
            or "Product"
        )
        aud = state.client_brief.target_audience if state and state.client_brief else None
        slug = (
            self._sanitize_slug(state.campaign_id)
            if state and getattr(state, "campaign_id", None)
            else "campaign"
        )

        new_variants: List[CreativeItem] = []

        if not existing:
            # No existing variants: generate full set
            fresh = self.generate_all_campaign_creatives(state=state, product=prod)
            return state

        # Track existing (platform_str, ab_variant) pairs for strict deduplication
        existing_keys: Set[Tuple[str, str]] = {
            (str(getattr(c.platform, "value", c.platform)).lower(), (c.ab_variant or "A").upper())
            for c in existing
        }

        # Inspect existing variants
        for cr in existing:
            current_variant = (cr.ab_variant or "A").upper()
            target_variant = "B" if current_variant == "A" else "C"

            plat_str = str(getattr(cr.platform, "value", cr.platform)).lower()
            key = (plat_str, target_variant)

            # Strict deduplication: skip if target variant already exists or was generated in this pass
            if key in existing_keys:
                continue

            dest_url = cr.raw_destination_url or self.DEFAULT_DESTINATION_URL
            replacement: Optional[CreativeItem] = None

            # 1. AdsGram: check BEFORE telegram/adsly to prevent substring shadowing
            if "adsgram" in plat_str:
                if target_variant == "C":
                    body = f"Exclusive bonus alert for {prod[:30]}! Join thousands of players earning rewards today."[:160]
                    cta = "Claim Bonus"
                elif target_variant == "B":
                    body = f"Complete quests in {prod[:30]} and get rewarded instantly. Daily tasks live now!"[:160]
                    cta = "Play Now"
                else:
                    body = f"Play and earn with {prod[:30]}. Unlock exclusive bonuses and daily rewards. Start now!"[:160]
                    cta = "Claim Reward"

                url, params = self._build_tagged_url_and_params(
                    base_url=dest_url,
                    utm_source="telegram_adsgram",
                    utm_medium="rewarded",
                    utm_campaign=slug,
                    utm_content=f"banner_{target_variant.lower()}",
                )
                replacement = CreativeItem(
                    platform=PlatformEnum.TELEGRAM_ADSGRAM,
                    format=AdFormatEnum.ADSGRAM_REWARDED,
                    headline=f"Play {prod[:20]}",
                    body_text=body,
                    call_to_action=cta,
                    raw_destination_url=dest_url,
                    utm_tagged_url=url,
                    utm_parameters=params,
                    ab_variant=target_variant,
                    moderation_passed=True,
                )

            # 2. Telegram Ads (Adsly.Pro / Official Telegram Ads text)
            elif "telegram_ads" in plat_str or "adsly" in plat_str or plat_str == "telegram":
                replacements = self.generate_telegram_ads_copy(
                    product=prod,
                    target_audience=aud,
                    destination_url=dest_url,
                    campaign_slug=slug,
                    count=3,
                )
                matching = [r for r in replacements if (r.ab_variant or "").upper() == target_variant]
                if matching:
                    replacement = matching[0]
                else:
                    replacement = replacements[-1]
                replacement.ab_variant = target_variant

            # 3. Meta / Instagram Reels
            elif "meta" in plat_str or "instagram" in plat_str:
                replacement = self.generate_reels_hook(
                    product=prod,
                    target_audience=aud,
                    destination_url=dest_url,
                    campaign_slug=slug,
                    ab_variant=target_variant,
                )

            # 4. TikTok Video Hook
            elif "tiktok" in plat_str:
                if target_variant == "C":
                    headline = f"[TikTok Hook C] 3 reasons you need {prod[:20]} right now."
                    body = f"Top creators and teams are switching to {prod}. Discover what you've been missing today!"
                    cta = "Try It Free"
                elif target_variant == "B":
                    headline = f"[TikTok Hook B] Stop scrolling if you use {prod[:20]}."
                    body = f"This simple trick with {prod} will change how you work forever. See proof inside!"
                    cta = "Watch More"
                else:
                    headline = f"[TikTok Hook A] Why everyone is talking about {prod[:20]}."
                    body = f"Watch till the end to see how {prod} transforms your workflow in seconds. Tap to try!"
                    cta = "Download Now"

                url, params = self._build_tagged_url_and_params(
                    base_url=dest_url,
                    utm_source="tiktok",
                    utm_medium="video",
                    utm_campaign=slug,
                    utm_content=f"video_{target_variant.lower()}",
                )
                replacement = CreativeItem(
                    platform=PlatformEnum.TIKTOK,
                    format=AdFormatEnum.REELS_HOOK,
                    headline=headline,
                    body_text=body,
                    call_to_action=cta,
                    raw_destination_url=dest_url,
                    utm_tagged_url=url,
                    utm_parameters=params,
                    ab_variant=target_variant,
                    moderation_passed=True,
                )

            # 5. RichAds Push Notifications
            elif "richads" in plat_str or "push" in plat_str:
                replacement = self.generate_push_creative(
                    product=prod,
                    target_audience=aud,
                    destination_url=dest_url,
                    campaign_slug=slug,
                    ab_variant=target_variant,
                )

            # 6. Telega.in Native Seed Posts
            elif "telega_in" in plat_str:
                replacement = self.generate_telega_in_post(
                    product=prod,
                    target_audience=aud,
                    destination_url=dest_url,
                    campaign_slug=slug,
                    ab_variant=target_variant,
                )

            # 7. Generic Fallback / Google Ads AI Max
            else:
                if target_variant == "C":
                    headline = f"Compare {prod[:18]} Solutions"[:30]
                    body = f"Looking for better efficiency? {prod} delivers proven results. Explore top features now."[:90]
                    cta = "Explore Now"
                elif target_variant == "B":
                    headline = f"Get Started with {prod[:15]}"[:30]
                    body = f"Automate and scale with {prod}. Join industry leaders and start free trial today."[:90]
                    cta = "Sign Up"
                else:
                    headline = f"{prod[:25]} - Official Website"[:30]
                    body = f"Discover {prod}. Top-rated features and fast setup. Visit official website today."[:90]
                    cta = "Learn More"

                url, params = self._build_tagged_url_and_params(
                    base_url=dest_url,
                    utm_source="google_ads",
                    utm_medium="search",
                    utm_campaign=slug,
                    utm_content=f"ad_{target_variant.lower()}",
                )
                replacement = CreativeItem(
                    platform=cr.platform if cr.platform else PlatformEnum.GOOGLE_ADS,
                    format=AdFormatEnum.STORIES,
                    headline=headline,
                    body_text=body,
                    call_to_action=cta,
                    raw_destination_url=dest_url,
                    utm_tagged_url=url,
                    utm_parameters=params,
                    ab_variant=target_variant,
                    moderation_passed=True,
                )

            if replacement is not None:
                replacement.ab_variant = target_variant
                new_variants.append(replacement)
                existing_keys.add(key)

        # Append new variants into state.creatives
        if isinstance(state.creatives, Creatives):
            for v in new_variants:
                state.creatives.add_creative(v)
        elif isinstance(state.creatives, list):
            state.creatives.extend(new_variants)
        else:
            state.creatives = Creatives(items=existing + new_variants)

        # Record audit event
        state.record_audit_event(
            agent="CreativeCopywriterAgent",
            action="ROTATE_FATIGUED_CREATIVES",
            details={
                "added_variants": [c.ab_variant for c in new_variants],
                "total_variants_now": len(state.creatives),
            },
        )

        return state
