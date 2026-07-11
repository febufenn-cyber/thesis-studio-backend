"""ORM models. Importing this module registers all tables on Base metadata."""

from app.models.auth_token import AuthToken
from app.models.citation_resolution import CitationResolution
from app.models.document_command import DocumentCommand
from app.models.document_preview import DocumentPreview
from app.models.document_snapshot import DocumentSnapshot
from app.models.event import Event
from app.models.export import Export
from app.models.file import File
from app.models.institution import Institution
from app.models.job import Job
from app.models.manuscript_revision import ManuscriptRevision
from app.models.message import Message
from app.models.project import Project
from app.models.quote import Quote
from app.models.review_item import ReviewItem
from app.models.session import ThesisSession
from app.models.source import Source
from app.models.style_profile import StyleProfile
from app.models.usage_event import UsageEvent
from app.models.user import User

__all__ = [
    "AuthToken",
    "CitationResolution",
    "DocumentCommand",
    "DocumentPreview",
    "DocumentSnapshot",
    "Event",
    "Export",
    "File",
    "Institution",
    "Job",
    "ManuscriptRevision",
    "Message",
    "Project",
    "Quote",
    "ReviewItem",
    "ThesisSession",
    "Source",
    "StyleProfile",
    "UsageEvent",
    "User",
]
