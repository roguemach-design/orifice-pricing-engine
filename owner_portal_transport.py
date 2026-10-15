"""Owner transport: verified reads and the single organizational archive action."""

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

    def archive(self, order_id, archived):
        from urllib.parse import quote

        if not self.credential or type(archived) is not bool:
            raise PortalError("authorization")
        try:
            response = requests.put(
                self.base + "/admin/orders/" + quote(order_id, safe="") + "/archive",
                headers={"x-api-key": self.credential},
                json={"archived": archived},
                timeout=(10, 30),
                allow_redirects=False,
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
        try:
            return response.json()
        except ValueError:
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

    def manufacturing_post(self, path, body):
        if path not in (
            "/admin/manufacturing/bundles",
            "/admin/manufacturing/bundles/query",
        ):
            raise PortalError("missing")
        if not self.credential:
            raise PortalError("authorization")
        try:
            response = requests.post(
                self.base + path,
                json=body,
                headers={"x-api-key": self.credential},
                timeout=(10, 120),
                allow_redirects=False,
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
        try:
            return response.json()
        except ValueError:
            raise PortalError("service") from None

    def derived_artifact(self, bundle_id, artifact):
        from urllib.parse import quote

        response = self.get(
            "/admin/manufacturing/bundles/"
            + quote(bundle_id, safe="")
            + "/files/"
            + quote(artifact["name"], safe="")
        )
        if (
            len(response.content) != artifact["size"]
            or sha256(response.content).hexdigest() != artifact["sha256"]
            or response.headers.get("X-Artifact-SHA256") != artifact["sha256"]
            or response.headers.get("Content-Disposition")
            != f'attachment; filename="{artifact["filename"]}"'
        ):
            raise PortalError("integrity")
        return response.content


def clear_owner_session(state):
    access = state.get("mc_download_access")
    if access is not None:
        access.revoke()
    for key in list(state):
        if str(key).startswith("mc_") or key == "owner_admin_credential":
            del state[key]


class DownloadAccess:
    """Session-local revocable access for Streamlit's deferred worker thread."""

    def __init__(self, client):
        from threading import Lock

        self._client = client
        self._active = True
        self._lock = Lock()

    def revoke(self):
        with self._lock:
            self._active = False
            self._client = None

    def load(self, revision, kind, filename):
        # No Streamlit commands and no shared data cache in a deferred callback.
        with self._lock:
            client = self._client if self._active else None
        if client is None:
            raise RuntimeError("Download blocked: owner session is locked.")
        try:
            content = client.artifact(revision, kind, filename)
        except PortalError as error:
            raise RuntimeError("Download blocked: " + ERRORS[error.category]) from None
        with self._lock:
            if not self._active:
                raise RuntimeError("Download blocked: owner session is locked.")
        return content

    def load_derived(self, bundle_id, artifact):
        with self._lock:
            client = self._client if self._active else None
        if client is None:
            raise RuntimeError("Download blocked: owner session is locked.")
        try:
            content = client.derived_artifact(bundle_id, artifact)
        except PortalError as error:
            raise RuntimeError("Download blocked: " + ERRORS[error.category]) from None
        with self._lock:
            if not self._active:
                raise RuntimeError("Download blocked: owner session is locked.")
        return content


def download_callable(access, revision, kind, filename):
    from copy import deepcopy
    from functools import partial

    # Bind the exact selected immutable revision; reruns must not retarget it.
    return partial(access.load, deepcopy(revision), kind, filename)
