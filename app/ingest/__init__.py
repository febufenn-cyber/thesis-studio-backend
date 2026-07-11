"""Mode B ingestion engine (v2 M3).

Pipeline: docx_extract (styled paragraph stream) -> structure (canonical
ThesisDocument) -> citations (registry candidates) -> verifier (blocking
pre-export audit). Pure logic — no routes, no LLM calls; the operator API
wraps these.
"""
