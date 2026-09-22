from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .documents import NormalizedDocument, TextBlock
from .models import (
    BooleanField,
    DocumentReference,
    DrawingExtractionResult,
    DrawingFields,
    FieldStatus,
    IntegerField,
    MeasurementUnit,
    NumericField,
    ProviderDataHandling,
    SourceEvidence,
    StringField,
    UnitField,
)
from .value_normalization import normalize_material, normalize_unit, parse_number


class ExtractionProviderError(RuntimeError):
    pass


class ExtractionProvider(ABC):
    name: str
    data_handling: ProviderDataHandling

    @abstractmethod
    def extract_drawing(self, document: NormalizedDocument) -> DrawingExtractionResult:
        raise NotImplementedError


def _document_reference(document: NormalizedDocument) -> DocumentReference:
    return DocumentReference(
        filename=document.filename,
        media_type=document.media_type,
        sha256=document.sha256,
        page_count=len(document.pages),
    )


StructuredCompletion = Callable[[str, dict[str, Any], NormalizedDocument], str]


def build_fixed_schema_prompt(document: NormalizedDocument) -> str:
    text_layer = "\n\n".join(
        f"PAGE {page.page_number}\n{page.text}" for page in document.pages if page.text
    )
    return f"""You extract requirements from a drawing of one O-Plate/orifice plate.
Return only JSON matching the supplied schema. Search only for the fixed schema.
Do not invent dimensions, material, quantity, tolerances, chamfers, or metadata.
Use not_detected when information is absent, ambiguous when multiple readings conflict,
and unreadable when the source cannot be read. Preserve field-specific confidence,
raw text, page number, and source bounding boxes when available.
The result is a candidate extraction only. It is not pricing and must not contain price.

Native PDF text, when available:
{text_layer or "[no native text layer; use the supplied page image(s)]"}
"""


class StructuredModelExtractionProvider(ExtractionProvider):
    """Vendor-neutral adapter around any strict JSON completion implementation."""

    def __init__(
        self,
        *,
        provider_name: str,
        completion: StructuredCompletion,
        data_handling: ProviderDataHandling,
    ) -> None:
        self.name = provider_name
        self._completion = completion
        self.data_handling = data_handling

    def extract_drawing(self, document: NormalizedDocument) -> DrawingExtractionResult:
        prompt = build_fixed_schema_prompt(document)
        try:
            raw = self._completion(prompt, DrawingFields.model_json_schema(), document)
            payload = json.loads(raw)
            fields_payload = (
                payload.get("fields", payload) if isinstance(payload, dict) else payload
            )
            if not isinstance(fields_payload, dict) or set(fields_payload) != set(
                DrawingFields.model_fields
            ):
                raise ValueError("provider must return every drawing field")
            fields = DrawingFields.model_validate(fields_payload)
        except (
            json.JSONDecodeError,
            ValidationError,
            TypeError,
            AttributeError,
            ValueError,
        ) as exc:
            raise ExtractionProviderError(
                "provider output failed strict schema validation"
            ) from exc
        return DrawingExtractionResult(
            document=_document_reference(document),
            provider_name=self.name,
            provider_data_handling=self.data_handling,
            fields=fields,
        )


class NativeTextExtractionProvider(ExtractionProvider):
    """Low-cost first pass for clearly labeled, digitally generated PDFs."""

    name = "native_pdf_text_v1"
    data_handling = ProviderDataHandling(
        external_service=False,
        retention="in_memory_only",
        sends_document_content=False,
    )
    _number = r"(?:\d+\s+\d+/\d+|\d+/\d+|(?:\d+(?:\.\d*)?|\.\d+))"
    _unit = r"(?:IN(?:CH(?:ES)?)?|MM|\")"

    def extract_drawing(self, document: NormalizedDocument) -> DrawingExtractionResult:
        if not document.has_text_layer:
            fields = DrawingFields()
            return DrawingExtractionResult(
                document=_document_reference(document),
                provider_name=self.name,
                provider_data_handling=self.data_handling,
                fields=fields,
                document_warnings=[
                    "No native text layer; OCR or vision provider required."
                ],
            )

        units = self._extract_global_units(document)
        default_unit = MeasurementUnit(units.value) if units.value else None
        fields = DrawingFields(
            outside_diameter=self._numeric(
                document,
                [
                    rf"\b(?:PLATE\s+)?(?:OUTSIDE\s+DIAMETER|O\.?D\.?)\s*[:=]?\s*(?:[Ø⌀]\s*)?(?P<value>{self._number})\s*(?P<unit>{self._unit})?"
                ],
                default_unit,
            ),
            bore_diameter=self._numeric(
                document,
                [
                    rf"\b(?:BORE|ORIFICE)(?:\s+DIAMETER)?\s*[:=]?\s*(?:[Ø⌀]\s*)?(?P<value>{self._number})\s*(?P<unit>{self._unit})?"
                ],
                default_unit,
            ),
            thickness=self._numeric(
                document,
                [
                    rf"\b(?:PLATE\s+)?THICKNESS\s*[:=]?\s*(?P<value>{self._number})\s*(?P<unit>{self._unit})?"
                ],
                default_unit,
            ),
            material=self._string(
                document,
                [r"\bMATERIAL\s*[:=]\s*(?P<value>[^;|]+)$"],
                normalizer=normalize_material,
            ),
            quantity=self._integer(
                document,
                [r"\b(?:QUANTITY|QTY)\s*[:=]\s*(?P<value>\d+)\b"],
            ),
            global_units=units,
            general_dimensional_tolerance=self._numeric(
                document,
                [
                    rf"\bGENERAL\s+(?:DIMENSIONAL\s+)?TOLERANCE\s*[:=]?\s*(?:±|\+/-)\s*(?P<value>{self._number})\s*(?P<unit>{self._unit})?"
                ],
                default_unit,
            ),
            marking_text=self._string(
                document, [r"\b(?:MARKING|HANDLE\s+MARKING)\s*[:=]\s*(?P<value>.+)$"]
            ),
            customer_part_number=self._string(
                document,
                [r"\b(?:CUSTOMER\s+)?PART\s+(?:NUMBER|NO\.?)\s*[:=]\s*(?P<value>.+)$"],
            ),
            drawing_number=self._string(
                document,
                [r"\bDRAWING\s+(?:NUMBER|NO\.?)\s*[:=]\s*(?P<value>.+)$"],
            ),
            revision=self._string(
                document, [r"\b(?:REVISION|REV\.?)\s*[:=]\s*(?P<value>[A-Z0-9.-]+)\b"]
            ),
        )
        fields.bore_tolerance_plus, fields.bore_tolerance_minus = self._tolerance(
            document, default_unit
        )
        (
            fields.chamfer_present,
            fields.chamfer_width,
            fields.chamfer_depth,
            fields.chamfer_angle,
        ) = self._chamfer(document, default_unit)
        return DrawingExtractionResult(
            document=_document_reference(document),
            provider_name=self.name,
            provider_data_handling=self.data_handling,
            fields=fields,
        )

    @staticmethod
    def _iter_blocks(document: NormalizedDocument):
        for page in document.pages:
            for block in page.text_blocks:
                yield page.page_number, block

    def _matches(self, document: NormalizedDocument, patterns: list[str]):
        found = []
        for page_number, block in self._iter_blocks(document):
            for pattern in patterns:
                match = re.search(pattern, block.text, flags=re.IGNORECASE)
                if match:
                    found.append((page_number, block, match))
                    break
        return found

    def _evidence(self, page_number: int, block: TextBlock) -> SourceEvidence:
        return SourceEvidence(
            page_number=page_number,
            raw_text=block.text,
            bbox=block.bbox,
            coordinate_unit=block.coordinate_unit,
            extraction_method=self.name,
        )

    def _extract_global_units(self, document: NormalizedDocument) -> UnitField:
        matches = self._matches(
            document,
            [
                r"\b(?:GLOBAL\s+)?UNITS\s*[:=]\s*(?P<value>IN(?:CH(?:ES)?)?|MM)\b",
                r"\bALL\s+DIMENSIONS\s+(?:ARE\s+)?IN\s+(?P<value>INCHES|MM)\b",
            ],
        )
        values = []
        for page_number, block, match in matches:
            unit = normalize_unit(match.group("value"))
            if unit in {MeasurementUnit.INCH, MeasurementUnit.MILLIMETER}:
                values.append((unit.value, page_number, block))
        if not values:
            return UnitField()
        distinct = {value for value, _, _ in values}
        evidence = [self._evidence(page, block) for _, page, block in values]
        if len(distinct) > 1:
            return UnitField(
                status=FieldStatus.AMBIGUOUS,
                confidence=0.4,
                raw_text=" | ".join(item.raw_text or "" for item in evidence),
                evidence=evidence,
                warnings=["Conflicting global units were detected."],
            )
        value = values[0][0]
        return UnitField(
            value=value,
            normalized_unit=MeasurementUnit(value),
            raw_text=evidence[0].raw_text,
            confidence=0.99,
            status=FieldStatus.DETECTED,
            evidence=evidence,
        )

    def _numeric(
        self,
        document: NormalizedDocument,
        patterns: list[str],
        default_unit: MeasurementUnit | None,
    ) -> NumericField:
        parsed = []
        for page_number, block, match in self._matches(document, patterns):
            try:
                value = parse_number(match.group("value"))
            except (ValueError, ZeroDivisionError):
                continue
            unit = normalize_unit(match.groupdict().get("unit")) or default_unit
            parsed.append((value, unit, page_number, block))
        if not parsed:
            return NumericField()
        distinct = {
            (round(value, 12), unit.value if unit else None)
            for value, unit, _, _ in parsed
        }
        evidence = [self._evidence(page, block) for _, _, page, block in parsed]
        if len(distinct) > 1:
            return NumericField(
                status=FieldStatus.AMBIGUOUS,
                confidence=0.4,
                raw_text=" | ".join(item.raw_text or "" for item in evidence),
                evidence=evidence,
                warnings=["Multiple conflicting values were detected."],
            )
        value, unit, _, _ = parsed[0]
        return NumericField(
            value=value,
            normalized_unit=unit,
            raw_text=evidence[0].raw_text,
            confidence=0.99,
            status=FieldStatus.DETECTED,
            evidence=evidence,
        )

    def _integer(
        self, document: NormalizedDocument, patterns: list[str]
    ) -> IntegerField:
        matches = self._matches(document, patterns)
        if not matches:
            return IntegerField()
        parsed = [
            (int(match.group("value")), page, block) for page, block, match in matches
        ]
        evidence = [self._evidence(page, block) for _, page, block in parsed]
        distinct = {value for value, _, _ in parsed}
        if len(distinct) > 1:
            return IntegerField(
                status=FieldStatus.AMBIGUOUS,
                confidence=0.4,
                raw_text=" | ".join(item.raw_text or "" for item in evidence),
                evidence=evidence,
            )
        return IntegerField(
            value=parsed[0][0],
            normalized_unit=MeasurementUnit.COUNT,
            raw_text=evidence[0].raw_text,
            confidence=0.99,
            status=FieldStatus.DETECTED,
            evidence=evidence,
        )

    def _string(
        self,
        document: NormalizedDocument,
        patterns: list[str],
        normalizer: Callable[[str], str] | None = None,
    ) -> StringField:
        matches = self._matches(document, patterns)
        if not matches:
            return StringField()
        parsed = []
        for page, block, match in matches:
            raw_value = match.group("value").strip()
            parsed.append(
                ((normalizer or (lambda value: value))(raw_value), page, block)
            )
        evidence = [self._evidence(page, block) for _, page, block in parsed]
        distinct = {value for value, _, _ in parsed}
        if len(distinct) > 1:
            return StringField(
                status=FieldStatus.AMBIGUOUS,
                confidence=0.4,
                raw_text=" | ".join(item.raw_text or "" for item in evidence),
                evidence=evidence,
            )
        return StringField(
            value=parsed[0][0],
            raw_text=evidence[0].raw_text,
            confidence=0.99,
            status=FieldStatus.DETECTED,
            evidence=evidence,
        )

    def _tolerance(
        self,
        document: NormalizedDocument,
        default_unit: MeasurementUnit | None,
    ) -> tuple[NumericField, NumericField]:
        asymmetric = self._matches(
            document,
            [
                rf"\bBORE\s+TOLERANCE\s*[:=]?\s*\+(?P<plus>{self._number})\s*(?:/|,)?\s*-(?P<minus>{self._number})\s*(?P<unit>{self._unit})?"
            ],
        )
        if asymmetric:
            values = []
            for page, block, match in asymmetric:
                unit = normalize_unit(match.groupdict().get("unit")) or default_unit
                values.append(
                    (
                        parse_number(match.group("plus")),
                        parse_number(match.group("minus")),
                        unit,
                        page,
                        block,
                    )
                )
            distinct = {
                (round(plus, 12), round(minus, 12), unit.value if unit else None)
                for plus, minus, unit, _, _ in values
            }
            evidence = [self._evidence(page, block) for _, _, _, page, block in values]
            if len(distinct) > 1:
                ambiguous = NumericField(
                    status=FieldStatus.AMBIGUOUS,
                    confidence=0.4,
                    raw_text=" | ".join(item.raw_text or "" for item in evidence),
                    evidence=evidence,
                )
                return ambiguous, ambiguous.model_copy(deep=True)
            plus, minus, unit, _, _ = values[0]
            common = dict(
                normalized_unit=unit,
                raw_text=evidence[0].raw_text,
                confidence=0.99,
                status=FieldStatus.DETECTED,
                evidence=evidence,
            )
            return NumericField(value=plus, **common), NumericField(
                value=minus, **common
            )

        symmetric = self._matches(
            document,
            [
                rf"\bBORE\s+TOLERANCE\s*[:=]?\s*(?:±|\+/-)\s*(?P<value>{self._number})\s*(?P<unit>{self._unit})?"
            ],
        )
        if not symmetric:
            return NumericField(), NumericField()
        parsed = []
        for page, block, match in symmetric:
            unit = normalize_unit(match.groupdict().get("unit")) or default_unit
            parsed.append((parse_number(match.group("value")), unit, page, block))
        distinct = {
            (round(value, 12), unit.value if unit else None)
            for value, unit, _, _ in parsed
        }
        evidence = [self._evidence(page, block) for _, _, page, block in parsed]
        if len(distinct) > 1:
            ambiguous = NumericField(
                status=FieldStatus.AMBIGUOUS,
                confidence=0.4,
                raw_text=" | ".join(item.raw_text or "" for item in evidence),
                evidence=evidence,
            )
            return ambiguous, ambiguous.model_copy(deep=True)
        value, unit, _, _ = parsed[0]
        common = dict(
            normalized_unit=unit,
            raw_text=evidence[0].raw_text,
            confidence=0.99,
            status=FieldStatus.DETECTED,
            evidence=evidence,
        )
        return NumericField(value=value, **common), NumericField(value=value, **common)

    def _chamfer(
        self,
        document: NormalizedDocument,
        default_unit: MeasurementUnit | None,
    ) -> tuple[BooleanField, NumericField, NumericField, NumericField]:
        no_chamfer = self._matches(
            document, [r"\bCHAMFER\s*[:=]\s*(?P<value>NONE|NO)\b"]
        )
        detailed = self._matches(
            document,
            [
                rf"\bCHAMFER\s*[:=]?\s*(?P<width>{self._number})\s*(?P<unit>{self._unit})?\s*[Xx×]\s*(?P<angle>{self._number})\s*(?:DEG(?:REES?)?|°)?"
            ],
        )
        present_only = self._matches(
            document, [r"\bCHAMFER\s*[:=]\s*(?P<value>YES|REQUIRED)\b"]
        )
        if no_chamfer and (detailed or present_only):
            evidence = [
                self._evidence(page, block)
                for page, block, _ in no_chamfer + detailed + present_only
            ]
            return (
                BooleanField(
                    status=FieldStatus.AMBIGUOUS,
                    confidence=0.4,
                    raw_text=" | ".join(item.raw_text or "" for item in evidence),
                    evidence=evidence,
                ),
                NumericField(),
                NumericField(),
                NumericField(),
            )
        if detailed:
            page, block, match = detailed[0]
            evidence = [self._evidence(page, block)]
            unit = normalize_unit(match.groupdict().get("unit")) or default_unit
            common = dict(
                raw_text=block.text,
                confidence=0.99,
                status=FieldStatus.DETECTED,
                evidence=evidence,
            )
            return (
                BooleanField(value=True, **common),
                NumericField(
                    value=parse_number(match.group("width")),
                    normalized_unit=unit,
                    **common,
                ),
                NumericField(),
                NumericField(
                    value=parse_number(match.group("angle")),
                    normalized_unit=MeasurementUnit.DEGREE,
                    **common,
                ),
            )
        if present_only:
            page, block, _ = present_only[0]
            evidence = [self._evidence(page, block)]
            return (
                BooleanField(
                    value=True,
                    raw_text=block.text,
                    confidence=0.99,
                    status=FieldStatus.DETECTED,
                    evidence=evidence,
                ),
                NumericField(),
                NumericField(),
                NumericField(),
            )
        if no_chamfer:
            page, block, _ = no_chamfer[0]
            evidence = [self._evidence(page, block)]
            return (
                BooleanField(
                    value=False,
                    raw_text=block.text,
                    confidence=0.99,
                    status=FieldStatus.DETECTED,
                    evidence=evidence,
                ),
                NumericField(),
                NumericField(),
                NumericField(),
            )
        return BooleanField(), NumericField(), NumericField(), NumericField()
