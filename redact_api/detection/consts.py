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
# Tier-2 (NER) categories (redact-api#5 R5). Same lowercase snake_case taxonomy;
# name/organization/location are Tier-2 exclusive, while phone/email/ssn overlap
# the Tier-1 categories above so NER-found instances land under the same label.
CATEGORY_NAME = "name"
CATEGORY_ORGANIZATION = "organization"
CATEGORY_LOCATION = "location"

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

# --- Tier-2 NER confidence floor (redact-api#5 R4) ---
# Presidio results scoring below this are dropped at detection time. The floor is
# applied inclusively (``score >= TIER2_MIN_CONFIDENCE``): Presidio's
# ``PhoneRecognizer`` emits its base pattern hits at exactly 0.4, so an exclusive
# floor would silently drop every base-confidence phone number. Change only with
# evidence that a different cutoff improves precision/recall on real documents.
TIER2_MIN_CONFIDENCE = 0.4

# --- Tier-2 entity mapping (redact-api#5 R5) ---
# Maps the Presidio entity types this service redacts onto its detection-layer
# category taxonomy. PERSON/ORGANIZATION/LOCATION are Tier-2 exclusive;
# PHONE_NUMBER/EMAIL_ADDRESS/US_SSN overlap Tier-1 categories on purpose. Every
# other entity type Presidio can emit for ``language="en"`` is dropped (both by
# the ``entities=`` request filter and defensively via ``.get()`` at build time).
PRESIDIO_ENTITY_TO_CATEGORY: dict[str, str] = {
    "PERSON": CATEGORY_NAME,
    "ORGANIZATION": CATEGORY_ORGANIZATION,
    "LOCATION": CATEGORY_LOCATION,
    "PHONE_NUMBER": CATEGORY_PHONE,
    "EMAIL_ADDRESS": CATEGORY_EMAIL,
    "US_SSN": CATEGORY_SSN,
}
