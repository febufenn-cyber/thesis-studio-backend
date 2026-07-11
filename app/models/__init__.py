"""ORM models. Importing this module registers all tables on the Base metadata."""

from app.models.auth_token import AuthToken
from app.models.event import Event
from app.models.export import Export
from app.models.file import File
from app.models.institution import Institution
from app.models.message import Message
from app.models.project import Project
from app.models.quote import Quote
from app.models.session import ThesisSession
from app.models.source import Source
from app.models.style_profile import StyleProfile
from app.models.usage_event import UsageEvent
from app.models.user import User

__all__ = [
    "AuthToken",
    "Event",
    "Export",
    "File",
    "Institution",
    "Message",
    "Project",
    "Quote",
    "ThesisSession",
    "Source",
    "StyleProfile",
    "UsageEvent",
    "User",
]
