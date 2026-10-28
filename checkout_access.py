"""Fail-closed UI readiness; API checkout creation remains authoritative."""
import requests


def checkout_access(api_base, headers, *, owner_test_allowed=False, owner_acceptance=False):
    try:
        response = requests.get(f"{api_base}/checkout/availability", headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("available") is True and data.get("mode") in {"live", "owner_test", "test"}:
                return {"available": True, "mode": data["mode"]}
    except (requests.RequestException, ValueError, TypeError):
        pass
    return {"available": False, "mode": None}
