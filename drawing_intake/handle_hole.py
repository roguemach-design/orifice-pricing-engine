"""Evidence-bound handle-hole proposals; no manufacturing authorization."""

import re

from .models import BooleanField, NumericField, FieldStatus, SourceEvidence
from .value_normalization import normalize_unit, parse_number

_NAMES = (
    "handle_hole_enabled",
    "handle_hole_diameter",
    "handle_hole_center_from_handle_end",
)
_NUMBER = r"(?:\d+\s+\d+/\d+|\d+/\d+|(?:\d+(?:\.\d*)?|\.\d+))"
_PATTERNS = {
    "handle_hole_diameter": [
        rf"\bHANDLE\s+HOLE(?:\s+(?:DIAMETER|DIA))?\s*[:=]?\s*[Ø⌀]?\s*(?P<value>{_NUMBER})",
        rf"[Ø⌀]\s*(?P<value>{_NUMBER})\s*(?:IN|MM|\")?\s+HANDLE\s+HOLE",
    ],
    "handle_hole_center_from_handle_end": [
        rf"\bHANDLE\s+END\s+TO\s+(?:HANDLE\s+)?HOLE\s+(?:C/L|CENTER(?:LINE)?)\s*[:=]?\s*(?P<value>{_NUMBER})",
        rf"(?P<value>{_NUMBER})\s*(?:IN|MM|\")?\s+(?:FROM\s+)?HANDLE\s+END\s+TO\s+(?:HANDLE\s+)?HOLE\s+(?:C/L|CENTER(?:LINE)?)",
    ],
}


def propose_handle_hole(observations, default_unit=None):
    """observations are (text, SourceEvidence), scoped to the selected part."""
    fields = {name: NumericField() for name in _NAMES[1:]}
    all_sources = []
    for name, patterns in _PATTERNS.items():
        matches = []
        for raw, source in observations:
            for pattern in patterns:
                for match in re.finditer(pattern, raw, re.I):
                    try:
                        value = parse_number(match.group("value"))
                    except (ValueError, ZeroDivisionError):
                        continue
                    # Explicit local units outrank global units; unknown units abstain.
                    suffix = raw[match.end("value") :].strip()
                    local = re.match(r'^(MM|IN(?:CH(?:ES)?)?|")', suffix, re.I)
                    unit = normalize_unit(local.group(1)) if local else default_unit
                    matches.append((value, unit, raw, source))
        if not matches:
            continue
        unique = {(value, unit) for value, unit, _, _ in matches}
        conflicting = len(unique) != 1
        value, unit, raw, _ = matches[0]
        sources = [item[3] for item in matches]
        all_sources.extend(sources)
        fields[name] = NumericField(
            value=None if conflicting else value,
            normalized_unit=unit,
            raw_text=raw,
            confidence=0.9 if unit else 0.5,
            status=(
                FieldStatus.AMBIGUOUS
                if conflicting
                else (FieldStatus.DETECTED if unit else FieldStatus.LOW_CONFIDENCE)
            ),
            evidence=sources,
            warnings=[
                "Handle-hole proposal requires user review and canonical geometry validation."
            ],
        )
    fields[_NAMES[0]] = (
        BooleanField(
            value=True,
            confidence=0.9,
            status=FieldStatus.DETECTED,
            raw_text=all_sources[0].raw_text,
            evidence=all_sources,
            warnings=[
                "Presence inferred only from explicitly labeled handle-hole evidence."
            ],
        )
        if all_sources
        else BooleanField()
    )
    return fields


def native_handle_hole(document, default_unit=None):
    return propose_handle_hole(
        [
            (
                block.text,
                SourceEvidence(
                    page_number=page.page_number,
                    raw_text=block.text,
                    bbox=block.bbox,
                    coordinate_unit="pdf_point",
                    extraction_method="native_labeled_handle_hole_v1",
                ),
            )
            for page in document.pages
            for block in page.text_blocks
        ],
        default_unit,
    )
