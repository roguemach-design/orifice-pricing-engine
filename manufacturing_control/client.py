"""Read-only owner client. No workflow mutation methods or global data caches."""

from hashlib import sha256
import requests


class PortalError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


ERRORS = {
    "authorization": "Owner authorization was not accepted. Lock and unlock with the current credential.",
    "missing": "Record unavailable. Your order and revision selection is kept.",
    "conflict": "This request is unavailable or the revision is no longer current. Refresh the record before trying again.",
    "integrity": "File integrity check failed. Download blocked. No records were changed.",
    "rate": "Too many requests right now. Wait 30 seconds, then try again. Your selection is kept.",
    "service": "The order service is unavailable. Your selection is kept; no records were changed.",
    "name": "The authoritative DXF delivery name is unavailable. Download blocked.",
}


class OwnerClient:
    def __init__(self, base, credential):
        self.base, self.credential = base.rstrip("/"), credential

    def get(self, path, **kwargs):
        if not self.credential:
            raise PortalError("authorization")
        if not path.startswith("/admin/") or "://" in path or ".." in path:
            raise PortalError("missing")
        try:
            response = requests.get(
                self.base + path,
                headers={"x-api-key": self.credential},
                timeout=(10, 90),
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException:
            raise PortalError("service") from None
        if response.status_code != 200:
            raise PortalError(
                {
                    401: "authorization",
                    403: "authorization",
                    404: "missing",
                    409: "conflict",
                    429: "rate",
                }.get(response.status_code, "service")
            )
        return response

    def json(self, path, **kwargs):
        try:
            return self.get(path, **kwargs).json()
        except (ValueError, KeyError, TypeError):
            raise PortalError("service") from None

    def artifact(self, revision, kind, filename):
        rid = revision["id"]
        path = f"/admin/frozen-plates/revisions/{rid}/" + (
            "dxf" if kind == "dxf" else f"artifact/{kind}"
        )
        response = self.get(path)
        artifact = revision["artifacts"][kind]
        if (
            sha256(response.content).hexdigest() != artifact["sha256"]
            or len(response.content) != artifact["size"]
        ):
            raise PortalError("integrity")
        if (
            kind == "dxf"
            and response.headers.get("Content-Disposition")
            != f'attachment; filename="{filename}"'
        ):
            raise PortalError("name")
        return response.content


def clear_owner_session(state):
    for key in list(state):
        if str(key).startswith("mc_") or key == "owner_admin_credential":
            del state[key]
