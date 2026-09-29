"""Scope/state labels only; no metering calculator or release workflow."""

from enum import StrEnum


class PlateApplication(StrEnum):
    RESTRICTION_GENERAL = "restriction-general"
    METERING = "metering"


class DrawingState(StrEnum):
    PROTOTYPE = "prototype"
    CUSTOMER_CONFIRMATION = "customer-confirmation"
    RELEASED = "released-for-manufacture"


STATUS_LABELS = {
    DrawingState.PROTOTYPE: "PROTOTYPE - NOT RELEASED FOR MANUFACTURE",
    DrawingState.CUSTOMER_CONFIRMATION: "CUSTOMER CONFIRMATION - NOT RELEASED FOR MANUFACTURE",
    DrawingState.RELEASED: "RELEASED FOR MANUFACTURE",
}


def application_context(application):
    application = PlateApplication(application)
    return {
        "application": application.value,
        "active_metering_rule_sets": [],
        "metering_validation": (
            "NOT IMPLEMENTED"
            if application == PlateApplication.METERING
            else "NOT APPLICABLE"
        ),
    }
