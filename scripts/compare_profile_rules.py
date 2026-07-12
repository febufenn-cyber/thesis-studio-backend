"""Compare a formatting profile against explicit institutional rules.

Subphase E (institution profile sign-off tooling). Takes ``--profile`` (a name
registered in ``app.renderers.phase1_profiles``) and ``--rules`` (a JSON file,
or a Markdown file whose first ```json fenced block holds the same object) of
explicit institutional requirements — page size, margins, font, spacing,
chapter-title treatment, pagination, quotation style, works-cited style — and
prints a deviation table (rule, expected, actual, match|deviation|unverifiable).

Actual values come from the resolved profile configuration; when a rendered
golden fingerprint exists (produced by ``scripts/generate_profile_golden.py``
under ``var/profile-goldens/<profile>/<version>/fingerprint.json``) the
rendered values are cross-checked too, so a rule only counts as ``match`` when
both the configuration and the rendered DOCX agree with it.

Exit codes: 0 = no deviations, 1 = at least one deviation, 2 = usage error.

A starter rules file lives at
``docs/release/profile-rules/MCC_MA_ENGLISH.example.json``. It is populated
from the repo's own documented legacy-formatter settings and is EXAMPLE data —
not institutional evidence. Certification requires values transcribed from the
official institutional guide.

Usage::

    .venv-validate/bin/python scripts/compare_profile_rules.py \
        --profile mcc_ma_english_2026 \
        --rules docs/release/profile-rules/MCC_MA_ENGLISH.example.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.renderers.phase1_profiles import PROFILE_LABELS, resolve_phase1_profile  # noqa: E402
from app.renderers.profiles import ResolvedProfile  # noqa: E402

_FLOAT_TOL = 0.01


@dataclass
class RuleResult:
    """One row of the deviation table."""

    rule: str
    expected: Any
    actual: Any
    status: str  # "match" | "deviation" | "unverifiable"
    note: str = ""


def load_rules(path: Path) -> dict[str, Any]:
    """Load the rules object from a JSON file or a Markdown ```json block."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".md", ".markdown"):
        match = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
        if not match:
            raise ValueError(f"No ```json fenced block found in {path.name}")
        text = match.group(1)
    data = json.loads(text)
    if "rules" not in data or not isinstance(data["rules"], dict):
        raise ValueError('Rules file must contain a top-level "rules" object')
    return data


def _values_match(expected: Any, actual: Any) -> bool:
    """Compare rule values with a small tolerance for floats."""
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)) \
            and not isinstance(expected, bool) and not isinstance(actual, bool):
        return abs(float(expected) - float(actual)) < _FLOAT_TOL
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip() == actual.strip()
    return expected == actual


def _row(rule: str, expected: Any, config_value: Any, rendered_value: Any = ...,
         note: str = "") -> RuleResult:
    """Build one result row, cross-checking config against the rendered value.

    ``rendered_value`` uses Ellipsis as the "not renderable / no fingerprint"
    sentinel so ``None`` can still be a legitimate rendered value.
    """
    if rendered_value is not ...:
        if not _values_match(config_value, rendered_value):
            return RuleResult(
                rule, expected, f"config={config_value} rendered={rendered_value}",
                "deviation", note="profile config and rendered DOCX disagree",
            )
        actual: Any = rendered_value
        note = (note + "; " if note else "") + "render-verified"
    else:
        actual = config_value
    status = "match" if _values_match(expected, actual) else "deviation"
    return RuleResult(rule, expected, actual, status, note)


def _fingerprint_path(profile_name: str, version_label: str) -> Path:
    """Default fingerprint location written by generate_profile_golden.py."""
    version_dir = version_label.split(":", 1)[1] if ":" in version_label else version_label
    return REPO_ROOT / "var" / "profile-goldens" / profile_name / version_dir / "fingerprint.json"


def compare(profile_name: str, profile: ResolvedProfile, rules: dict[str, Any],
            fingerprint: dict[str, Any] | None) -> list[RuleResult]:
    """Compare every provided rule against the profile (and fingerprint if any)."""
    results: list[RuleResult] = []
    fmt = (fingerprint or {}).get("formatting", {})
    sections = fmt.get("sections", [])
    body_sect = sections[-1] if sections else {}
    front_sect = sections[0] if sections else {}
    normal = (fmt.get("styles") or {}).get("TS-Normal") or {}
    bq_style = (fmt.get("styles") or {}).get("TS-BlockQuote") or {}
    title_style = (fmt.get("styles") or {}).get("TS-ChapterTitle") or {}
    wc_hang = fmt.get("works_cited_hanging_indent") or {}
    have_fp = bool(fmt)

    def rendered(value: Any) -> Any:
        return value if have_fp else ...

    if "page_size" in rules:
        results.append(_row("page_size", rules["page_size"], profile.page.size,
                            rendered(body_sect.get("page_size"))))

    for side in ("top", "bottom", "left", "right"):
        key = f"margins_in.{side}"
        margins = rules.get("margins_in") or {}
        if side in margins:
            results.append(_row(
                key, margins[side], getattr(profile.page.margins_in, side),
                rendered((body_sect.get("margins_in") or {}).get(side)),
            ))

    if "font" in rules:
        results.append(_row("font", rules["font"], profile.type.font,
                            rendered(normal.get("font"))))
    if "font_size_pt" in rules:
        results.append(_row("font_size_pt", rules["font_size_pt"], profile.type.size_pt,
                            rendered(normal.get("size_pt"))))
    if "line_spacing" in rules:
        results.append(_row("line_spacing", rules["line_spacing"], profile.type.line_spacing,
                            rendered(normal.get("line_spacing"))))
    if "first_line_indent_in" in rules:
        results.append(_row(
            "first_line_indent_in", rules["first_line_indent_in"],
            profile.type.first_line_indent_in, rendered(normal.get("first_line_indent_in")),
        ))
    if "justify_body" in rules:
        justified = None
        if have_fp:
            justified = "JUSTIFY" in str(normal.get("alignment") or "")
        results.append(_row("justify_body", rules["justify_body"],
                            profile.type.justify_body, rendered(justified)))

    chapter = rules.get("chapter_title") or {}
    if "label_format" in chapter:
        results.append(_row("chapter_title.label_format", chapter["label_format"],
                            profile.chapter_label.format))
    if "caps" in chapter:
        results.append(_row("chapter_title.caps", chapter["caps"],
                            profile.chapter_label.title_caps,
                            note="casing applied to text; not render-detectable from style"))
    if "bold" in chapter:
        results.append(_row("chapter_title.bold", chapter["bold"],
                            profile.chapter_label.title_bold,
                            rendered(bool(title_style.get("bold")))))
    if "new_page" in chapter:
        results.append(_row("chapter_title.new_page", chapter["new_page"],
                            profile.chapter_label.new_page))

    pagination = rules.get("pagination") or {}
    if "front_style" in pagination:
        results.append(_row("pagination.front_style", pagination["front_style"],
                            profile.pagination.front.style,
                            rendered(_style_from_fmt(front_sect.get("page_number_format")))))
    if "front_position" in pagination:
        results.append(_row("pagination.front_position", pagination["front_position"],
                            profile.pagination.front.position))
    if "body_style" in pagination:
        results.append(_row("pagination.body_style", pagination["body_style"],
                            profile.pagination.body.style,
                            rendered(_style_from_fmt(body_sect.get("page_number_format")))))
    if "body_position" in pagination:
        results.append(_row("pagination.body_position", pagination["body_position"],
                            profile.pagination.body.position))
    if "body_restart_at" in pagination:
        rendered_start = body_sect.get("page_number_start")
        results.append(_row(
            "pagination.body_restart_at", pagination["body_restart_at"],
            profile.pagination.body.restart_at,
            rendered(int(rendered_start) if rendered_start is not None else None),
        ))
    if "mla_header_name" in pagination:
        results.append(_row("pagination.mla_header_name", pagination["mla_header_name"],
                            profile.pagination.mla_header_name))

    quotes = rules.get("quotations") or {}
    if "block_threshold_lines" in quotes:
        results.append(_row("quotations.block_threshold_lines",
                            quotes["block_threshold_lines"],
                            profile.quotes.block_threshold_lines))
    if "block_indent_in" in quotes:
        results.append(_row("quotations.block_indent_in", quotes["block_indent_in"],
                            profile.quotes.block_indent_in,
                            rendered(bq_style.get("left_indent_in"))))
    if "verse_threshold_lines" in quotes:
        results.append(_row("quotations.verse_threshold_lines",
                            quotes["verse_threshold_lines"],
                            profile.quotes.verse_threshold_lines))

    works_cited = rules.get("works_cited") or {}
    if "style" in works_cited:
        results.append(RuleResult(
            "works_cited.style", works_cited["style"],
            "MLA 9 templates (app/renderers/works_cited.py)",
            "unverifiable",
            note="citation-style conformance needs manual review against the official guide",
        ))
    if "heading" in works_cited:
        results.append(_row("works_cited.heading", works_cited["heading"],
                            profile.works_cited.heading))
    if "heading_bold" in works_cited:
        results.append(_row("works_cited.heading_bold", works_cited["heading_bold"],
                            profile.works_cited.heading_bold))
    if "hanging_indent_in" in works_cited:
        results.append(_row(
            "works_cited.hanging_indent_in", works_cited["hanging_indent_in"],
            profile.works_cited.hanging_indent_in,
            rendered(wc_hang.get("left_indent_in")),
        ))

    toc = rules.get("toc") or {}
    if "native_word_field" in toc:
        results.append(_row("toc.native_word_field", toc["native_word_field"],
                            profile.toc.native_word_field,
                            rendered(fmt.get("toc_native_word_field_present"))))

    known = {
        "page_size", "margins_in", "font", "font_size_pt", "line_spacing",
        "first_line_indent_in", "justify_body", "chapter_title", "pagination",
        "quotations", "works_cited", "toc",
    }
    for key in sorted(set(rules) - known):
        results.append(RuleResult(
            key, rules[key], "(no comparable profile setting)", "unverifiable",
            note="rule key not mapped to any profile/renderer setting",
        ))
    return results


def _style_from_fmt(fmt_value: str | None) -> str | None:
    """Map an OOXML page-number format back to the profile vocabulary."""
    mapping = {"lowerRoman": "lower_roman", "upperRoman": "upper_roman",
               "decimal": "arabic"}
    return mapping.get(fmt_value or "", fmt_value)


def print_table(results: list[RuleResult]) -> None:
    """Print the fixed-width deviation table."""
    def cell(value: Any, width: int) -> str:
        text = json.dumps(value) if isinstance(value, (dict, list, bool)) else str(value)
        return text[: width - 1] + "…" if len(text) > width else text.ljust(width)

    widths = (34, 26, 40, 13)
    header = ("RULE", "EXPECTED", "ACTUAL", "STATUS")
    print("  ".join(cell(h, w) for h, w in zip(header, widths)))
    print("  ".join("-" * w for w in widths))
    for r in results:
        status = r.status.upper() if r.status == "deviation" else r.status
        print("  ".join((cell(r.rule, widths[0]), cell(r.expected, widths[1]),
                         cell(r.actual, widths[2]), cell(status, widths[3]))))
        if r.note:
            print(f"    note: {r.note}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True,
                        help=f"Registered profile: {', '.join(sorted(PROFILE_LABELS))}")
    parser.add_argument("--rules", required=True, type=Path,
                        help="JSON (or Markdown with a ```json block) rules file.")
    parser.add_argument("--fingerprint", type=Path, default=None,
                        help="Optional fingerprint.json (default: the profile's golden).")
    args = parser.parse_args(argv)

    if args.profile not in PROFILE_LABELS:
        print(f"ERROR: unknown profile {args.profile!r}. "
              f"Registered: {', '.join(sorted(PROFILE_LABELS))}")
        return 2
    if not args.rules.exists():
        print(f"ERROR: rules file not found: {args.rules}")
        return 2

    try:
        rules_doc = load_rules(args.rules)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not parse rules file: {exc}")
        return 2

    profile, version_label = resolve_phase1_profile(args.profile)

    fp_path = args.fingerprint or _fingerprint_path(args.profile, version_label)
    fingerprint: dict[str, Any] | None = None
    if fp_path.exists():
        fingerprint = json.loads(fp_path.read_text(encoding="utf-8"))

    print(f"Profile:      {args.profile}  [{version_label}]")
    print(f"Rules file:   {args.rules}")
    for meta_key in ("institution", "programme", "source", "status"):
        if meta_key in rules_doc:
            print(f"  {meta_key}: {rules_doc[meta_key]}")
    print(f"Fingerprint:  {fp_path if fingerprint else 'none (config-only comparison; run generate_profile_golden.py first)'}")
    print()

    results = compare(args.profile, profile, rules_doc["rules"], fingerprint)
    print_table(results)

    deviations = sum(1 for r in results if r.status == "deviation")
    unverifiable = sum(1 for r in results if r.status == "unverifiable")
    matches = sum(1 for r in results if r.status == "match")
    print()
    print(f"Summary: {matches} match, {deviations} deviation(s), {unverifiable} unverifiable "
          f"of {len(results)} rule(s).")
    if unverifiable:
        print("Unverifiable rules require manual review against the official guide.")
    print("This comparison is engineering evidence, not institutional certification.")
    return 1 if deviations else 0


if __name__ == "__main__":
    raise SystemExit(main())
