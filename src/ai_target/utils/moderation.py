"""
Platform Moderation Engine for AI Target Campaign Management System.

Enforces creative copy compliance for Telegram Ads (character limits, URL detection,
handle preservation, formatting) and RichAds push notifications (title & body limits).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple


class ModerationError(ValueError):
    """Raised when creative copy violates platform moderation policies."""
    pass


# Telegram Ads Limits
TELEGRAM_MAX_LENGTH = 160
TELEGRAM_MAX_EXCLAMATION_MARKS = 1

# RichAds Limits
RICHADS_MAX_TITLE_LENGTH = 30
RICHADS_MAX_BODY_LENGTH = 45

# Precompiled Regular Expressions for Telegram Moderation
RE_ZERO_WIDTH = re.compile(r"[\u200b-\u200d\ufeff\u00ad\u2060]")
RE_DEFANGED_DOT = re.compile(r"\[\.\]|\(\.\)|\[dot\]|\(dot\)|\s+\.\s*", re.IGNORECASE)

RE_URL_SCHEME = re.compile(r"https?://\S+", re.IGNORECASE)
RE_WWW_PREFIX = re.compile(r"\bwww\.[a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+", re.IGNORECASE)
RE_TME_LINK = re.compile(r"\b(?:t|telegram)\.me/\S+", re.IGNORECASE)

RE_IPV4 = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
)
RE_IPV6 = re.compile(
    r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b|"
    r"\b(?:[0-9a-fA-F]{1,4}:)+:(?:[0-9a-fA-F]{1,4}:)*[0-9a-fA-F]{1,4}\b|"
    r"(?<![0-9a-zA-Z])::(?:[0-9a-fA-F]{1,4}:)*[0-9a-fA-F]{1,4}\b|"
    r"\b(?:[0-9a-fA-F]{1,4}:)+::(?![0-9a-zA-Z])",
    re.IGNORECASE,
)
RE_HEX_OCTAL_IP = re.compile(
    r"\b0x[0-9a-fA-F]{8}\b|"
    r"\b0x[0-9a-fA-F]{1,2}(?:\.(?:0x[0-9a-fA-F]{1,2}|[0-9]{1,3})){3}\b|"
    r"\b0[0-7]+(?:\.(?:0[0-7]+|[0-9]+)){3}\b|"
    r"\b0o[0-7]{11}\b",
    re.IGNORECASE,
)

TLD_LIST = "com|org|net|io|me|ru|co|app|ai|tech|xyz|biz|info|online|pro|store|dev|gg|link|cc|to|tg|site|ly|gd|click|vip"

RE_DOMAIN = re.compile(
    rf"\b[a-zA-Z0-9-]+\.(?:{TLD_LIST})(?:/[^\s]*)?\b",
    re.IGNORECASE,
)
RE_OBFUSCATED_DOMAIN = re.compile(
    rf"\b[a-zA-Z0-9-]+\s*(?:\[\.\]|\(\.\)|\[dot\]|\(dot\)|\s+\.|\.\s+)\s*(?:{TLD_LIST})\b",
    re.IGNORECASE,
)
RE_TELEGRAM_HANDLE = re.compile(r"@[a-zA-Z0-9_]{3,32}\b(?!\.[a-zA-Z0-9])")
RE_EXCESSIVE_CAPS = re.compile(r"(?<!\w)[A-ZА-ЯЁ]{6,}(?!\w)")


def validate_telegram_copy(
    text: str,
    strict_formatting: bool = True,
) -> Tuple[bool, Optional[str]]:
    """
    Validates ad copy against Telegram Ads moderation rules.

    Args:
        text: Ad text to validate.
        strict_formatting: When True, also validates exclamation marks and excessive ALL-CAPS words.

    Returns:
        Tuple[bool, Optional[str]]: (True, None) if valid, (False, reason) if invalid.
    """
    if not isinstance(text, str):
        return False, "Telegram copy text must be a string."

    normalized_text = unicodedata.normalize("NFC", text.strip())
    if not normalized_text:
        return False, "Telegram copy text cannot be empty or whitespace only."

    # 1. Check character length (<= 160 Unicode codepoints)
    char_count = len(normalized_text)
    if char_count > TELEGRAM_MAX_LENGTH:
        return (
            False,
            f"Telegram Ads copy length ({char_count}) exceeds maximum allowed {TELEGRAM_MAX_LENGTH} characters.",
        )

    # 2. Check for prohibited URLs and links
    # Pre-clean zero-width / invisible control characters
    clean_links_text = RE_ZERO_WIDTH.sub("", normalized_text)

    # Check for obfuscated domain patterns before normalization to preserve specific reason
    match_obf = RE_OBFUSCATED_DOMAIN.search(clean_links_text)
    if match_obf:
        return False, f"Obfuscated domain name detected in copy: '{match_obf.group(0)}'."

    # Normalize defanged dots
    clean_defanged_text = RE_DEFANGED_DOT.sub(".", clean_links_text)

    # Mask out valid @username handles before inspecting for domain names or URLs
    # Negative lookahead (?!\.[a-zA-Z0-9]) prevents disguised domains (@channel.com) from being masked
    scrubbed_for_links = RE_TELEGRAM_HANDLE.sub("[HANDLE]", clean_defanged_text)

    if RE_URL_SCHEME.search(scrubbed_for_links) or RE_URL_SCHEME.search(clean_links_text):
        return False, "Raw external URLs (http:// or https://) are strictly prohibited in Telegram Ads copy."

    if RE_WWW_PREFIX.search(scrubbed_for_links) or RE_WWW_PREFIX.search(clean_links_text):
        return False, "Raw external web addresses (www.) are strictly prohibited in Telegram Ads copy."

    if RE_TME_LINK.search(scrubbed_for_links) or RE_TME_LINK.search(clean_links_text):
        return False, "Raw Telegram links (t.me/...) are not permitted in copy body; configure promoted entity instead."

    if (
        RE_IPV4.search(scrubbed_for_links)
        or RE_IPV4.search(clean_links_text)
        or RE_IPV6.search(scrubbed_for_links)
        or RE_IPV6.search(clean_links_text)
        or RE_HEX_OCTAL_IP.search(scrubbed_for_links)
        or RE_HEX_OCTAL_IP.search(clean_links_text)
    ):
        return False, "IP addresses are strictly prohibited in Telegram Ads copy."

    match_domain = RE_DOMAIN.search(scrubbed_for_links) or RE_DOMAIN.search(clean_links_text)
    if match_domain:
        return False, f"Raw domain name or external link detected in copy: '{match_domain.group(0)}'."

    # 3. Formatting checks
    if strict_formatting:
        exclamations = normalized_text.count("!")
        if exclamations > TELEGRAM_MAX_EXCLAMATION_MARKS:
            return (
                False,
                f"Telegram Ads moderation allows at most {TELEGRAM_MAX_EXCLAMATION_MARKS} exclamation mark (found {exclamations}).",
            )

        caps_match = RE_EXCESSIVE_CAPS.search(normalized_text)
        if caps_match:
            return (
                False,
                f"Excessive capitalization detected: word '{caps_match.group(0)}' exceeds allowed length in ALL-CAPS.",
            )

    return True, None


def validate_telegram_ads_copy(text: str) -> bool:
    """
    Validates Telegram Ads copy, returning True or raising ModerationError on violation.
    Compatibility function for E2E boundary testing suite.
    """
    valid, reason = validate_telegram_copy(text, strict_formatting=False)
    if not valid:
        raise ModerationError(reason)
    return True


def validate_richads_copy(
    title: str,
    body: str,
) -> Tuple[bool, Optional[str]]:
    """
    Validates push notification copy against RichAds character caps.

    Args:
        title: Push notification title (max 30 chars).
        body: Push notification body (max 45 chars).

    Returns:
        Tuple[bool, Optional[str]]: (True, None) if valid, (False, reason) if invalid.
    """
    if not isinstance(title, str) or not title.strip():
        return False, "RichAds title must be a non-empty string."

    if not isinstance(body, str) or not body.strip():
        return False, "RichAds body must be a non-empty string."

    norm_title = unicodedata.normalize("NFC", title.strip())
    norm_body = unicodedata.normalize("NFC", body.strip())

    title_len = len(norm_title)
    if title_len > RICHADS_MAX_TITLE_LENGTH:
        return (
            False,
            f"RichAds title length ({title_len}) exceeds maximum allowed {RICHADS_MAX_TITLE_LENGTH} characters.",
        )

    body_len = len(norm_body)
    if body_len > RICHADS_MAX_BODY_LENGTH:
        return (
            False,
            f"RichAds body length ({body_len}) exceeds maximum allowed {RICHADS_MAX_BODY_LENGTH} characters.",
        )

    return True, None
