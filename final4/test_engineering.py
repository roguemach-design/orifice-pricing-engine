"""Explicit owner TEST derivatives. No automatic staging, sourcing or release path."""

import json
from frozen_plate.repository import WorkflowError, canonical, digest
from haas_generator.staging import generate as haas
from packaging_generator.generator import generate as packaging

MODE = "OWNER_TEST_ENGINEERING"
VERSION = "owner-test-engineering-1"


class TestEngineering:
    __test__ = False

    def __init__(self, stager):
        self.stager = stager
        self.service = stager.service

    def ensure(self, family, association, *, actor):
        if family not in ("HAAS", "PACKAGING") or not actor:
            raise WorkflowError("valid family/server owner actor required")
        s, repo = self.service, self.service.repo
        signature = self.stager.profiles()[family]
        key = digest(canonical(dict(mode=MODE, version=VERSION,
                                    parent=association, profile=signature)))
        # Same serialized transaction as approval/supersession and bundle writes.
        with repo.transaction() as db:
            r, spec, current, approved = s._parent(db, association, require_current=False)
            if json.loads(r["source_json"]).get("_payment", {}).get("mode") != "owner_test":
                raise WorkflowError("TEST provenance required")
            if not current or not approved:
                raise WorkflowError("current customer-approved exact TEST revision required")
            for b in db.execute(
                "SELECT id,manifest_json,manifest_sha256 FROM manufacturing_bundles WHERE revision_id=? AND family=? ORDER BY created_at,id",
                (association["revision_id"], family),
            ):
                if digest(b["manifest_json"]) != b["manifest_sha256"]:
                    raise WorkflowError("stored engineering manifest integrity failure")
                manifest = json.loads(b["manifest_json"])
                if manifest.get("mode") == MODE and manifest.get("staging_key") == key:
                    return b["id"]
            parent = {**association, "revision": f"R{r['number']}"}
            if family == "HAAS":
                files = haas(spec, s.profile, self.stager.fixture, s.parameters, parent)
                warning = "NOT MACHINE-PROVEN / REVIEW REQUIRED"
                files["program.NC"] = files["program.NC"].replace(
                    b"(REVIEW / SETUP VERIFICATION REQUIRED)",
                    b"(TEST / NOT A REAL SALE - NOT MACHINE-PROVEN / REVIEW REQUIRED)\n(REVIEW / SETUP VERIFICATION REQUIRED)", 1)
            else:
                files = packaging(spec, s.packaging_config, parent)
                warning = "PROTOTYPE / NOT QUALIFIED FOR SHIPPING"
                # DXF comment only: no cutting geometry, TEXT or MTEXT changes.
                files["packaging.dxf"] = (
                    b"999\nTEST / NOT A REAL SALE - PROTOTYPE / NOT QUALIFIED FOR SHIPPING\n"
                    + files["packaging.dxf"])
            inputs = json.loads(files["inputs.json"])
            provenance = dict(mode=MODE, version=VERSION, payment_mode="owner_test",
                              warning=warning, parent=parent, generated_by=actor,
                              manufacturing_release_enabled=False, release_eligible=False)
            files["test-engineering.json"] = (canonical(provenance) + "\n").encode("ascii")
            files["TEST-ENGINEERING.md"] = (
                "# TEST / NOT A REAL SALE\n\n" + warning
                + "\n\nEngineering review only. No manufacturing, sourcing, dispatch or shipping authorization.\n"
            ).encode("ascii")
            manifest = json.loads(files["manifest.json"])
            manifest["files"] = {name: dict(size=len(raw), sha256=digest(raw))
                                 for name, raw in files.items() if name != "manifest.json"}
            files["manifest.json"] = (canonical(manifest) + "\n").encode("ascii")
            return s._store(db, family, association, r, files, inputs, actor,
                            staging=dict(mode=MODE, profile_sha256=signature,
                                         staging_key=key, payment_mode="owner_test",
                                         warning=warning, release_eligible=False,
                                         input_source="APPROVED TEST FROZEN PLATE + CONTROLLED PROFILES"))
