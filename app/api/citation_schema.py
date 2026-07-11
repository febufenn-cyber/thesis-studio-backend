"""Citation source schemas shared by the renderer and Phase 2 forms."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.renderers.works_cited import _REQUIRED


router = APIRouter(tags=["phase2-citations"])

_OPTIONAL: dict[str, tuple[str, ...]] = {
    "book": ("edition", "doi_or_url"),
    "translated_book": ("edition", "doi_or_url"),
    "chapter_in_collection": ("volume", "edition", "doi_or_url"),
    "journal": ("doi_or_url",),
    "journal_db": ("access_date",),
    "web": ("author", "pub_date", "access_date"),
    "film": ("performers", "medium"),
}


@router.get("/citation-source-kinds")
async def citation_source_kinds(current_user: CurrentUser) -> dict:
    """Return the exact source kinds/fields accepted by final rendering."""

    return {
        "kinds": {
            kind: {
                "required": list(fields),
                "optional": list(_OPTIONAL.get(kind, ())),
                "label": kind.replace("_", " ").title(),
            }
            for kind, fields in _REQUIRED.items()
        },
        "policy": (
            "Unknown source kinds may be preserved as raw entries for review, "
            "but only listed kinds can produce a final formatted Works Cited entry."
        ),
    }
