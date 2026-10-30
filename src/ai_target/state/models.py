"""
Core CampaignState and constituent sub-models for the Multi-Agent Advertising Campaign Platform.
Compliant with Python 3.12+ and Pydantic v2.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import parse_qsl, urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from ai_target.utils.moderation import (
    TLD_LIST,
    validate_telegram_copy,
)


# ============================================================================
# 1. Domain Exceptions
# ============================================================================

class CampaignStateError(Exception):
    """Base exception for all CampaignState and lifecycle errors."""
    pass


class PaymentVerificationError(CampaignStateError, PermissionError, ValueError):
    """
    Raised when an operation attempts to transition a campaign to an active status
    (e.g., LIVE or OPTIMIZING) without confirmed payment verification.
    Inherits from CampaignStateError, PermissionError, and ValueError for maximum compatibility.
    """
    def __init__(
        self,
        message_or_campaign_id: Optional[str] = None,
        target_status: Optional[Any] = None,
        message: Optional[str] = None,
        campaign_id: Optional[str] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        cid = campaign_id or (message_or_campaign_id if target_status is not None or message is not None else "UNKNOWN")
        self.campaign_id = cid
        self.target_status = target_status
        if message is not None:
            msg = message
        elif target_status is not None or campaign_id is not None:
            targ_val = getattr(target_status, "value", str(target_status))
            msg = (
                f"Payment Verification Gate Violation: Campaign '{cid}' cannot transition "
                f"to '{targ_val}' because payment has not been verified (financials.payment_verified is False)."
            )
        else:
            msg = str(message_or_campaign_id or "Payment not verified")
        super().__init__(msg)


# Backward-compatible alias
PaymentNotVerifiedError = PaymentVerificationError


class InvalidStateTransitionError(CampaignStateError, ValueError):
    """
    Raised when an illegal or unsupported lifecycle status transition is attempted.
    Inherits from CampaignStateError and ValueError for maximum compatibility.
    """
    def __init__(
        self,
        current_status_or_msg: Any = "Invalid status transition",
        target_status: Optional[Any] = None,
        message: Optional[str] = None,
        current_status: Optional[Any] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        curr = current_status or (current_status_or_msg if target_status is not None or message is not None else None)
        self.current_status = curr
        self.target_status = target_status
        if message is not None:
            msg = message
        elif target_status is not None or current_status is not None:
            curr_val = getattr(curr, "value", str(curr))
            targ_val = getattr(target_status, "value", str(target_status))
            msg = f"Invalid status transition: Cannot move from '{curr_val}' to '{targ_val}'."
        else:
            msg = str(current_status_or_msg)
        super().__init__(msg)


# Backward-compatible alias
InvalidTransitionError = InvalidStateTransitionError


# ============================================================================
# 2. Enums
# ============================================================================

class CampaignStatus(str, Enum):
    """Lifecycle status states for CampaignState FSM."""
    INTAKE = "INTAKE"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    LIVE = "LIVE"
    OPTIMIZING = "OPTIMIZING"
    PAUSED = "PAUSED"


# Active statuses where campaigns incur running ad spend and require verified payment
ACTIVE_STATUSES: Set[CampaignStatus] = {
    CampaignStatus.LIVE,
    CampaignStatus.OPTIMIZING,
}

ACTIVE_STATUS_VALUES: Set[str] = {
    "LIVE",
    "OPTIMIZING",
    "CampaignStatus.LIVE",
    "CampaignStatus.OPTIMIZING",
}


def is_active_status(status: Any) -> bool:
    """
    Returns True if the given status represents an active running campaign status
    (LIVE or OPTIMIZING), whether passed as CampaignStatus enum or string value.
    """
    if status in ACTIVE_STATUSES:
        return True
    if str(status) in ACTIVE_STATUS_VALUES:
        return True
    if getattr(status, "value", None) in ("LIVE", "OPTIMIZING"):
        return True
    return False


class PlatformEnum(str, Enum):
    """Supported advertising platforms and inventory sources."""
    META_INSTAGRAM = "meta_instagram"
    TIKTOK = "tiktok"
    TELEGRAM_ADSLY = "telegram_adsly"
    TELEGRAM_ADSGRAM = "telegram_adsgram"
    TELEGA_IN = "telega_in"
    RICHADS = "richads"
    GOOGLE_ADS = "google_ads"


class AdFormatEnum(str, Enum):
    """Ad format taxonomy across supported platforms."""
    REELS_HOOK = "reels_hook"
    STORIES = "stories"
    TELEGRAM_ADS_TEXT = "telegram_ads_text"
    ADSGRAM_REWARDED = "adsgram_rewarded"
    PUSH_BANNER = "richads_push"
    NATIVE_POST = "telega_in_post"


class CampaignGoalEnum(str, Enum):
    """Standard marketing objective goals."""
    LEADS = "LEADS"
    TRAFFIC = "TRAFFIC"
    SALES = "SALES"
    INSTALLS = "INSTALLS"
    TELEGRAM_SUBSCRIBERS = "TELEGRAM_SUBSCRIBERS"


# ============================================================================
# 3. Base Model Configuration
# ============================================================================

class StateBaseModel(BaseModel):
    """Base model enforcing Pydantic v2 assignment validation and legacy shims."""
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        populate_by_name=True,
        extra="allow",
        allow_inf_nan=False,
    )

    def dict(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Pydantic v1 compatibility alias for model_dump."""
        return self.model_dump(*args, **kwargs)

    def json(self, *args: Any, **kwargs: Any) -> str:
        """Pydantic v1 compatibility alias for model_dump_json."""
        return self.model_dump_json(*args, **kwargs)


# ============================================================================
# 4. Constituent Sub-Models
# ============================================================================

class ClientBrief(StateBaseModel):
    """
    Intake parameter capture.
    Supports direct parameter names (product, geo, goal, budget)
    and aliases (product_name, target_geo).
    """
    product: str = Field(default="", min_length=1, description="Product or service name")
    geo: str = Field(default="", min_length=1, description="Target geography, countries, or regions")
    goal: str = Field(default="", min_length=1, description="Campaign objective (LEADS, TRAFFIC, SALES, etc.)")
    budget: float = Field(..., gt=0.0, description="Gross client budget in USD/USDT")

    product_description: Optional[str] = Field(default=None, description="Detailed product description and USPs")
    target_audience: Optional[str] = Field(default=None, description="Audience demographic & interest persona")
    target_geo: Optional[List[str]] = Field(default=None, description="Structured country codes / ISO tokens")
    competitor_channels: List[str] = Field(default_factory=list, description="Target competitor handles")
    campaign_duration_days: int = Field(default=30, gt=0, description="Planned flight duration in days")

    @model_validator(mode="before")
    @classmethod
    def normalize_brief_inputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize product / product_name
            if "product_name" in data and ("product" not in data or not data["product"]):
                data["product"] = data["product_name"]
            elif "product" in data and ("product_name" not in data or not data["product_name"]):
                data["product_name"] = data["product"]

            if isinstance(data.get("product"), str):
                data["product"] = data["product"].strip()
                data["product_name"] = data["product"]

            # Normalize geo / target_geo
            if "target_geo" in data and ("geo" not in data or not data["geo"]):
                tg = data["target_geo"]
                if isinstance(tg, list):
                    cleaned_tg = [str(x).strip() for x in tg if str(x).strip()]
                    data["target_geo"] = cleaned_tg
                    data["geo"] = ", ".join(cleaned_tg)
                else:
                    data["geo"] = str(tg).strip()
            elif "geo" in data and ("target_geo" not in data or not data["target_geo"]):
                g = data["geo"]
                if isinstance(g, str):
                    cleaned_tg = [x.strip() for x in g.split(",") if x.strip()]
                    data["target_geo"] = cleaned_tg
                    data["geo"] = g.strip()
                else:
                    data["target_geo"] = list(g)

            if isinstance(data.get("goal"), str):
                data["goal"] = data["goal"].strip()
        return data

    @property
    def product_name(self) -> str:
        return self.product

    @product_name.setter
    def product_name(self, value: str) -> None:
        self.product = value


class Financials(StateBaseModel):
    """
    Financial calculation engine model.
    Deducts 12% service commission from gross budget, computes Click.ru (3-5%)
    and eLama (3-6%) cashback projections, and tracks payment verification.
    """
    gross_budget: float = Field(..., gt=0.0, description="Gross client budget")
    currency: str = Field(default="USDT", description="Budget currency (USDT, USD, TON)")
    service_commission_rate: float = Field(default=0.12, ge=0.0, le=1.0, description="Service commission rate (12%)")
    service_commission: float = Field(default=0.0, ge=0.0, description="Gross * commission rate")
    net_media_budget: float = Field(default=0.0, ge=0.0, description="Gross - commission (88% of gross)")

    billing_partner: Optional[str] = Field(default="click_ru", description="Aggregator: click_ru, elama, direct")
    clickru_cashback_rate: float = Field(default=0.05, ge=0.03, le=0.06, description="Click.ru cashback rate (3-5%)")
    elama_cashback_rate: float = Field(default=0.04, ge=0.03, le=0.06, description="eLama cashback rate (3-6%)")
    agency_cashback_rate: Optional[float] = Field(default=None, ge=0.03, le=0.06, description="Agency cashback rate (3-6%)")
    projected_cashback: float = Field(default=0.0, ge=0.0, description="Net spend * partner cashback rate")

    payment_verified: bool = Field(default=False, description="Hard gate flag for LIVE transition")
    payment_reference_id: Optional[str] = Field(default=None, description="Tx hash or invoice reference ID")
    payment_verified_at: Optional[datetime] = Field(default=None, description="UTC confirmation timestamp")

    @model_validator(mode="before")
    @classmethod
    def normalize_financial_inputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "service_commission_amount" in data and "service_commission" not in data:
                data["service_commission"] = data["service_commission_amount"]
            if "net_ad_spend" in data and "net_media_budget" not in data:
                data["net_media_budget"] = data["net_ad_spend"]
            if "estimated_cashback_amount" in data and "projected_cashback" not in data:
                data["projected_cashback"] = data["estimated_cashback_amount"]
        return data

    @model_validator(mode="after")
    def compute_financial_breakdown(self) -> Financials:
        # 1. Compute 12% service commission if not explicitly specified
        if self.service_commission == 0.0 and self.gross_budget > 0:
            object.__setattr__(self, "service_commission", round(self.gross_budget * self.service_commission_rate, 2))

        # 2. Compute net media spend (88% of gross)
        if self.net_media_budget == 0.0 and self.gross_budget > 0:
            object.__setattr__(self, "net_media_budget", round(self.gross_budget - self.service_commission, 2))

        # 3. Determine agency cashback rate if not set explicitly
        if self.agency_cashback_rate is None:
            partner = (self.billing_partner or "click_ru").lower()
            object.__setattr__(
                self,
                "agency_cashback_rate",
                self.elama_cashback_rate if "elama" in partner else self.clickru_cashback_rate,
            )

        # 4. Compute projected cashback from billing aggregator
        rate = self.agency_cashback_rate or 0.05
        if self.projected_cashback == 0.0 and self.net_media_budget > 0:
            object.__setattr__(self, "projected_cashback", round(self.net_media_budget * rate, 2))

        return self

    @property
    def service_commission_amount(self) -> float:
        return self.service_commission

    @service_commission_amount.setter
    def service_commission_amount(self, value: float) -> None:
        self.service_commission = value

    @property
    def net_ad_spend(self) -> float:
        return self.net_media_budget

    @net_ad_spend.setter
    def net_ad_spend(self, value: float) -> None:
        self.net_media_budget = value

    @property
    def estimated_cashback_amount(self) -> float:
        return self.projected_cashback

    @estimated_cashback_amount.setter
    def estimated_cashback_amount(self, value: float) -> None:
        self.projected_cashback = value


class ChannelAllocation(StateBaseModel):
    """
    Allocation line item for an ad channel.
    Enforces minimum platform thresholds:
    - Instagram Reels & AdsGram: daily_budget >= 10.0 USDT/day
    - Adsly.Pro: cpm_estimate >= 0.10 TON
    """
    platform: Union[PlatformEnum, str] = Field(..., description="Platform identifier")
    allocated_budget: float = Field(..., gt=0.0, description="Total budget allocated to channel")
    daily_budget: float = Field(..., gt=0.0, description="Daily budget pacing")
    cpm_estimate: Optional[float] = Field(default=None, description="Estimated CPM")
    cpc_estimate: Optional[float] = Field(default=None, description="Estimated CPC")
    currency: str = Field(default="USDT", description="Currency unit")
    notes: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def validate_platform_minimum_thresholds(self) -> ChannelAllocation:
        plat_str = str(self.platform).lower()

        # Threshold 1: Instagram Reels & AdsGram >= 10 USDT/day
        if "instagram" in plat_str or "reels" in plat_str or "adsgram" in plat_str or "meta" in plat_str:
            if self.daily_budget < 10.0:
                raise ValueError(
                    f"Platform minimum violation: '{self.platform}' minimum daily budget of 10.0 USDT required "
                    f"(got {self.daily_budget})."
                )

        # Threshold 2: Adsly.Pro CPM >= 0.10 TON
        if "adsly" in plat_str or "ton" in plat_str:
            if self.cpm_estimate is not None and self.cpm_estimate < 0.10:
                raise ValueError(
                    f"Platform minimum violation: Adsly.Pro CPM bid must be >= 0.10 TON "
                    f"(got {self.cpm_estimate})."
                )

        return self


class MediaPlan(StateBaseModel):
    """Media plan model aggregating channel allocations."""
    allocations: List[ChannelAllocation] = Field(default_factory=list)
    total_allocated: float = Field(default=0.0, ge=0.0)
    platform_threshold_checks_passed: bool = Field(default=False)

    @model_validator(mode="after")
    def verify_plan_totals(self) -> MediaPlan:
        object.__setattr__(self, "total_allocated", round(sum(a.allocated_budget for a in self.allocations), 2))
        object.__setattr__(self, "platform_threshold_checks_passed", len(self.allocations) > 0)
        return self

    def add_allocation(self, allocation: ChannelAllocation) -> None:
        self.allocations.append(allocation)
        object.__setattr__(self, "total_allocated", round(sum(a.allocated_budget for a in self.allocations), 2))
        object.__setattr__(self, "platform_threshold_checks_passed", len(self.allocations) > 0)

    def get_allocation_for_platform(self, platform: Union[PlatformEnum, str]) -> Optional[ChannelAllocation]:
        plat_str = str(platform).lower()
        for alloc in self.allocations:
            if str(alloc.platform).lower() == plat_str:
                return alloc
        return None


class CreativeItem(StateBaseModel):
    """
    Individual ad copy variant with automated moderation and UTM tracking validation.
    """
    creative_id: str = Field(default_factory=lambda: f"cr_{uuid.uuid4().hex[:8]}")
    platform: Union[PlatformEnum, str] = Field(...)
    format: Union[AdFormatEnum, str] = Field(...)
    headline: Optional[str] = Field(default=None, max_length=255)
    body_text: str = Field(...)
    character_count: int = Field(default=0)
    call_to_action: str = Field(default="Learn More")
    raw_destination_url: str = Field(...)
    utm_tagged_url: str = Field(...)
    utm_parameters: Dict[str, str] = Field(default_factory=dict)
    ab_variant: str = Field(default="A", description="Variant letter: A, B, etc.")
    status: str = Field(default="ACTIVE", description="Creative delivery status: ACTIVE or PAUSED")
    moderation_passed: bool = Field(default=False)
    moderation_flags: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_copy_moderation(self) -> CreativeItem:
        object.__setattr__(self, "character_count", len(self.body_text))
        flags: List[str] = []
        plat_str = str(self.platform).lower()
        fmt_str = str(self.format).lower()

        # 1. Telegram Ads Moderation Rules
        if "telegram" in plat_str or "adsly" in plat_str or "telegram_ads" in fmt_str:
            if self.character_count > 160:
                flags.append(f"Telegram Ads text exceeds 160 chars (current: {self.character_count})")

            # Validate against complete Telegram moderation rules (TLD list, URLs, IPs, obfuscation)
            valid_tg, tg_reason = validate_telegram_copy(self.body_text, strict_formatting=True)
            if not valid_tg and tg_reason:
                if "exceeds" not in tg_reason.lower() or self.character_count <= 160:
                    if "exclamation" in tg_reason.lower() or "capitalization" in tg_reason.lower():
                        flags.append(f"Telegram Ads formatting violation: {tg_reason}")
                    else:
                        flags.append(f"Raw external links are strictly forbidden in Telegram Ads body text: {tg_reason}")
            else:
                # Supplementary defense referencing complete TLD_LIST from moderation engine
                raw_url_pattern = re.compile(
                    rf"(https?://\S+|www\.\S+|[a-zA-Z0-9-]+\.(?:{TLD_LIST})(?:/\S*)?)",
                    re.IGNORECASE,
                )
                cleaned_text = re.sub(r"@[a-zA-Z0-9_]+", "", self.body_text)
                if raw_url_pattern.search(cleaned_text):
                    flags.append("Raw external links are strictly forbidden in Telegram Ads body text")

        # 2. RichAds Push Moderation Rules
        if "push" in fmt_str or "richads" in plat_str:
            if self.headline and len(self.headline) > 30:
                flags.append(f"Push headline exceeds 30 characters (current: {len(self.headline)})")
            if self.character_count > 45:
                flags.append(f"Push body exceeds 45 characters (current: {self.character_count})")

        # 3. Mandatory UTM Parameters Verification
        required_utms = {"utm_source", "utm_medium", "utm_campaign", "utm_content"}
        missing_utms = required_utms - set(self.utm_parameters.keys())
        if missing_utms:
            # Attempt to extract missing UTMs from utm_tagged_url
            if self.utm_tagged_url:
                parsed_url = urlparse(self.utm_tagged_url)
                query_params = dict(parse_qsl(parsed_url.query))
                missing_from_url = required_utms - set(query_params.keys())
                if missing_from_url:
                    flags.append(f"Missing mandatory UTM parameters: {sorted(list(missing_from_url))}")
                else:
                    for k in required_utms:
                        self.utm_parameters[k] = query_params[k]
            else:
                flags.append(f"Missing mandatory UTM parameters: {sorted(list(missing_utms))}")

        object.__setattr__(self, "moderation_flags", flags)
        object.__setattr__(self, "moderation_passed", len(flags) == 0)
        return self


# Backward-compatible alias
CreativeVariant = CreativeItem


class Creatives(StateBaseModel):
    """
    Container model for creatives collection.
    Supports iteration, indexing, len, and direct list assignment.
    """
    items: List[CreativeItem] = Field(default_factory=list)
    total_variants: int = Field(default=0)
    moderation_passed: bool = Field(default=True)

    @model_validator(mode="after")
    def update_creative_metrics(self) -> Creatives:
        object.__setattr__(self, "total_variants", len(self.items))
        object.__setattr__(self, "moderation_passed", all(i.moderation_passed for i in self.items) if self.items else True)
        return self

    def add_creative(self, creative: CreativeItem) -> None:
        self.items.append(creative)
        object.__setattr__(self, "total_variants", len(self.items))
        if not creative.moderation_passed:
            object.__setattr__(self, "moderation_passed", False)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> CreativeItem:
        return self.items[index]


class LiveDeploymentRecord(StateBaseModel):
    """
    Deployment ledger record for live/staged platform campaigns.
    Enforces initial status strictly as PAUSED (or DISABLE for TikTok).
    """
    deployment_id: str = Field(default_factory=lambda: f"dep_{uuid.uuid4().hex[:8]}")
    platform: Union[PlatformEnum, str] = Field(...)
    external_campaign_id: str = Field(...)
    external_adset_id: Optional[str] = Field(default=None)
    external_ad_id: Optional[str] = Field(default=None)
    status: str = Field(default="PAUSED", description="Initial status strictly PAUSED or DISABLE")
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
    deployed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    adapter_mode: str = Field(default="sandbox", description="sandbox or live")


class LiveDeployments(StateBaseModel):
    """Container model for live deployments and staged payloads."""
    records: List[LiveDeploymentRecord] = Field(default_factory=list)
    staged_payloads: Dict[str, Any] = Field(default_factory=dict)

    def add_deployment(self, record: LiveDeploymentRecord) -> None:
        self.records.append(record)

    def __iter__(self):
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> LiveDeploymentRecord:
        return self.records[index]


class OptimizationRecommendation(StateBaseModel):
    """
    Human-in-the-loop diagnostic recommendation explaining why conversion is low
    and proposing a concrete improvement while keeping the final decision with the marketer.
    """
    recommendation_id: str = Field(default_factory=lambda: f"rec_{uuid.uuid4().hex[:8]}")
    target_id: str = Field(default="campaign", description="Target creative_id or campaign_id")
    category: str = Field(
        default="CREATIVE_HOOK",
        description="CREATIVE_HOOK, OFFER_HEADLINE, LANDING_BOT_FLOW, SALES_SCRIPT, AUDIENCE_FATIGUE, BUDGET_REALLOCATION",
    )
    bottleneck_stage: str = Field(
        default="HOOK",
        description="Funnel stage: HOOK, CLICK, LEAD_MESSAGE, SALE_CLOSE, CPA_EFFICIENCY, FREQUENCY",
    )
    why_low_conversion: str = Field(..., min_length=1, description="Diagnostic explanation of why conversion is low")
    proposed_change: str = Field(..., min_length=1, description="Actionable proposal for the human marketer to approve/reject")
    decision_status: str = Field(
        default="PENDING_USER_DECISION",
        description="PENDING_USER_DECISION, APPROVED, REJECTED, APPLIED",
    )
    decided_by: Optional[str] = Field(default=None, description="Marketer/owner who approved or rejected")
    decided_at: Optional[datetime] = Field(default=None)
    user_comment: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Alias
ActionProposal = OptimizationRecommendation


class ReelCreativeMetrics(StateBaseModel):
    """
    Per-Reel / per-creative full-funnel telemetry and diagnostics model:
    - Tracks Impressions -> 3-sec Views (Hook Rate) -> Clicks (CTR) -> Messages/Leads ("сколько написали") -> Sales ("сколько продалось").
    - Supports automated pausing of underperforming Reels while surfacing root-cause diagnostics
      (`why_low_conversion`) and actionable recommendations (`recommendations`).
    """
    creative_id: str = Field(..., min_length=1, description="Unique ID of the Reel or creative")
    creative_name: Optional[str] = Field(default=None, description="Human-readable name/title of the Reel")
    platform: Union[PlatformEnum, str] = Field(default=PlatformEnum.META_INSTAGRAM)
    format: Union[AdFormatEnum, str] = Field(default=AdFormatEnum.REELS_HOOK)
    status: str = Field(default="ACTIVE", description="ACTIVE or PAUSED")

    spend: float = Field(default=0.0, ge=0.0)
    impressions: int = Field(default=0, ge=0)
    reach: int = Field(default=0, ge=0)
    three_sec_views: int = Field(default=0, ge=0, description="Number of 3-second video views (thumbstops)")
    avg_watch_time_sec: float = Field(default=0.0, ge=0.0, description="Average watch time in seconds")
    hook_rate: float = Field(default=0.0, ge=0.0, description="3-second view rate (%)")
    clicks: int = Field(default=0, ge=0)
    ctr: float = Field(default=0.0, ge=0.0, description="Click-through rate (%)")

    messages_received: int = Field(default=0, ge=0, description="Сколько человек написали (leads/messages in DM or bot)")
    sales_count: int = Field(default=0, ge=0, description="Сколько продалось (closed orders/purchases)")
    conversions: int = Field(default=0, ge=0, description="Primary conversion events count")
    revenue: float = Field(default=0.0, ge=0.0, description="Total revenue generated from closed sales")

    target_cpa: float = Field(default=10.0, gt=0.0)
    target_conversion_rate: float = Field(default=1.0, ge=0.0, description="Minimum acceptable click-to-conversion rate (%)")
    cpa: float = Field(default=0.0, ge=0.0)
    conversion_rate: float = Field(default=0.0, ge=0.0, description="Click-to-conversion rate (%)")
    lead_to_sale_rate: float = Field(default=0.0, ge=0.0, description="Percentage of leads/messages that converted to sales (%)")
    cost_per_message: float = Field(default=0.0, ge=0.0, description="Spend per person who messaged/wrote")
    cost_per_sale: float = Field(default=0.0, ge=0.0, description="Customer Acquisition Cost (CAC) per sale")
    roas: float = Field(default=0.0, ge=0.0, description="Return on Ad Spend (revenue / spend)")
    frequency: float = Field(default=1.0, ge=0.0)

    auto_paused: bool = Field(default=False, description="True if automatically paused due to low conversion or high CPA")
    pause_reason: Optional[str] = Field(default=None)
    why_low_conversion: List[str] = Field(default_factory=list, description="Diagnostic reasons explaining why conversion is low")
    recommendations: List[str] = Field(default_factory=list, description="Proposed improvements for human marketer decision")

    @model_validator(mode="before")
    @classmethod
    def normalize_reel_crm_inputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "leads_count" in data and "messages_received" not in data:
                data["messages_received"] = data["leads_count"]
            if "orders_closed" in data and "sales_count" not in data:
                data["sales_count"] = data["orders_closed"]
        return data

    @model_validator(mode="after")
    def compute_reel_funnel_metrics(self) -> ReelCreativeMetrics:
        # 1. Default conversions to messages_received (or sales_count) if conversions was not explicitly provided
        if "conversions" not in self.model_fields_set or (
            self.conversions == 0 and (self.messages_received > 0 or self.sales_count > 0)
        ):
            if self.messages_received > 0:
                object.__setattr__(self, "conversions", self.messages_received)
            elif self.sales_count > 0:
                object.__setattr__(self, "conversions", self.sales_count)
            elif "conversions" not in self.model_fields_set:
                object.__setattr__(self, "conversions", 0)

        # 2. Hook rate (%)
        if "hook_rate" not in self.model_fields_set:
            if self.impressions > 0 and self.three_sec_views > 0:
                object.__setattr__(self, "hook_rate", round((self.three_sec_views / self.impressions) * 100.0, 2))
            else:
                object.__setattr__(self, "hook_rate", 0.0)

        # 3. CTR (%)
        if "ctr" not in self.model_fields_set:
            if self.impressions > 0 and self.clicks > 0:
                object.__setattr__(self, "ctr", round((self.clicks / self.impressions) * 100.0, 2))
            else:
                object.__setattr__(self, "ctr", 0.0)

        # 4. Conversion rate (%) from clicks
        if "conversion_rate" not in self.model_fields_set:
            if self.clicks > 0 and self.conversions > 0:
                object.__setattr__(self, "conversion_rate", round((self.conversions / self.clicks) * 100.0, 2))
            else:
                object.__setattr__(self, "conversion_rate", 0.0)

        # 5. CPA
        if self.conversions > 0:
            object.__setattr__(self, "cpa", round(self.spend / self.conversions, 2))
        else:
            object.__setattr__(self, "cpa", round(self.spend, 2))

        # 6. CRM Funnel: cost_per_message, cost_per_sale, lead_to_sale_rate, roas
        if self.messages_received > 0:
            object.__setattr__(self, "cost_per_message", round(self.spend / self.messages_received, 2))
            object.__setattr__(self, "lead_to_sale_rate", round((self.sales_count / self.messages_received) * 100.0, 2))
        else:
            object.__setattr__(self, "cost_per_message", round(self.spend, 2))
            object.__setattr__(self, "lead_to_sale_rate", 0.0)

        if self.sales_count > 0:
            object.__setattr__(self, "cost_per_sale", round(self.spend / self.sales_count, 2))
        else:
            object.__setattr__(self, "cost_per_sale", round(self.spend, 2))

        if self.spend > 0 and self.revenue > 0:
            object.__setattr__(self, "roas", round(self.revenue / self.spend, 2))
        elif "roas" not in self.model_fields_set:
            object.__setattr__(self, "roas", 0.0)

        # 7. Frequency
        if self.reach > 0 and self.impressions > 0 and "frequency" not in self.model_fields_set:
            object.__setattr__(self, "frequency", round(self.impressions / self.reach, 2))

        return self

    @property
    def leads_count(self) -> int:
        return self.messages_received

    @leads_count.setter
    def leads_count(self, value: int) -> None:
        self.messages_received = value

    @property
    def orders_closed(self) -> int:
        return self.sales_count

    @orders_closed.setter
    def orders_closed(self, value: int) -> None:
        self.sales_count = value


# Aliases
CreativePerformanceMetrics = ReelCreativeMetrics
ReelTelemetry = ReelCreativeMetrics


class PerformanceMetrics(StateBaseModel):
    """
    Telemetry ingestion, full-funnel CRM tracking, and automated guardrails evaluator:
    - Kill-switch: spend >= 1.5x target CPA with 0 conversions -> KILL_SWITCH
    - Creative fatigue: frequency > 2.8 -> FATIGUE_ALERT
    - Meta learning phase: tracks 50 optimization events
    - Full-funnel CRM: tracks messages_received ("сколько написали") and sales_count ("сколько продалось")
    """
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    platform: Union[PlatformEnum, str] = Field(default=PlatformEnum.META_INSTAGRAM)
    spend: float = Field(default=0.0, ge=0.0)
    impressions: int = Field(default=0, ge=0)
    reach: int = Field(default=0, ge=0)
    three_sec_views: int = Field(default=0, ge=0, description="3-second video views for hook rate")
    hook_rate: float = Field(default=0.0, ge=0.0, description="3-sec view rate (%)")
    clicks: int = Field(default=0, ge=0)
    ctr: float = Field(default=0.0, ge=0.0, description="Click-through rate (%)")
    conversions: int = Field(default=0, ge=0)
    conversion_rate: float = Field(default=0.0, ge=0.0, description="Conversions / clicks (%)")
    messages_received: int = Field(default=0, ge=0, description="Сколько человек написали (leads/messages)")
    sales_count: int = Field(default=0, ge=0, description="Сколько продалось (closed sales/orders)")
    revenue: float = Field(default=0.0, ge=0.0, description="Total sales revenue")
    lead_to_sale_rate: float = Field(default=0.0, ge=0.0, description="sales_count / messages_received (%)")
    cost_per_message: float = Field(default=0.0, ge=0.0, description="Spend / messages_received")
    cost_per_sale: float = Field(default=0.0, ge=0.0, description="CAC: Spend / sales_count")
    roas: float = Field(default=0.0, ge=0.0, description="Return on Ad Spend (revenue / spend)")
    target_cpa: float = Field(default=10.0, gt=0.0)
    cpa: float = Field(default=0.0, ge=0.0)
    frequency: float = Field(default=1.0, ge=0.0)
    learning_phase_status: str = Field(default="LEARNING", description="LEARNING or COMPLETED")
    optimization_events_count: int = Field(default=0, ge=0)
    guardrail_triggered: bool = Field(default=False)
    guardrail_action: Optional[str] = Field(default=None, description="KILL_SWITCH, FATIGUE_ALERT, BID_ADJUST")
    notes: Optional[str] = Field(default=None)
    why_low_conversion: List[str] = Field(default_factory=list, description="Diagnostic reasons for low conversion")
    recommendations: List[str] = Field(default_factory=list, description="Actionable proposals for human decision")

    @model_validator(mode="before")
    @classmethod
    def normalize_crm_inputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "leads_count" in data and "messages_received" not in data:
                data["messages_received"] = data["leads_count"]
            if "orders_closed" in data and "sales_count" not in data:
                data["sales_count"] = data["orders_closed"]
        return data

    @model_validator(mode="after")
    def evaluate_telemetry_guardrails(self) -> PerformanceMetrics:
        # 0. Default conversions from messages_received / sales_count if conversions was not explicitly passed
        if "conversions" not in self.model_fields_set or (
            self.conversions == 0 and (self.messages_received > 0 or self.sales_count > 0)
        ):
            if self.messages_received > 0:
                object.__setattr__(self, "conversions", self.messages_received)
            elif self.sales_count > 0:
                object.__setattr__(self, "conversions", self.sales_count)
            elif "conversions" not in self.model_fields_set:
                object.__setattr__(self, "conversions", 0)

        # 1. Compute CPA
        if self.conversions > 0:
            object.__setattr__(self, "cpa", round(self.spend / self.conversions, 2))
        else:
            object.__setattr__(self, "cpa", round(self.spend, 2))

        # 1a. Compute frequency from impressions / reach if frequency was not explicitly provided
        if self.reach > 0 and self.impressions > 0 and "frequency" not in self.model_fields_set:
            object.__setattr__(self, "frequency", round(self.impressions / self.reach, 2))

        # 1b. Compute funnel rates & CRM metrics (hook_rate, ctr, conversion_rate, lead_to_sale_rate, cost_per_message, cost_per_sale, roas)
        if "hook_rate" not in self.model_fields_set:
            if self.impressions > 0 and self.three_sec_views > 0:
                object.__setattr__(self, "hook_rate", round((self.three_sec_views / self.impressions) * 100.0, 2))
            else:
                object.__setattr__(self, "hook_rate", 0.0)
        if "ctr" not in self.model_fields_set:
            if self.impressions > 0 and self.clicks > 0:
                object.__setattr__(self, "ctr", round((self.clicks / self.impressions) * 100.0, 2))
            else:
                object.__setattr__(self, "ctr", 0.0)
        if "conversion_rate" not in self.model_fields_set:
            if self.clicks > 0 and self.conversions > 0:
                object.__setattr__(self, "conversion_rate", round((self.conversions / self.clicks) * 100.0, 2))
            else:
                object.__setattr__(self, "conversion_rate", 0.0)

        if self.messages_received > 0:
            object.__setattr__(self, "cost_per_message", round(self.spend / self.messages_received, 2))
            object.__setattr__(self, "lead_to_sale_rate", round((self.sales_count / self.messages_received) * 100.0, 2))
        else:
            object.__setattr__(self, "cost_per_message", round(self.spend, 2))
            object.__setattr__(self, "lead_to_sale_rate", 0.0)

        if self.sales_count > 0:
            object.__setattr__(self, "cost_per_sale", round(self.spend / self.sales_count, 2))
        else:
            object.__setattr__(self, "cost_per_sale", round(self.spend, 2))

        if self.spend > 0 and self.revenue > 0:
            object.__setattr__(self, "roas", round(self.revenue / self.spend, 2))
        elif "roas" not in self.model_fields_set:
            object.__setattr__(self, "roas", 0.0)

        # 2. Meta 50-event learning phase evaluation
        if self.optimization_events_count >= 50 or self.conversions >= 50:
            object.__setattr__(self, "learning_phase_status", "COMPLETED")

        # 3. Guardrail 1: Kill-Switch (Spend >= 1.5x target CPA with 0 conversions)
        if self.conversions == 0 and round(self.spend, 4) >= round(1.5 * self.target_cpa, 4) and self.target_cpa > 0:
            object.__setattr__(self, "guardrail_triggered", True)
            object.__setattr__(self, "guardrail_action", "KILL_SWITCH")
            note_msg = (
                f"Kill-switch triggered: spend {self.spend} >= 1.5x target CPA {self.target_cpa} with 0 conversions."
            )
            if self.frequency > 2.8:
                note_msg += f" Concurrent creative fatigue detected: frequency {self.frequency} > 2.8 threshold."
            object.__setattr__(self, "notes", note_msg)

        # 4. Guardrail 2: Creative Fatigue (Frequency > 2.8)
        elif self.frequency > 2.8:
            object.__setattr__(self, "guardrail_triggered", True)
            object.__setattr__(self, "guardrail_action", "FATIGUE_ALERT")
            object.__setattr__(
                self,
                "notes",
                f"Creative fatigue detected: frequency {self.frequency} > 2.8 threshold.",
            )

        return self

    @property
    def leads_count(self) -> int:
        return self.messages_received

    @leads_count.setter
    def leads_count(self, value: int) -> None:
        self.messages_received = value

    @property
    def orders_closed(self) -> int:
        return self.sales_count

    @orders_closed.setter
    def orders_closed(self, value: int) -> None:
        self.sales_count = value


# ============================================================================
# 5. Master CampaignState Model
# ============================================================================

class CampaignState(StateBaseModel):
    """
    Central source-of-truth state model across all 6 agent roles.
    Enforces status lifecycle transitions and the uncompromising payment verification hard gate.
    """
    campaign_id: str = Field(default_factory=lambda: f"cmp_{uuid.uuid4().hex[:12]}")
    status: CampaignStatus = Field(default=CampaignStatus.INTAKE)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    client_brief: Optional[ClientBrief] = Field(default=None)
    financials: Optional[Financials] = Field(default=None)
    media_plan: Optional[MediaPlan] = Field(default=None)
    creatives: Union[Creatives, List[CreativeItem]] = Field(default_factory=list)
    live_deployments: Union[LiveDeployments, List[LiveDeploymentRecord]] = Field(default_factory=list)
    performance_metrics: List[PerformanceMetrics] = Field(default_factory=list)
    reel_metrics: List[ReelCreativeMetrics] = Field(
        default_factory=list,
        description="Per-Reel / per-creative telemetry snapshots for granular auto-pause and diagnostics",
    )
    pending_recommendations: List[OptimizationRecommendation] = Field(
        default_factory=list,
        description="Diagnostic recommendations awaiting human marketer decision (PENDING_USER_DECISION)",
    )
    audit_trail: List[Dict[str, Any]] = Field(default_factory=list)

    def __init__(self, **data: Any) -> None:
        # Pre-validate status and financials BEFORE calling super().__init__(**data)
        # to ensure PaymentVerificationError is raised directly instead of being
        # wrapped into a pydantic.ValidationError by Pydantic's root validator.
        status = data.get("status")
        if is_active_status(status):
            fin = data.get("financials")
            is_verified = False
            if fin is not None:
                if isinstance(fin, Financials):
                    is_verified = getattr(fin, "payment_verified", False) is True
                elif isinstance(fin, dict):
                    try:
                        fin_obj = Financials.model_validate(fin)
                        is_verified = getattr(fin_obj, "payment_verified", False) is True
                    except Exception:
                        pv = fin.get("payment_verified")
                        is_verified = (
                            (pv is True or pv == "true" or pv == "True" or pv == 1)
                            and pv not in (False, 0, 0.0, "0", "false", "False", "no", "off", "f")
                        )
            if not is_verified:
                cid = data.get("campaign_id", "UNKNOWN")
                target_st = (
                    status if isinstance(status, CampaignStatus)
                    else (CampaignStatus(status) if str(status) in CampaignStatus._value2member_map_ else CampaignStatus.LIVE)
                )
                status_label = getattr(target_st, "value", str(target_st))
                raise PaymentVerificationError(
                    campaign_id=cid,
                    target_status=target_st,
                    message=f"HARD GATE VIOLATION: Campaign '{cid}' cannot enter {status_label} status while payment_verified is False.",
                )

        super().__init__(**data)

    def __setattr__(self, name: str, value: Any) -> None:
        # Direct attribute assignment hard gate check for status transitions
        if name == "status" and is_active_status(value):
            financials = getattr(self, "financials", None)
            if not financials or not getattr(financials, "payment_verified", False):
                cid = getattr(self, "campaign_id", "UNKNOWN")
                target_st = (
                    value if isinstance(value, CampaignStatus)
                    else (CampaignStatus(value) if str(value) in CampaignStatus._value2member_map_ else CampaignStatus.LIVE)
                )
                status_label = getattr(target_st, "value", str(target_st))
                raise PaymentVerificationError(
                    campaign_id=cid,
                    target_status=target_st,
                    message=f"HARD GATE VIOLATION: Campaign '{cid}' cannot enter {status_label} status while payment_verified is False.",
                )

        # Direct attribute assignment hard gate check for financials revocation in active status
        curr_status = getattr(self, "status", None)
        if name == "financials" and is_active_status(curr_status):
            is_verified = False
            if value is not None:
                if isinstance(value, Financials):
                    is_verified = getattr(value, "payment_verified", False) is True
                elif isinstance(value, dict):
                    try:
                        fin_obj = Financials.model_validate(value)
                        is_verified = getattr(fin_obj, "payment_verified", False) is True
                    except Exception:
                        pv = value.get("payment_verified")
                        is_verified = pv is True
            if not is_verified:
                cid = getattr(self, "campaign_id", "UNKNOWN")
                status_label = getattr(curr_status, "value", str(curr_status))
                raise PaymentVerificationError(
                    campaign_id=cid,
                    target_status=curr_status,
                    message=f"HARD GATE VIOLATION: Cannot revoke verified payment on Campaign '{cid}' while in {status_label} status.",
                )

        super().__setattr__(name, value)

    @field_validator("creatives", mode="before")
    @classmethod
    def coerce_creatives_input(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [CreativeItem.model_validate(i) if isinstance(i, dict) else i for i in v]
        if isinstance(v, dict) and "items" in v:
            return Creatives(**v)
        return v

    @field_validator("live_deployments", mode="before")
    @classmethod
    def coerce_deployments_input(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [LiveDeploymentRecord.model_validate(i) if isinstance(i, dict) else i for i in v]
        if isinstance(v, dict) and "records" in v:
            return LiveDeployments(**v)
        return v

    @model_validator(mode="after")
    def verify_payment_before_live(self) -> CampaignState:
        """
        Hard Gate: Campaign can NEVER be in active status (LIVE, OPTIMIZING)
        if payment_verified is False.
        """
        if is_active_status(self.status):
            if not self.financials or not getattr(self.financials, "payment_verified", False):
                status_label = getattr(self.status, "value", str(self.status))
                raise PaymentVerificationError(
                    campaign_id=self.campaign_id,
                    target_status=self.status,
                    message=f"HARD GATE VIOLATION: Campaign '{self.campaign_id}' cannot enter {status_label} status while payment_verified is False.",
                )
        return self

    @property
    def creative_metrics(self) -> List[ReelCreativeMetrics]:
        return self.reel_metrics

    @creative_metrics.setter
    def creative_metrics(self, value: List[ReelCreativeMetrics]) -> None:
        self.reel_metrics = value

    @property
    def recommendations(self) -> List[OptimizationRecommendation]:
        return self.pending_recommendations

    @recommendations.setter
    def recommendations(self, value: List[OptimizationRecommendation]) -> None:
        self.pending_recommendations = value

    def transition_to(self, new_status: Union[CampaignStatus, str]) -> CampaignState:
        """
        Executes a formal lifecycle transition according to the transition graph:
        INTAKE -> PLANNING -> AWAITING_APPROVAL -> LIVE -> OPTIMIZING -> PAUSED
        (with re-activation paths to LIVE or OPTIMIZING).
        Raises PaymentVerificationError if new_status is LIVE and payment is unverified.
        Raises InvalidStateTransitionError on illegal status jumps.
        """
        from ai_target.state.transitions import transition_state
        return transition_state(self, new_status)

    def record_audit_event(self, agent: str, action: str, details: Dict[str, Any]) -> None:
        """Records an entry in the campaign audit trail."""
        self.audit_trail.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "action": action,
            "details": details,
        })

