"""Bounded, provenance-rich context compilation for grounded AI work."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.safety import scan_untrusted_text, system_safety_policy, wrap_untrusted
from app.ai.schemas import AIScope, GroundedAIOutput
from app.ai.task_registry import TaskSpec
from app.canonical.model import ThesisDocument
from app.core.config import get_settings
from app.models.ai_memory import AIMemory
from app.models.ai_message import AIMessage
from app.models.project import Project
from app.models.quote import Quote
from app.models.review_item import ReviewItem
from app.models.source import Source
from app.services.registry_scope import active_revision_rows


class ContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompiledContext:
    system_prompt: str
    user_prompt: str
    manifest: dict[str, Any]
    context_hash: str


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _block_text(block) -> str:
    if hasattr(block, "runs"):
        return "".join(run.text for run in block.runs)
    if hasattr(block, "text"):
        return str(block.text)
    if hasattr(block, "lines"):
        return "\n".join(block.lines)
    if hasattr(block, "kind"):
        return f"[{block.kind}: {getattr(block, 'note', '')}]"
    return _json(block.model_dump(mode="json"))


def _chapter_payload(chapter, *, include_blocks: bool) -> dict:
    payload: dict[str, Any] = {
        "id": str(chapter.id),
        "number": chapter.number,
        "title": chapter.title,
        "status": chapter.status,
        "block_count": len(chapter.blocks),
    }
    if include_blocks:
        payload["blocks"] = [
            {
                "id": str(block.id),
                "type": block.type,
                "text": _block_text(block),
                "quote_id": str(getattr(block, "quote_id", "") or "") or None,
                "source_paragraph_index": getattr(block, "source_paragraph_index", None),
            }
            for block in chapter.blocks
        ]
    return payload


def _safe_project_meta(project: Project) -> dict:
    meta = project.meta or {}
    return {
        "project_title": project.title,
        "document_type": project.doc_type,
        "format_profile": project.format_profile,
        "research_question": meta.get("research_question"),
        "thesis_statement": meta.get("thesis_statement"),
        "primary_texts": meta.get("primary_texts") or meta.get("primary_text"),
        "framework": meta.get("framework"),
        "methodology": meta.get("methodology"),
        "degree": meta.get("degree"),
        "department": meta.get("department"),
    }


def _selected_document_context(document: ThesisDocument, scope: AIScope) -> tuple[dict, list[str], list[str]]:
    chapter_by_id = {str(chapter.id): chapter for chapter in document.chapters}
    block_locations: dict[str, tuple[Any, int]] = {}
    for chapter in document.chapters:
        for index, block in enumerate(chapter.blocks):
            block_locations[str(block.id)] = (chapter, index)

    selected_chapters: list[Any] = []
    selected_blocks: list[str] = []

    if scope.type == "project":
        return {
            "chapter_map": [_chapter_payload(chapter, include_blocks=False) for chapter in document.chapters]
        }, [str(chapter.id) for chapter in document.chapters], []

    if scope.type == "chapter":
        chapter = chapter_by_id.get(str(scope.chapter_id))
        if chapter is None:
            raise ContextError("The selected chapter no longer exists.")
        selected_chapters = [chapter]
    elif scope.type in {"block", "selection"}:
        ids = [str(scope.block_id)] if scope.type == "block" else [str(value) for value in scope.block_ids]
        seen_chapters: set[str] = set()
        slices: list[dict] = []
        for block_id in ids:
            location = block_locations.get(block_id)
            if location is None:
                raise ContextError(f"Selected block {block_id} no longer exists.")
            chapter, index = location
            selected_blocks.append(block_id)
            if str(chapter.id) not in seen_chapters:
                selected_chapters.append(chapter)
                seen_chapters.add(str(chapter.id))
            start, end = max(0, index - 2), min(len(chapter.blocks), index + 3)
            slices.append(
                {
                    "chapter_id": str(chapter.id),
                    "chapter_number": chapter.number,
                    "chapter_title": chapter.title,
                    "selected_block_id": block_id,
                    "nearby_blocks": [
                        {
                            "id": str(block.id),
                            "type": block.type,
                            "selected": str(block.id) == block_id,
                            "text": _block_text(block),
                            "quote_id": str(getattr(block, "quote_id", "") or "") or None,
                        }
                        for block in chapter.blocks[start:end]
                    ],
                }
            )
        return {"selection": slices}, [str(ch.id) for ch in selected_chapters], selected_blocks
    else:
        # Review/source/quote scopes get their exact object below and a compact chapter map here.
        return {
            "chapter_map": [_chapter_payload(chapter, include_blocks=False) for chapter in document.chapters]
        }, [], []

    return {
        "chapters": [_chapter_payload(chapter, include_blocks=True) for chapter in selected_chapters]
    }, [str(chapter.id) for chapter in selected_chapters], selected_blocks


def _clip(serialized: str, remaining: int) -> tuple[str, int, bool]:
    if remaining <= 0:
        return "", 0, True
    if len(serialized) <= remaining:
        return serialized, len(serialized), False
    suffix = "\n[CONTEXT TRUNCATED BY SERVER TOKEN BUDGET]"
    take = max(0, remaining - len(suffix))
    return serialized[:take] + suffix, remaining, True


async def compile_context(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    *,
    thread_id: UUID,
    spec: TaskSpec,
    scope: AIScope,
    user_request: str,
) -> CompiledContext:
    settings = get_settings()
    document = ThesisDocument.model_validate(
        {
            "schema_version": project.canonical_schema_version,
            "meta": project.meta or {},
            "front_matter": project.front_matter or [],
            "chapters": project.chapters or [],
            "works_cited": project.works_cited or [],
        }
    )
    selected_payload, chapter_ids, block_ids = _selected_document_context(document, scope)

    all_sources = list(
        (
            await db.execute(
                select(Source).where(Source.project_id == project.id, Source.user_id == user_id)
            )
        ).scalars()
    )
    all_quotes = list(
        (
            await db.execute(
                select(Quote).where(Quote.project_id == project.id, Quote.user_id == user_id)
            )
        ).scalars()
    )
    sources = active_revision_rows(all_sources, project.active_revision_id)
    quotes = active_revision_rows(all_quotes, project.active_revision_id)

    if scope.type == "source":
        sources = [source for source in sources if source.id == scope.source_id]
        if not sources:
            raise ContextError("The selected source is not active in this project revision.")
    if scope.type == "quote":
        quotes = [quote for quote in quotes if quote.id == scope.quote_id]
        if not quotes:
            raise ContextError("The selected quotation is not active in this project revision.")

    review_query = select(ReviewItem).where(
        ReviewItem.project_id == project.id,
        ReviewItem.user_id == user_id,
        ReviewItem.status == "open",
    )
    if scope.type == "review":
        review_query = review_query.where(ReviewItem.id == scope.review_item_id)
    elif block_ids:
        review_query = review_query.where(ReviewItem.block_id.in_([UUID(value) for value in block_ids]))
    reviews = list((await db.execute(review_query.order_by(ReviewItem.created_at.asc()).limit(60))).scalars())
    if scope.type == "review" and not reviews:
        raise ContextError("The selected review item no longer exists or is no longer open.")

    memory_query = select(AIMemory).where(
        AIMemory.project_id == project.id,
        AIMemory.user_id == user_id,
        AIMemory.stale.is_(False),
    )
    memories = list((await db.execute(memory_query.order_by(AIMemory.updated_at.desc()).limit(30))).scalars())

    recent_messages = list(
        (
            await db.execute(
                select(AIMessage)
                .where(
                    AIMessage.thread_id == thread_id,
                    AIMessage.project_id == project.id,
                    AIMessage.user_id == user_id,
                )
                .order_by(AIMessage.created_at.desc())
                .limit(settings.AI_RECENT_THREAD_MESSAGES)
            )
        ).scalars()
    )
    recent_messages.reverse()

    source_payload = [
        {
            "id": str(source.id),
            "kind": source.kind,
            "fields": source.fields,
            "verified": source.verified,
            "parse_status": source.parse_status,
            "raw_entry": source.raw_entry,
        }
        for source in sources[:80]
    ]
    quote_payload = [
        {
            "id": str(quote.id),
            "source_id": str(quote.source_id),
            "page_or_loc": quote.page_or_loc,
            "text": quote.text,
            "verified": quote.verified,
        }
        for quote in sorted(quotes, key=lambda row: (not row.verified, row.created_at))[:80]
    ]
    review_payload = [
        {
            "id": str(item.id),
            "rule": item.rule,
            "category": item.category,
            "severity": item.severity,
            "title": item.title,
            "explanation": item.explanation,
            "location": item.location,
        }
        for item in reviews
    ]
    memory_payload = [
        {
            "id": str(memory.id),
            "scope_type": memory.scope_type,
            "scope_key": memory.scope_key,
            "kind": memory.kind,
            "content": memory.content,
            "based_on_document_version": memory.based_on_document_version,
        }
        for memory in memories
    ]
    conversation_payload = [
        {"role": message.role, "content": message.content, "task_mode": message.task_mode}
        for message in recent_messages
    ]

    untrusted_sections = [
        ("canonical_project_metadata", _json(_safe_project_meta(project))),
        ("selected_canonical_document", _json(selected_payload)),
        ("registered_sources", _json(source_payload)),
        ("registered_quotations", _json(quote_payload)),
        ("open_review_findings", _json(review_payload)),
        ("project_memory_navigation_aids", _json(memory_payload)),
        ("recent_local_thread", _json(conversation_payload)),
    ]
    injection_findings: list[dict[str, Any]] = []
    remaining = settings.AI_MAX_CONTEXT_CHARS
    rendered_sections: list[str] = []
    omitted: list[str] = []
    truncated: list[str] = []
    for label, raw in untrusted_sections:
        for finding in scan_untrusted_text(raw):
            injection_findings.append({"section": label, **finding})
        wrapped = wrap_untrusted(label, raw)
        clipped, used, was_truncated = _clip(wrapped, remaining)
        remaining -= used
        if not clipped:
            omitted.append(label)
            continue
        rendered_sections.append(clipped)
        if was_truncated:
            truncated.append(label)

    schema_text = _json(GroundedAIOutput.model_json_schema())
    policy = project.ai_policy or {}
    system_prompt = "\n\n".join(
        [
            system_safety_policy(),
            f"TASK MODE: {spec.mode}\nTASK PURPOSE: {spec.description}\nRISK: {spec.risk_level}",
            "PROJECT AI POLICY:\n" + _json(policy),
            "ALLOWED PROPOSAL OPERATION KINDS:\n" + _json(list(spec.allowed_operations)),
            "REQUIRED OUTPUT JSON SCHEMA:\n" + schema_text,
        ]
    )
    user_prompt = "\n\n".join(
        [
            "SCOPE MANIFEST:\n" + _json(scope.model_dump(mode="json")),
            *rendered_sections,
            "CURRENT USER REQUEST:\n" + user_request,
            "Return a single JSON object. Explain what you read, what you inferred, what evidence you used, what remains missing, and what the human must decide.",
        ]
    )

    manifest: dict[str, Any] = {
        "document_version": project.document_version,
        "canonical_schema_version": project.canonical_schema_version,
        "active_revision_id": str(project.active_revision_id) if project.active_revision_id else None,
        "task_mode": spec.mode,
        "scope": scope.model_dump(mode="json"),
        "chapter_ids": chapter_ids,
        "block_ids": block_ids,
        "block_hashes": {
            block_id: _hash(
                next(
                    block.model_dump(mode="json")
                    for chapter in document.chapters
                    for block in chapter.blocks
                    if str(block.id) == block_id
                )
            )
            for block_id in block_ids
        },
        "source_ids": [str(source.id) for source in sources[:80]],
        "verified_source_ids": [str(source.id) for source in sources if source.verified][:80],
        "quote_ids": [str(quote.id) for quote in quotes[:80]],
        "verified_quote_ids": [str(quote.id) for quote in quotes if quote.verified][:80],
        "review_item_ids": [str(item.id) for item in reviews],
        "memory_ids": [str(memory.id) for memory in memories],
        "recent_message_ids": [str(message.id) for message in recent_messages],
        "injection_findings": injection_findings,
        "omitted_sections": omitted,
        "truncated_sections": truncated,
        "context_chars": len(user_prompt),
        "external_research_available": False,
    }
    context_hash = _hash({"system": system_prompt, "user": user_prompt, "manifest": manifest})
    return CompiledContext(system_prompt, user_prompt, manifest, context_hash)
