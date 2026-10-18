"""Semantic Intent Gate — classifies requests BEFORE any LLM planning or SQL execution.

Outcome codes (also stored in QueryResponse.intent_classification):
  ANSWERABLE            – dataset supports the required concepts; proceed to planning.
  AMBIGUOUS             – required detail is missing or unclear; ask one clarification.
  UNSUPPORTED_BY_DATASET – request needs concepts absent from the selected dataset.
  DATASET_METADATA      – user asks about the dataset itself; answer from registry.
  UNSAFE_OR_INVALID     – request or structure is rejected by the safety policy.

Design contract:
  * Deterministic concept-matching against the dataset registry runs first.
  * The LLM is NOT consulted for intent classification (avoids circular trust).
  * An unknown question is never silently passed; uncertain cases are AMBIGUOUS.
  * Only ANSWERABLE returns None (no gate message); all others return a message.
  * This stage is injected into pipeline.ask() before llm.generate_plan().
  * It does NOT weaken or replace SQL validation or typed-plan validation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .dataset_registry import DATASETS, DEFAULT_DATASET_ID

# ---------------------------------------------------------------------------
# Classification outcome constants
# ---------------------------------------------------------------------------
ANSWERABLE = "ANSWERABLE"
AMBIGUOUS = "AMBIGUOUS"
UNSUPPORTED_BY_DATASET = "UNSUPPORTED_BY_DATASET"
DATASET_METADATA = "DATASET_METADATA"
UNSAFE_OR_INVALID = "UNSAFE_OR_INVALID"


@dataclass
class IntentResult:
    outcome: str                          # one of the constants above
    message: Optional[str] = None        # human-readable explanation / clarification
    missing_concepts: List[str] = field(default_factory=list)
    metadata_answer: Optional[str] = None  # populated for DATASET_METADATA only
    capability_match: Optional[dict] = None


# ---------------------------------------------------------------------------
# Dataset capability descriptors
# ---------------------------------------------------------------------------

# Concepts that each dataset CAN answer (mapped as concept → canonical column names)
_DATASET_CONCEPTS: Dict[str, Dict[str, List[str]]] = {
    "tpch_customer": {
        # purchasable items / identity
        "customer": ["C_CUSTKEY", "C_NAME"],
        "key": ["C_CUSTKEY"],
        "name": ["C_NAME"],
        "account_balance": ["C_ACCTBAL"],
        "market_segment": ["C_MKTSEGMENT"],
        "segment": ["C_MKTSEGMENT"],
        "count": ["C_CUSTKEY"],
        "ranking": ["C_ACCTBAL", "C_NAME", "C_CUSTKEY"],
        "highest": ["C_ACCTBAL"],
        "top": ["C_ACCTBAL", "C_NAME", "C_CUSTKEY"],
        "balance": ["C_ACCTBAL"],
    },
    "electricity_mix": {
        "electricity": ["RENEWABLES_TWH"],
        "renewable": ["RENEWABLES_TWH"],
        "generation": ["RENEWABLES_TWH"],
        "country": ["ENTITY"],
        "entity": ["ENTITY"],
        "year": ["YEAR"],
        "trend": ["YEAR", "RENEWABLES_TWH"],
        "ranking": ["ENTITY", "RENEWABLES_TWH"],
        "top": ["ENTITY", "RENEWABLES_TWH"],
        "highest": ["RENEWABLES_TWH"],
        "compare": ["YEAR", "RENEWABLES_TWH"],
    },
}

# Concepts that are explicitly NOT in each dataset — triggers UNSUPPORTED_BY_DATASET
# Each entry: (concept_name_for_message, regex_patterns_to_detect_it)
_UNSUPPORTED_CONCEPTS: Dict[str, List[tuple]] = {
    "tpch_customer": [
        # Sales, products, orders, revenue
        ("shirt sales", [r"\bshirt\b"]),
        ("product sales", [r"\bproduct\b", r"\bproducts\b"]),
        ("sales transactions", [r"\bsales?\b(?!\s+(?:force|rep|person|team))"]),
        ("order history", [r"\border\b", r"\borders\b", r"\bpurchase history\b", r"\bbuy\b", r"\bbought\b"]),
        ("revenue", [r"\brevenue\b", r"\brevenues\b"]),
        ("spending history", [r"\bspending\b", r"\bspent\b"]),
        ("invoice data", [r"\binvoice\b"]),
        ("date/time data", [r"\bthis year\b", r"\blast year\b", r"\bmonthly\b",
                            r"\bannual\b", r"\bquarterly\b", r"\b\d{4}\b",
                            r"\byear(?:ly)?\s+(?:comparison|trend)\b",
                            r"\bcompare.*year\b", r"\byear.*compar\b"]),
        ("product categories", [r"\bcategory\b", r"\bcategories\b"]),
        ("transaction dates", [r"\bdate\b", r"\bdates\b", r"\btimestamp\b"]),
        ("temperature data", [r"\btemperature\b", r"\bweather\b", r"\bclimate\b", r"\bhot\b", r"\bheat\b"]),
        ("stock or inventory", [r"\bstock\b", r"\binventory\b", r"\bwarehouse\b"]),
        ("supplier data", [r"\bsupplier\b", r"\bvendor\b"]),
        ("employee data", [r"\bemployee\b", r"\bstaff\b"]),
        ("profit data", [r"\bprofit\b", r"\bmargin\b"]),
        ("pricing data", [r"\bprice\b", r"\bprices\b", r"\bpricing\b"]),
        ("part/item data", [r"\bpart\b", r"\bitem\b", r"\blineitem\b"]),
        ("nation/region data", [r"\bnation\b", r"\bregion\b", r"\bcountry\b", r"\bcountries\b"]),
        ("address or location", [r"\baddresses?\b", r"\bcities\b", r"\bcity\b", r"\bzip\b"]),
    ],
    "electricity_mix": [
        ("solar generation breakdown", [r"\bsolar\b"]),
        ("wind generation breakdown", [r"\bwind\b"]),
        ("hydro generation breakdown", [r"\bhydro\b"]),
        ("coal or fossil fuel data", [r"\bcoal\b", r"\bfossil\b", r"\bgas\b", r"\boil\b",
                                      r"\bnuclear\b", r"\bnatural gas\b"]),
        ("electricity consumption", [r"\bconsumption\b", r"\bdemand\b", r"\bused\b"]),
        ("per-capita measures", [r"\bper capita\b", r"\bper person\b", r"\bpopulation\b"]),
        ("renewable share/percentage", [r"\bpercentage\b", r"\bshare\b", r"\bfraction\b",
                                        r"\b%\b", r"\bpercent\b"]),
        ("total electricity generation", [r"\btotal electricity\b", r"\btotal generation\b(?!.*renewable)"]),
        ("temperature data", [r"\btemperature\b", r"\bweather\b", r"\bclimate\b", r"\bhot\b", r"\bheat\b"]),
        ("customer data", [r"\bcustomer\b", r"\bsales?\b", r"\brevenue\b"]),
        ("price data", [r"\bprice\b", r"\bcost\b", r"\btariff\b"]),
        ("CO2 emissions", [r"\bco2\b", r"\bcarbon\b", r"\bemissions\b"]),
    ],
}

# Metadata trigger patterns — if matched → DATASET_METADATA (no LLM, no SQL)
_METADATA_TRIGGERS = [
    r"\bwhat (?:is|does|are) (?:this|the) dataset\b",
    r"\bwhat (?:is|does) (?:this|the) data(?:set)? (?:contain|cover|include|about|mean|measure|represent)\b",
    r"\bwhat columns?\b",
    r"\bwhich columns?\b",
    r"\bavailable columns?\b",
    r"\bwhat fields?\b",
    r"\bwhich fields?\b",
    r"\bshow (?:me )?(?:the )?(?:available |all )?columns?\b",
    r"\bshow (?:me )?(?:the )?(?:available |all )?fields?\b",
    r"\bschema\b",
    r"\bwhat years? (?:are )?(?:covered|available|in (?:the|this))\b",
    r"\bwhat (?:is|are) (?:the )?(?:available |supported )?years?\b",
    r"\bwhat (?:does|is) renewables_twh (?:mean|measure|represent)\b",
    r"\bwhat (?:does|is|are) (?:the )?(?:unit|units?)\b",
    r"\bwhat (?:is|are) (?:the )?(?:source|license|attribution)\b",
    r"\btell me about (?:this|the) dataset\b",
    r"\bdescribe (?:this|the) dataset\b",
    r"\bwhat data (?:is|are) (?:available|in (?:this|the) dataset)\b",
    r"\bwhat (?:can|do) (?:you|i|we) (?:query|ask|filter|search)\b",
    r"\bwhat (?:is|are) (?:the )?limitations?\b",
    r"\bwhat (?:is|are) (?:the )?(?:supported|available) (?:operations?|aggregations?|filters?)\b",
]

# Ambiguity indicators for each dataset — missing required detail
_AMBIGUITY_PATTERNS: Dict[str, List[tuple]] = {
    # (clarification_message, detection_pattern, required_detail_missing)
    "electricity_mix": [
        (
            "Which year should I use? The dataset covers 2000–2025. "
            "Name a year or ask for 'the latest' (2025).",
            [r"\btrend\b", r"\bchange(?:d)?\b", r"\bover time\b", r"\bhistor(?:y|ical)\b",
             r"\bevolution\b", r"\bgrowth\b"],
            # Only ambiguous if NO year is present
            lambda q: not re.search(r"\b(?:19|20)\d{2}\b", q, re.IGNORECASE)
               and "latest" not in q.lower()
               and "most recent" not in q.lower()
               and not re.search(r"\ball years\b|\bevery year\b", q.lower()),
        ),
        (
            "Which country or region should I filter to? "
            "Name a specific country or ask for all countries.",
            [r"\bgeneration\b", r"\brenewable\b"],
            # Ambiguous if a country-specific question lacks a country name but also
            # isn't a global/ranking question.
            lambda q: (
                not re.search(r"\bcountries\b|\ball\b|\bworld\b|\bglobal\b|\branking\b|\btop\b|\bmost\b|\bhighest\b|\blargest\b", q, re.IGNORECASE)
                and not _has_country_mention(q)
                and re.search(r"\bin\b", q, re.IGNORECASE)
                and not re.search(r"\b(?:19|20)\d{2}\b|\blatest\b|\brecent\b", q, re.IGNORECASE)
            ),
        ),
    ],
}

# Concepts with reasonable synonyms that should map to ANSWERABLE for each dataset
_SYNONYM_MAP: Dict[str, Dict[str, str]] = {
    "tpch_customer": {
        r"\bclient\b": "customer",
        r"\baccount\b": "account_balance",
        r"\bfinancial\b": "account_balance",
        r"\bsegments?\b": "market_segment",
        r"\bindustry\b": "market_segment",
        r"\bvalue\b(?!\s+chain)": "account_balance",
    },
    "electricity_mix": {
        r"\benergy\b": "renewable",
        r"\bpower\b": "electricity",
        r"\bgreen energy\b": "renewable",
        r"\bclean energy\b": "renewable",
        r"\brenewables\b": "renewable",
        r"\belectricity output\b": "generation",
        r"\belectricity produced\b": "generation",
        r"\bnations?\b": "country",
        r"\bregions?\b": "country",
        r"\bterawatt\b": "electricity",
        r"\btwh\b": "electricity",
    },
}


# ---------------------------------------------------------------------------
# Helper: country-name detection (simple heuristic for electricity_mix)
# ---------------------------------------------------------------------------
def _has_country_mention(question: str) -> bool:
    """Return True when the question names a plausible country or territory."""
    # Check for capitalised proper noun following prepositions
    if re.search(r"\b(?:in|for|of)\s+[A-Z][a-z]", question):
        return True
    # Check for any word starting with a capital that's not the first word
    words = question.split()
    for word in words[1:]:
        cleaned = re.sub(r"[^\w]", "", word)
        if cleaned and cleaned[0].isupper():
            return True
    return False


# ---------------------------------------------------------------------------
# Metadata answer builder
# ---------------------------------------------------------------------------
def _build_metadata_answer(dataset_id: str, question: str) -> str:
    """Construct a metadata answer from registry-only data."""
    dataset = DATASETS.get(dataset_id)
    if dataset is None:
        return "The selected dataset is not registered."

    q = question.lower()

    # Schema / columns question
    if re.search(r"\bcolumns?\b|\bfields?\b|\bschema\b", q):
        field_lines = []
        for name, details in dataset["fields"].items():
            unit = details.get("unit", "")
            desc = details.get("description", "")
            unit_str = f" ({unit})" if unit else ""
            field_lines.append(f"  • {name}{unit_str}: {desc}")
        # Add definitions if available
        definitions = dataset.get("definitions", {})
        def_lines = []
        for name, definition in definitions.items():
            def_lines.append(f"  • {name}: {definition}")
        result = f"The {dataset['name']} dataset has these fields:\n" + "\n".join(field_lines)
        if def_lines:
            result += "\n\nField definitions:\n" + "\n".join(def_lines)
        return result

    # Year coverage (electricity_mix only)
    if re.search(r"\byears?\b|\bcoverage\b|\btime\b|\bperiod\b", q) and dataset_id == "electricity_mix":
        subset = dataset.get("subset", {})
        year_min = subset.get("year_min", "unknown")
        year_max = subset.get("year_max", "unknown")
        retrieved = dataset.get("retrieved_on", "not documented")
        return (
            f"This bundled snapshot of {dataset['name']} covers years {year_min}–{year_max} "
            f"for ISO alpha-3 coded countries and territories. "
            f"The data was retrieved on {retrieved}. "
            f"'Latest available year' is {year_max}."
        )

    # Units question
    if re.search(r"\bunits?\b|\bmeasure(?:s|ment)?\b|\bmean\b", q):
        units = dataset.get("units", {})
        if units:
            unit_lines = [f"  • {k}: {v}" for k, v in units.items()]
            return f"Units for {dataset['name']}:\n" + "\n".join(unit_lines)
        definitions = dataset.get("definitions", {})
        if definitions:
            def_lines = [f"  • {k}: {v}" for k, v in definitions.items()]
            return f"Field definitions for {dataset['name']}:\n" + "\n".join(def_lines)
        return "No unit documentation is recorded for this dataset in the registry."

    # Source / attribution / license question
    if re.search(r"\bsource\b|\blicense\b|\battribution\b|\bcredit\b", q):
        attribution = dataset.get("attribution", "Not documented.")
        license_text = dataset.get("license", "Not documented.")
        source_url = dataset.get("source_url", "")
        result = f"Attribution: {attribution}\nLicense: {license_text}"
        if source_url:
            result += f"\nSource URL: {source_url}"
        return result

    # Limitations / supported operations
    if re.search(r"\blimitations?\b|\bsupported\b|\boperations?\b|\bfilters?\b|\baggregations?\b", q):
        supported = dataset.get("supported", {})
        missing = dataset.get("missing_values", "")
        if supported:
            lines = []
            for key, value in supported.items():
                lines.append(f"  • {key}: {', '.join(value) if isinstance(value, list) else value}")
            result = f"Supported operations for {dataset['name']}:\n" + "\n".join(lines)
        else:
            result = f"Supported operations for {dataset['name']} are not fully documented in the registry."
        if missing:
            result += f"\n\nMissing values: {missing}"
        return result

    # General / "what is this dataset" fallback
    description = dataset.get("description", "No description available.")
    storage = dataset.get("storage", "not documented")
    attribution = dataset.get("attribution", "not documented")

    result = f"{dataset['name']}: {description}\n\nStorage: {storage}\nAttribution: {attribution}"

    if dataset_id == "electricity_mix":
        subset = dataset.get("subset", {})
        rows_count = subset.get("rows", "unknown")
        year_min = subset.get("year_min", "unknown")
        year_max = subset.get("year_max", "unknown")
        result += f"\n\nThis bundled snapshot covers {year_min}–{year_max} with {rows_count} rows for ISO-coded entities."
        missing = dataset.get("missing_values", "")
        if missing:
            result += f"\n\n{missing}"

    return result


# ---------------------------------------------------------------------------
# Core classification logic
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return " ".join(text.lower().strip().split())


def _apply_synonyms(text: str, dataset_id: str) -> str:
    """Replace known synonyms with their canonical concept names."""
    synonym_map = _SYNONYM_MAP.get(dataset_id, {})
    for pattern, replacement in synonym_map.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _detect_unsupported(text: str, dataset_id: str) -> Optional[tuple]:
    """
    Return (concept_name, patterns_matched) if text requests something the dataset lacks.
    Returns None if no unsupported concept is detected.
    """
    unsupported_list = _UNSUPPORTED_CONCEPTS.get(dataset_id, [])
    for concept_name, patterns in unsupported_list:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return concept_name, [pattern]
    return None


def _detect_metadata(text: str) -> bool:
    """Return True when the question is about the dataset itself."""
    for pattern in _METADATA_TRIGGERS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _detect_ambiguity(question: str, dataset_id: str) -> Optional[str]:
    """
    Return a clarification message if the question is ambiguous for this dataset.
    Returns None when no ambiguity is detected.
    """
    if (dataset_id == "electricity_mix"
            and re.search(r"\b(?:this year|last year|year over year|year to year)\b", question, re.IGNORECASE)):
        return ("Which country should I compare, and which years in the 2000–2025 snapshot "
                "should I use? The dataset reports renewable generation in TWh.")

    patterns_list = _AMBIGUITY_PATTERNS.get(dataset_id, [])
    for message, trigger_patterns, condition_fn in patterns_list:
        if any(re.search(p, question, re.IGNORECASE) for p in trigger_patterns):
            try:
                if condition_fn(question):
                    return message
            except Exception:
                pass
    return None


def _has_registered_concept(text: str, dataset_id: str) -> bool:
    """Require a request to name at least one catalog concept before planning.

    This is a conservative boundary: known aliases are normalized first, and
    fields come from the trusted registry. Unfamiliar wording is clarified
    instead of being treated as proof that a request is answerable.
    """
    normalized = _apply_synonyms(_normalise(text), dataset_id)
    concepts = _DATASET_CONCEPTS.get(dataset_id, {})
    for concept in concepts:
        if re.search(r"(?<!\w)" + re.escape(concept.replace("_", " ")) + r"s?(?!\w)", normalized):
            return True
        if re.search(r"(?<!\w)" + re.escape(concept) + r"s?(?!\w)", normalized):
            return True
    fields = DATASETS[dataset_id].get("fields", {})
    return any(re.search(r"(?<!\w)" + re.escape(field.casefold()) + r"(?!\w)", normalized)
               for field in fields)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify(question: str, dataset_id: str = DEFAULT_DATASET_ID) -> IntentResult:
    """
    Classify a question against the selected dataset's registered capabilities.

    Called by pipeline.ask() BEFORE any LLM call or SQL execution.
    Returns an IntentResult; the pipeline only proceeds to LLM planning
    when outcome == ANSWERABLE.
    """
    if not isinstance(question, str) or not question.strip():
        return IntentResult(outcome=UNSAFE_OR_INVALID, message="Question is empty.")

    dataset = DATASETS.get(dataset_id)
    if dataset is None:
        return IntentResult(outcome=UNSAFE_OR_INVALID, message="The selected dataset is not registered.")

    text = _normalise(question)
    text_with_synonyms = _apply_synonyms(text, dataset_id)

    # -----------------------------------------------------------------
    # 1. DATASET_METADATA — user asks about the dataset itself
    # -----------------------------------------------------------------
    if _detect_metadata(text):
        metadata_answer = _build_metadata_answer(dataset_id, question)
        return IntentResult(
            outcome=DATASET_METADATA,
            message=metadata_answer,
            metadata_answer=metadata_answer,
            capability_match={"status": "passed", "checks": [{
                "name": "registered_metadata", "status": "passed",
                "detail": "The response uses only metadata recorded for the selected dataset.",
            }]},
        )

    # -----------------------------------------------------------------
    # 2. UNSUPPORTED_BY_DATASET — deterministic concept check
    #    Run BEFORE ambiguity so we never ask for clarification on a
    #    fundamentally unsupported concept.
    # -----------------------------------------------------------------
    unsupported = _detect_unsupported(text_with_synonyms, dataset_id)
    if unsupported is not None:
        concept_name, _ = unsupported
        dataset_name = dataset.get("name", dataset_id)
        registered_fields = list(dataset.get("fields", {}).keys())
        field_list = ", ".join(registered_fields) if registered_fields else "none documented"
        message = (
            f"This question requires {concept_name}, which is not available in the "
            f"selected dataset '{dataset_name}'. "
            f"The available fields are: {field_list}. "
            f"Please select a dataset that contains the required data, or ask about "
            f"what is available in this dataset."
        )
        return IntentResult(
            outcome=UNSUPPORTED_BY_DATASET,
            message=message,
            missing_concepts=[concept_name],
            capability_match={"status": "failed", "checks": [{
                "name": "dataset_capability", "status": "failed",
                "detail": f"The selected dataset does not provide {concept_name}.",
            }]},
        )

    # -----------------------------------------------------------------
    # 3. AMBIGUOUS — required detail is missing
    # -----------------------------------------------------------------
    ambiguity_message = _detect_ambiguity(question, dataset_id)
    if ambiguity_message is not None:
        return IntentResult(outcome=AMBIGUOUS, message=ambiguity_message,
                            capability_match={"status": "passed", "checks": [{
                                "name": "dataset_capability", "status": "passed",
                                "detail": "The requested concept is available; a required scope detail is missing.",
                            }]})

    # Do not turn an unfamiliar or underspecified request into an executable
    # query merely because a planner might produce a syntactically valid plan.
    if not _has_registered_concept(text_with_synonyms, dataset_id):
        dataset_name = dataset.get("name", dataset_id)
        fields = ", ".join(dataset.get("fields", {}))
        return IntentResult(
            outcome=AMBIGUOUS,
            message=(f"I couldn't map that request to a documented capability of {dataset_name}. "
                     f"Which of these fields or measures should I use: {fields}?"),
            capability_match={"status": "not_run", "checks": [{
                "name": "dataset_capability", "status": "not_run",
                "detail": "Capability matching needs clarification because the request uses no registered concept.",
            }]},
        )

    # -----------------------------------------------------------------
    # 4. ANSWERABLE — passes all gates; let the LLM plan proceed
    # -----------------------------------------------------------------
    return IntentResult(outcome=ANSWERABLE, capability_match={"status": "passed", "checks": [{
        "name": "dataset_capability", "status": "passed",
        "detail": "Requested concepts map to fields or operations in the trusted dataset catalog.",
    }]})
