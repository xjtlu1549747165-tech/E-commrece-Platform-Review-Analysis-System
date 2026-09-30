"""
Prototype registry for Policy page documents (no separate YAML/JSON manifest).

PDF files live under app/static/policy/{REGION_CODE}/ matching `filename`.
Replace placeholder PDFs with your HKEAA downloads as needed.
"""

from __future__ import annotations

from typing import Any

# Adcodes from DataV china_100000_full.json (province-level features).
ENABLED_REGION_ADCODES: frozenset[int] = frozenset({810000})  # Hong Kong SAR only (prototype)

REGION_LABEL_EN: dict[str, str] = {
    "HK": "Hong Kong SAR",
}

# Documents per region code (Flask static URL built as policy/{code}/{filename})
REGION_DOCUMENTS: dict[str, list[dict[str, Any]]] = {
    "HK": [
        {
            "filename": "2025_HKDSE_Regulations_C.pdf",
            "title_en": "HKDSE Examination Regulations and Assessment Information (2025 cohort)",
            "issuer": "Hong Kong Examinations and Assessment Authority (HKEAA)",
            "reference": "N/A",
            "source_url": "https://www.hkeaa.edu.hk/en/hkdse/",
            "excerpt_date": "2025-05-01",
        },
        {
            "filename": "2026_HKDSE_Regulations_C.pdf",
            "title_en": "HKDSE Examination Regulations and Assessment Information (2026 cohort)",
            "issuer": "Hong Kong Examinations and Assessment Authority (HKEAA)",
            "reference": "N/A",
            "source_url": "https://www.hkeaa.edu.hk/en/hkdse/",
            "excerpt_date": "2025-05-01",
        },
        {
            "filename": "2027_HKDSE_Regulations_C.pdf",
            "title_en": "HKDSE Examination Regulations and Assessment Information (2027 cohort)",
            "issuer": "Hong Kong Examinations and Assessment Authority (HKEAA)",
            "reference": "N/A",
            "source_url": "https://www.hkeaa.edu.hk/en/hkdse/",
            "excerpt_date": "2025-05-01",
        },
        {
            "filename": "2028_HKDSE_Regulations_C.pdf",
            "title_en": "HKDSE Examination Regulations and Assessment Information (2028 cohort)",
            "issuer": "Hong Kong Examinations and Assessment Authority (HKEAA)",
            "reference": "N/A",
            "source_url": "https://www.hkeaa.edu.hk/en/hkdse/",
            "excerpt_date": "2025-05-01",
        },
    ],
}
