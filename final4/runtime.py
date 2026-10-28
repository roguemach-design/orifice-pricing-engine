"""Opt-in production/staging service, using existing authorization and PG storage."""

from functools import lru_cache
import json
import os
from pathlib import Path
from dataclasses import asdict
from haas_generator.contract import construct, MachineProfile
from haas_generator.engineering import Parameters
from packaging_generator.generator import Configuration
from frozen_plate.api import repository
from frozen_plate.repository import WorkflowError
from .service import DerivedService
from .postgres import verify_repository

ROOT = Path(__file__).resolve().parents[1]


def enabled():
    return os.environ.get("FINAL4_ENABLED") == "true"


def read_config(variable, fallback):
    path = Path(os.environ.get(variable) or ROOT / fallback)
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def service():
    if not enabled():
        raise WorkflowError("derived manufacturing integration disabled")
    repo = repository()
    verify_repository(repo)
    # Bundled configurations are explicitly SYNTHETIC review/prototype profiles.
    # They cannot qualify physical manufacturing or shipping.
    return DerivedService(
        repo,
        machine_profile=construct(
            MachineProfile,
            read_config("FINAL4_MACHINE_PROFILE_PATH", "examples/haas/profile.json"),
        ),
        packaging_config=Configuration(
            **read_config(
                "FINAL4_PACKAGING_CONFIG_PATH", "examples/final4/packaging-config.json"
            )
        ),
        machining_parameters=Parameters(
            **read_config(
                "FINAL4_PARAMETERS_PATH", "examples/final4/machining-parameters.json"
            )
        ),
    )


def configuration():
    from .worker import automatic_enabled

    s = service()
    return dict(
        adapter="postgresql",
        schema=verify_repository(s.repo),
        machine_profile=asdict(s.profile),
        packaging_configuration=asdict(s.packaging_config),
        machining_parameters=asdict(s.parameters),
        manufacturing_release_enabled=False,
        haas_status="SETUP VERIFICATION REQUIRED",
        automatic_staging=automatic_enabled(),
        staging_profiles=automatic().profiles(),
        fixture_profile=asdict(automatic().fixture),
        packaging_status="PROTOTYPE",
    )


@lru_cache(maxsize=1)
def automatic():
    from .automatic import AutomaticStager
    from haas_generator.staging import FixtureProfile

    return AutomaticStager(
        service(),
        FixtureProfile(
            **read_config(
                "FINAL4_FIXTURE_PROFILE_PATH", "examples/final4/fixture-profile.json"
            )
        ),
    )


@lru_cache(maxsize=1)
def worker():
    from .worker import StagingWorker

    return StagingWorker(automatic)


def test_engineering():
    from .test_engineering import TestEngineering

    return TestEngineering(automatic())
