from datetime import datetime, timezone, timedelta
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, StrictBool, field_validator, model_validator

CONSENT_VERSION = "journey-2026-10-v1"
STEPS = (
    "landing",
    "configurator",
    "configuration",
    "quote",
    "cart",
    "pdf_quote",
    "checkout",
    "paid_order",
)
CATEGORIES = (
    "none",
    "invalid_input",
    "unsupported",
    "api_failure",
    "system_restriction",
    "technical_failure",
)


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    consent_version: Literal["journey-2026-10-v1"]
    internal: StrictBool = False


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    event_id: UUID
    timestamp: datetime
    step: Literal[
        "landing",
        "configurator",
        "configuration",
        "quote",
        "analyzer",
        "cart",
        "pdf_quote",
        "checkout",
    ]
    outcome: Literal["reached", "success", "attempted", "blocked", "error"]
    category: Literal[
        "none",
        "invalid_input",
        "unsupported",
        "api_failure",
        "system_restriction",
        "technical_failure",
    ]
    source: Literal["landing", "direct", "embed"]

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Invalid schema version")
        return value

    @field_validator("timestamp")
    @classmethod
    def recent(cls, value):
        now = datetime.now(timezone.utc)
        if value.tzinfo is None or not now - timedelta(
            minutes=5
        ) <= value <= now + timedelta(minutes=1):
            raise ValueError("Timestamp outside collection window")
        return value

    @model_validator(mode="after")
    def combination(self):
        if (self.outcome in ("error", "blocked")) != (self.category != "none"):
            raise ValueError("Invalid outcome/category")
        if self.category == "system_restriction" and self.outcome != "blocked":
            raise ValueError("Restriction must be blocked")
        if self.outcome == "attempted" and self.step not in ("analyzer", "checkout"):
            raise ValueError("Invalid attempted step")
        if self.source == "landing" and self.step not in ("landing", "configurator"):
            raise ValueError("Invalid landing step")
        return self


class ServerEvent(Event):
    source: Literal["backend"] = "backend"
