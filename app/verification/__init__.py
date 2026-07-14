"""Quotation and claim verification (docs/LLD.md 3.3).

Confirms that a quoted passage appears verbatim in its cited source and flags
transcription/paraphrase drift. Advisory only: findings never flip the
human-owned ``Quote.verified`` bit and a missing/unreadable source fails closed
to ``unverifiable`` (never ``verified``).
"""
