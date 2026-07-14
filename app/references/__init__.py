"""Reference enrichment and reconciliation (docs/LLD.md 3.2).

Resolve ``[VERIFY]`` placeholders on registry sources against bibliographic
authorities (Crossref, OpenAlex, arXiv, OpenLibrary), reconcile the results with
per-field confidence, retraction-check them, and write back only high-confidence
values — anything unresolved stays ``[VERIFY]`` (never-guess, DESIGN.md rule 2).
"""
