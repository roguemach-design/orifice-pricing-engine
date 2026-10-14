"""Reuse the server-verified internal drawing gate across owner-test pages."""

from collections.abc import Mapping

import requests


def verified_owner_access(
    api_base: str,
    *,
    enabled: bool,
    user_id_hint: str | None,
    headers: Mapping[str, str],
    access_path: str = "/internal/drawing-intake/access",
) -> bool:
    if not enabled or not user_id_hint:
        return False
    try:
        response = requests.get(
            f"{api_base}{access_path}",
            headers=dict(headers),
            timeout=5,
        )
        if response.status_code != 200:
            return False
        body = response.json()
        return bool(
            body.get("enabled")
            and body.get("authorized")
            and body.get("user_id") == user_id_hint
        )
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return False
