"""Phase 1 profile governance wrapper.

The old ``tn_university`` profile is retained for compatibility but is labelled
unverified. Institution-specific profiles are versioned and must be based on an
approved exemplar. The documented MCC/UoM legacy formatter uses 1.5 spacing.
"""

from __future__ import annotations

from dataclasses import replace

from app.renderers.profiles import ResolvedProfile, resolve_profile


MCC_PROFILE = "mcc_ma_english_2026"
GENERIC_TN_PROFILE = "tn_university"
MLA_PROFILE = "mla_strict"


PROFILE_LABELS = {
    MCC_PROFILE: "MCC MA English 2026 · verified legacy rules",
    GENERIC_TN_PROFILE: "Generic Tamil Nadu · spacing must be confirmed",
    MLA_PROFILE: "MLA 9 strict",
}


def resolve_phase1_profile(
    name: str,
    override: dict | None = None,
) -> tuple[ResolvedProfile, str]:
    """Resolve a governed profile and return ``(profile, version_label)``."""

    if name == MCC_PROFILE:
        base = resolve_profile(GENERIC_TN_PROFILE, override)
        governed = replace(
            base,
            type=replace(base.type, line_spacing=1.5),
            toc=replace(base.toc, native_word_field=True),
            notes=(
                (base.notes + " ") if base.notes else ""
            )
            + "MCC/University of Madras MA English profile; 1.5 spacing retained from the verified legacy formatter.",
        )
        return governed, "mcc_ma_english_2026:v1"

    base = resolve_profile(name, override)
    if name == GENERIC_TN_PROFILE:
        base = replace(
            base,
            toc=replace(base.toc, native_word_field=True),
            notes=(
                (base.notes + " ") if base.notes else ""
            )
            + "Generic TN profile is not institution-certified; operator must confirm spacing and official template wording.",
        )
        return base, "tn_university:compat-unverified-v1"
    if name == MLA_PROFILE:
        return base, "mla_strict:v1"
    return base, f"custom-base:{name}:v1"
