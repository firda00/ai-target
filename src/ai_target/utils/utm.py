"""
UTM Parameter Engine for AI Target Campaign Management System.

Appends standard UTM tracking parameters (utm_source, utm_medium, utm_campaign, utm_content)
to destination landing page URLs, preserving existing query parameters and fragments.
"""

from __future__ import annotations

from typing import Any, List, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MANDATORY_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")


def build_utm_url(
    base_url: str,
    utm_source: str,
    utm_medium: str,
    utm_campaign: str,
    utm_content: str,
    **extra: Any,
) -> str:
    """
    Builds a destination URL tagged with mandatory UTM parameters.

    Args:
        base_url: Target URL. Must be a valid absolute or recognized web URL.
        utm_source: Traffic source (e.g., 'meta', 'tiktok', 'telegram_ads', 'adsgram').
        utm_medium: Marketing channel (e.g., 'reels', 'story', 'cpc', 'cpm', 'push').
        utm_campaign: Campaign identifier (e.g., 'summer_2026').
        utm_content: Creative/hook identifier (e.g., 'hook_a').
        **extra: Additional query parameters (e.g., utm_term='crypto', ref='click_ru').

    Returns:
        str: Encoded URL with UTM parameters.

    Raises:
        ValueError: If base_url is invalid or any mandatory UTM parameter is missing/empty.
    """
    if not base_url or not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("Base URL must be a non-empty string.")

    base_url = base_url.strip()
    parsed = urlsplit(base_url)

    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid base URL (missing scheme or network location): '{base_url}'")

    mandatory_values = {
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
        "utm_content": utm_content,
    }

    for key, val in mandatory_values.items():
        if val is None or not isinstance(val, str) or not val.strip():
            raise ValueError(f"Missing or empty mandatory UTM parameter: '{key}'")

    # Parse existing query parameters, maintaining order as list of (key, val) tuples
    existing_pairs: List[Tuple[str, str]] = parse_qsl(parsed.query, keep_blank_values=True)

    # Prepare extra parameters and collect all keys that must be overwritten
    extra_params: List[Tuple[str, str]] = []
    keys_to_replace: Set[str] = set(mandatory_values.keys())

    for k, v in extra.items():
        if v is not None:
            # Normalize shorthand 'term' to 'utm_term'
            param_key = "utm_term" if k == "term" else k
            keys_to_replace.add(param_key)
            keys_to_replace.add(k)
            if isinstance(v, (list, tuple)):
                for item in v:
                    extra_params.append((param_key, str(item).strip()))
            else:
                extra_params.append((param_key, str(v).strip()))

    # Filter out existing parameters that will be replaced, preserving multi-value non-UTM params
    final_pairs: List[Tuple[str, str]] = [
        (k, v) for k, v in existing_pairs if k not in keys_to_replace
    ]

    # Append mandatory UTM parameters
    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
        final_pairs.append((key, mandatory_values[key].strip()))

    # Append extra parameters
    for key, val in extra_params:
        final_pairs.append((key, val))

    # Encode new query string
    encoded_query = urlencode(final_pairs, doseq=True)

    # Reassemble URL preserving scheme, netloc, path, query, fragment
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        encoded_query,
        parsed.fragment,
    ))


def append_utm_params(
    url: str,
    source: str,
    medium: str,
    campaign: str,
    content: str,
    **extra: Any,
) -> str:
    """
    Alias wrapper matching PROJECT.md interface contract.
    """
    return build_utm_url(
        base_url=url,
        utm_source=source,
        utm_medium=medium,
        utm_campaign=campaign,
        utm_content=content,
        **extra,
    )


# Alias for E2E suite compatibility
build_tracked_url = build_utm_url
