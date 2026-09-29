"""Run `python -m frozen_plate.demo`; optionally `--serve` after creating fixtures.

Creates only local test data. Refuses to overwrite an existing private repository.
No environment/provider credentials are loaded, and no outbound client is used.
"""

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import secrets

from fastapi.testclient import TestClient
from prototype_manufacturing import sample_spec
from .repository import Repository, ROUTES, WorkflowError, canonical, digest
from .presentation import email_html, message_html
from .web import create_app, ORIGIN


def write_private(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")
    path.chmod(0o600)


def run_demo(root, output):
    if root.exists():
        raise ValueError("private demo directory exists; choose a fresh --root")
    root.mkdir(parents=True, mode=0o700)
    keys = {
        name: secrets.token_urlsafe(48) for name in ("approval", "session", "admin")
    }
    write_private(root / "keys.json", keys)
    repo = Repository(root, keys["approval"])
    app = create_app(repo, session_key=keys["session"], admin_key=keys["admin"])
    customer = "prototype-customer"
    plate = repo.create_plate(
        order_id="OP-PROTOTYPE-001",
        line_id="L1",
        configuration_id="PROTOTYPE-CONFIG-001",
        customer_id=customer,
        actor="prototype-admin",
    )
    spec = replace(sample_spec(), part_identifier="PROTOTYPE-001")
    r1 = repo.create_revision(
        plate,
        spec,
        expected_current=None,
        reason="Phase 4 accepted sample",
        actor="prototype-admin",
        source_snapshot={"fixture": "OP-PROTOTYPE-001", "configuration": asdict(spec)},
    )
    d1 = repo.create_delivery(r1["id"])
    (root / "R1-email.eml").write_bytes(d1["mime"])
    (root / "R1-email.eml").chmod(0o600)
    cookie, csrf = app.state.local_sessions.issue(customer)
    client = TestClient(app, base_url=ORIGIN)
    client.cookies.set("fp_local_session", cookie)
    output.mkdir(parents=True, exist_ok=True)
    # Reviewable, inert exports omit bearer tokens/session material. The actual
    # interactive preview remains protected inside the loopback application.
    inert = email_html(d1["context"], "#", csrf="REVIEW-ONLY")
    inert = inert.replace('action="#"', 'action="#" onsubmit="return false"').replace(
        'type="submit"', 'type="button"'
    )
    (output / "customer-email-preview.html").write_text(inert)
    before = client.get("/approve/" + d1["token"])
    assert before.status_code == 200
    with repo.connect() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM frozen_plate_approvals").fetchone()[0] == 0
        )
    response = client.post(
        "/approve/" + d1["token"], data={"csrf": csrf}, headers={"Origin": ORIGIN}
    )
    assert (
        response.status_code == 200 and "YOUR ORDER IS IN PRODUCTION" in response.text
    )
    (output / "customer-success.html").write_text(response.text)
    routes = []
    for route in ROUTES:
        result = client.post(
            f'/internal/revisions/{r1["id"]}/source',
            json={"route": route},
            headers={"x-api-key": keys["admin"]},
        )
        assert result.status_code == 200
        routes.append(result.json())
    internal = client.get(
        f'/internal/revisions/{r1["id"]}/source', headers={"x-api-key": keys["admin"]}
    )
    (output / "internal-sourcing-preview.html").write_text(
        internal.text.replace('type="submit"', 'type="button"')
    )
    approved = repo.inspect_token(d1["token"], customer)["approval"]
    spec2 = replace(spec, quantity=2)
    r2 = repo.create_revision(
        plate,
        spec2,
        expected_current=r1["id"],
        reason="Illustrative customer change: quantity 1 to 2",
        actor="prototype-admin",
        source_snapshot={"fixture": "OP-PROTOTYPE-001", "configuration": asdict(spec2)},
    )
    d2 = repo.create_delivery(r2["id"])
    (root / "R2-email.eml").write_bytes(d2["mime"])
    (root / "R2-email.eml").chmod(0o600)
    old = repo.approve(d1["token"], customer)
    assert old["approval"] == approved and old["historical"]
    assert repo.inspect_token(d2["token"], customer)["state"] == "pending"
    try:
        repo.select_source(r1["id"], "ALRO", actor="prototype-admin")
        raise AssertionError("old sourcing unexpectedly allowed")
    except WorkflowError:
        pass
    assert repo.revision(r1["id"]) == r1
    for revision in (r1, r2):
        for artifact in revision["artifacts"].values():
            (output / artifact["filename"]).write_bytes(
                (repo.objects / artifact["object_key"]).read_bytes()
            )
    (output / "superseded-link.html").write_text(message_html("superseded"))
    manifest = {
        "prototype_only": True,
        "plate": repo.plate(plate),
        "revisions": [r1, r2],
        "r1_approval": approved,
        "sourcing_options": routes,
        "checks": {
            "passive_get_no_approval": True,
            "one_post_exact_r1_approval": True,
            "r1_immutable_after_r2": True,
            "r1_revisit_cannot_approve_r2": True,
            "r1_sourcing_blocked_after_r2": True,
            "r2_requires_independent_approval": True,
            "dxf_identical_for_quantity_only_change": r1["artifacts"]["dxf"]["sha256"]
            == r2["artifacts"]["dxf"]["sha256"],
            "no_email_or_vendor_submission": True,
        },
    }
    (output / "acceptance-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    # Available only to the local browser harness; never export/commit these.
    write_private(
        root / "browser-fixture.json",
        {
            "cookie": cookie,
            "csrf": csrf,
            "customer_id": customer,
            "r2_token": d2["token"],
            "r2_id": r2["id"],
            "plate_id": plate,
        },
    )
    print(
        "Local E2E passed: R1 approved, three route options recorded; R2 independently pending."
    )
    print("Review artifacts: " + str(output.resolve()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".frozen-plate-local"))
    parser.add_argument("--output", type=Path, default=Path("prototype_output/phase4"))
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if args.serve:
        import uvicorn

        keys = json.loads((args.root / "keys.json").read_text())
        repo = Repository(args.root, keys["approval"])
        app = create_app(repo, session_key=keys["session"], admin_key=keys["admin"])
        # No token-bearing access logs. No external bind or auto-login endpoint.
        uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)
    else:
        run_demo(args.root, args.output)


if __name__ == "__main__":
    main()
