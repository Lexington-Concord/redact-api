"""Tier-1 PII detectors: regex-driven candidate detection over raw page text.

Each ``detect_<category>`` scans a single ``PageModel`` and returns the PII
candidates it finds as ``CandidateSpan`` objects stamped ``SourceTier.TIER_1``.

Two rules hold across every detector here (redact-api#4):

* Matching is over the **raw** ``PageModel.text`` -- ``normalize_text`` is never
  applied first, so match offsets stay directly comparable to ``WordBBox``
  offsets and can be mapped to bboxes via ``resolve_span_bboxes`` (R5).
* Detectors are independent and never deduplicate against each other; a byte of
  text may be claimed by more than one category (adopted assumption).

Categories backed by a real validator (SSN SSA range rules, account-number Luhn)
emit ``CONFIDENCE_VALIDATED``; regex-only categories emit
``CONFIDENCE_REGEX_ONLY`` (R7). No third-party detection libraries are used:
Luhn and the SSN range check are hand-rolled; email candidates are confirmed
with ``email_validator`` (already an installed dependency) (R9).
"""

from __future__ import annotations

import re

from email_validator import EmailNotValidError, validate_email

from redact_api.detection.base import resolve_span_bboxes
from redact_api.detection.consts import (
    CATEGORY_ACCOUNT_NUMBER,
    CATEGORY_DOB,
    CATEGORY_EMAIL,
    CATEGORY_LICENSE_PLATE,
    CATEGORY_PHONE,
    CATEGORY_SSN,
    CONFIDENCE_REGEX_ONLY,
    CONFIDENCE_VALIDATED,
    DOB_ANCHOR_WINDOW_CHARS,
    DOB_KEYWORD_ANCHORS,
)
from redact_api.detection.models import CandidateSpan
from redact_api.ingest.models import PageModel
from redact_api.models.span import SourceTier

# --- Compiled patterns (matched against RAW page text, R5) ---

# Dashed SSN with strict 3-2-4 grouping; digit lookarounds prevent matching a
# window inside a longer digit run.
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")

# NANP phone: optional country code, area/exchange each begin 2-9, common
# separators (space, dot, hyphen) or none.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(\s*[2-9]\d{2}\s*\)|[2-9]\d{2})[\s.\-]?[2-9]\d{2}[\s.\-]?\d{4}(?!\d)"
)

# Coarse email candidate; every hit is confirmed with email_validator before it
# becomes a span.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Unbroken 12-19 digit run; Luhn-checked before it becomes a span.
_ACCOUNT_RE = re.compile(r"(?<!\d)\d{12,19}(?!\d)")

# Conservative generic plate shape: 5-8 uppercase alphanumerics; the mixed
# letter+digit requirement is enforced in _is_plate_shaped.
_LICENSE_PLATE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z0-9]{5,8}(?![A-Za-z0-9])")

# Numeric date (M/D/Y or M-D-Y); anchoring to a DOB keyword is done separately.
_DATE_RE = re.compile(r"(?<!\d)\d{1,2}[/-]\d{1,2}[/-]\d{2,4}(?!\d)")

# --- SSN SSA range rules (R9: hand-rolled, no third-party validator) ---
# Area 000 and 666 are never assigned; areas 900-999 are reserved (ITIN range).
_SSN_INVALID_AREAS = frozenset({0, 666})
_SSN_MAX_AREA = 899
# Group 00 and serial 0000 are never assigned.
_SSN_INVALID_GROUP = 0
_SSN_INVALID_SERIAL = 0

# --- Luhn checksum (R9: hand-rolled) ---
_LUHN_MODULUS = 10
_LUHN_DOUBLE_CAP = 9


def _is_valid_ssn(area: int, group: int, serial: int) -> bool:
    """True when the SSN's area/group/serial pass the SSA assignment rules."""
    if area in _SSN_INVALID_AREAS or area > _SSN_MAX_AREA:
        return False
    return group != _SSN_INVALID_GROUP and serial != _SSN_INVALID_SERIAL


def _luhn_check(digits: str) -> bool:
    """True when ``digits`` (an all-digit string) satisfies the Luhn checksum."""
    total = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        value = int(char)
        if index % 2 == parity:
            value *= 2
            if value > _LUHN_DOUBLE_CAP:
                value -= _LUHN_DOUBLE_CAP
        total += value
    return total % _LUHN_MODULUS == 0


def _is_valid_email(candidate: str) -> bool:
    """True when ``candidate`` passes RFC validation (deliverability not checked)."""
    try:
        validate_email(candidate, check_deliverability=False)
    except EmailNotValidError:
        return False
    return True


def _is_plate_shaped(candidate: str) -> bool:
    """True when ``candidate`` contains both a letter and a digit (mixed plate)."""
    return any(char.isalpha() for char in candidate) and any(char.isdigit() for char in candidate)


def _has_dob_anchor(text: str, match_start: int) -> bool:
    """True when a DOB keyword appears within the preceding raw-char window (R8)."""
    window = text[max(0, match_start - DOB_ANCHOR_WINDOW_CHARS) : match_start].casefold()
    return any(anchor in window for anchor in DOB_KEYWORD_ANCHORS)


def _candidate(page: PageModel, match: re.Match[str], category: str, confidence: float) -> CandidateSpan:
    """Build a ``CandidateSpan`` from a whole-match hit on ``page.text``."""
    start, end = match.start(), match.end()
    return CandidateSpan(
        page_number=page.page_number,
        start=start,
        end=end,
        bboxes=resolve_span_bboxes(page, start, end),
        text=match.group(),
        category=category,
        source_tier=SourceTier.TIER_1,
        confidence=confidence,
    )


def detect_ssn(page: PageModel) -> list[CandidateSpan]:
    """Detect dashed SSNs that satisfy the SSA area/group/serial rules."""
    spans: list[CandidateSpan] = []
    for match in _SSN_RE.finditer(page.text):
        area, group, serial = (int(part) for part in match.group().split("-"))
        if _is_valid_ssn(area, group, serial):
            spans.append(_candidate(page, match, CATEGORY_SSN, CONFIDENCE_VALIDATED))
    return spans


def detect_phone(page: PageModel) -> list[CandidateSpan]:
    """Detect NANP phone numbers in common written formats."""
    return [_candidate(page, match, CATEGORY_PHONE, CONFIDENCE_REGEX_ONLY) for match in _PHONE_RE.finditer(page.text)]


def detect_email(page: PageModel) -> list[CandidateSpan]:
    """Detect email addresses, confirming each candidate with email_validator."""
    spans: list[CandidateSpan] = []
    for match in _EMAIL_RE.finditer(page.text):
        if _is_valid_email(match.group()):
            spans.append(_candidate(page, match, CATEGORY_EMAIL, CONFIDENCE_REGEX_ONLY))
    return spans


def detect_account_number(page: PageModel) -> list[CandidateSpan]:
    """Detect 12-19 digit account numbers that pass the Luhn checksum."""
    spans: list[CandidateSpan] = []
    for match in _ACCOUNT_RE.finditer(page.text):
        if _luhn_check(match.group()):
            spans.append(_candidate(page, match, CATEGORY_ACCOUNT_NUMBER, CONFIDENCE_VALIDATED))
    return spans


def detect_license_plate(page: PageModel) -> list[CandidateSpan]:
    """Detect conservative generic (mixed letter+digit) license-plate shapes."""
    spans: list[CandidateSpan] = []
    for match in _LICENSE_PLATE_RE.finditer(page.text):
        if _is_plate_shaped(match.group()):
            spans.append(_candidate(page, match, CATEGORY_LICENSE_PLATE, CONFIDENCE_REGEX_ONLY))
    return spans


def detect_dob(page: PageModel) -> list[CandidateSpan]:
    """Detect dates of birth: numeric dates preceded by a DOB keyword anchor (R8)."""
    spans: list[CandidateSpan] = []
    for match in _DATE_RE.finditer(page.text):
        if _has_dob_anchor(page.text, match.start()):
            spans.append(_candidate(page, match, CATEGORY_DOB, CONFIDENCE_REGEX_ONLY))
    return spans
