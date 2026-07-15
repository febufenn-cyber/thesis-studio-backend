"""ORM models. Importing this module registers all tables on Base metadata."""

from app.models.ai_memory import AIMemory
from app.models.ai_message import AIMessage
from app.models.ai_proposal import AIProposal
from app.models.ai_run import AIRun
from app.models.ai_thread import AIThread
from app.models.auth_token import AuthToken
from app.models.citation_resolution import CitationResolution
from app.models.commercial import (
    AIProvider,
    AIProviderHealth,
    ApplicationSession,
    BackupRecord,
    BillingCustomer,
    BillingEvent,
    ConsentRecord,
    CostLedgerEntry,
    DataInventoryRecord,
    DataLifecycleJob,
    DeploymentRecord,
    EditionVersion,
    EntitlementDefinition,
    EntitlementGrant,
    FeatureFlag,
    Invoice,
    Payment,
    PlatformBudgetControl,
    PrivacyNoticeVersion,
    ProcessingPurpose,
    ProductEdition,
    RecoveryPolicy,
    ReleaseRecord,
    RestoreDrill,
    RolloutAssignment,
    SecurityRequirementEvidence,
    ServiceComponent,
    ServiceIncident,
    SLIMeasurement,
    SLODefinition,
    SubprocessorRecord,
    Subscription,
    SubscriptionItem,
    SupportAction,
    TenantBudget,
    UsageLedgerEntry,
)
from app.models.document_command import DocumentCommand
from app.models.document_preview import DocumentPreview
from app.models.document_snapshot import DocumentSnapshot
from app.models.event import Event
from app.models.export import Export
from app.models.file import File
from app.models.institution import Institution
from app.models.institutional_governance import (
    ExternalReviewGrant,
    InstitutionalPolicyVersion,
    InstitutionalProfileVersion,
    OfficialTemplateVersion,
    RetentionPolicy,
    SubmissionPackage,
)
from app.models.job import Job
from app.models.manuscript_revision import ManuscriptRevision
from app.models.message import Message
from app.models.presence import ProjectPresence
from app.models.project import Project
from app.models.quote import Quote
from app.models.research_candidate import ResearchCandidate
from app.models.review_collaboration import (
    ApprovalRecord,
    Attestation,
    CollaborationComment,
    HumanSuggestion,
    ReviewCycle,
    SupervisorInstruction,
)
from app.models.ai_use_statement import AIUseStatement
from app.models.api_key import ApiKey
from app.models.deposit import Deposit
from app.models.quote_verification import QuoteVerification
from app.models.research_consent import ResearchConsent
from app.models.resolution_record import ResolutionRecord
from app.models.review_item import ReviewItem
from app.models.session import ThesisSession
from app.models.source import Source
from app.models.source_field_provenance import SourceFieldProvenance
from app.models.supervision import BlockComment, CommitteeMembership
from app.models.style_profile import StyleProfile
from app.models.tenancy import (
    DataLifecycleRequest,
    Department,
    MembershipInvitation,
    Notification,
    NotificationPreference,
    OrganizationMembership,
    ProjectHandoff,
    ProjectMembership,
    ReviewAssignment,
    SupportAccessGrant,
)
from app.models.usage_event import UsageEvent
from app.models.user import User

# Register transaction-local Phase 4 governance hooks.
from app.collaboration import editor_hooks as _editor_hooks  # noqa: E402,F401
from app.collaboration import sealed_guard as _sealed_guard  # noqa: E402,F401

__all__ = [
    "AIMemory", "AIMessage", "AIProposal", "AIRun", "AIThread", "AuthToken",
    "CitationResolution", "DocumentCommand", "DocumentPreview", "DocumentSnapshot",
    "Event", "Export", "File", "Institution", "Job", "ManuscriptRevision", "Message",
    "ProjectPresence", "Project", "Quote", "ResearchCandidate", "ReviewItem",
    "ThesisSession", "Source", "SourceFieldProvenance", "ResolutionRecord",
    "AIUseStatement", "QuoteVerification", "CommitteeMembership", "BlockComment",
    "ResearchConsent", "ApiKey", "Deposit", "StyleProfile", "UsageEvent", "User", "Department",
    "OrganizationMembership", "ProjectMembership", "MembershipInvitation",
    "ReviewAssignment", "ProjectHandoff", "Notification", "NotificationPreference",
    "DataLifecycleRequest", "SupportAccessGrant", "ReviewCycle",
    "CollaborationComment", "HumanSuggestion", "ApprovalRecord",
    "SupervisorInstruction", "Attestation", "InstitutionalPolicyVersion",
    "InstitutionalProfileVersion", "OfficialTemplateVersion", "RetentionPolicy",
    "SubmissionPackage", "ExternalReviewGrant", "ProductEdition", "EditionVersion",
    "EntitlementDefinition", "EntitlementGrant", "UsageLedgerEntry", "CostLedgerEntry",
    "BillingCustomer", "Subscription", "SubscriptionItem", "Invoice", "Payment",
    "BillingEvent", "TenantBudget", "PlatformBudgetControl", "ApplicationSession",
    "AIProvider", "AIProviderHealth", "FeatureFlag", "RolloutAssignment",
    "ReleaseRecord", "DeploymentRecord", "ServiceComponent", "ServiceIncident",
    "SLODefinition", "SLIMeasurement", "RecoveryPolicy", "BackupRecord",
    "RestoreDrill", "PrivacyNoticeVersion", "ConsentRecord", "ProcessingPurpose",
    "DataInventoryRecord", "SubprocessorRecord", "SecurityRequirementEvidence",
    "SupportAction", "DataLifecycleJob",
]
