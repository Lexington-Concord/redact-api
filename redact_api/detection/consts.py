"""Constants for Tier-1 PII detection (category taxonomy + confidence pinning).

Category labels are the lowercase snake_case taxonomy every Tier-1 detector
stamps onto its ``CandidateSpan.category``. They are the detection-layer
vocabulary only -- the persisted ``Span.category`` column stays free-text and is
untouched by this module (redact-api#4 R2).

Confidence is pinned per category by how the detector confirms a candidate:
categories backed by a real validator (SSA range rules for SSN, Luhn for account
numbers) emit ``CONFIDENCE_VALIDATED``; regex-only categories emit
``CONFIDENCE_REGEX_ONLY`` (R7).
"""

from __future__ import annotations

# --- Category taxonomy (lowercase snake_case; detection-layer only, R2) ---
CATEGORY_SSN = "ssn"
CATEGORY_PHONE = "phone"
CATEGORY_EMAIL = "email"
CATEGORY_ACCOUNT_NUMBER = "account_number"
CATEGORY_LICENSE_PLATE = "license_plate"
CATEGORY_DOB = "dob"

# --- Confidence pinning (R7) ---
# Emitted by categories confirmed with a real validator (SSN SSA range rules,
# account-number Luhn checksum).
CONFIDENCE_VALIDATED = 1.0
# Emitted by regex-only categories (phone, email, license plate, DOB), which
# have no independent checksum/authority behind the pattern.
CONFIDENCE_REGEX_ONLY = 0.9

# --- DOB anchoring (R8) ---
# Keyword anchors (compared case-insensitively) that must appear shortly before a
# date for it to count as a date of birth. Stored lowercase so a single casefold
# of the preceding window suffices.
DOB_KEYWORD_ANCHORS = ("dob", "date of birth", "born")
# Number of raw characters immediately preceding a date that are scanned for an
# anchor. A literal character window (no line-boundary restriction), per the
# adopted assumption for redact-api#4.
DOB_ANCHOR_WINDOW_CHARS = 32
