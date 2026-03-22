from functools import lru_cache

from app.accounting_analysis.akaunting_reconciliation_service import AkauntingReconciliationService
from app.banking.reconciliation_context import ReconciliationContextService
from app.banking.review_service import BankReconciliationReviewService
from app.banking.service import BankTransactionService
from app.accounting_analysis.review_service import AccountingOperatorReviewService
from app.accounting_analysis.service import AccountingAnalysisService
from app.connectors.accounting_akaunting import AkauntingConnector
from app.approvals.repository import ApprovalRepository
from app.approvals.service import ApprovalService
from app.audit.repository import AuditRepository
from app.audit.service import AuditService
from app.config import get_settings
from app.connectors.dms_paperless import PaperlessConnector
from app.connectors.notifications_telegram import TelegramConnector
from app.connectors.workflow_n8n import N8NConnector
from app.document_analysis.service import DocumentAnalysisService
from app.memory.file_store import FileStore
from app.open_items.repository import OpenItemsRepository
from app.open_items.service import OpenItemsService
from app.problems.repository import ProblemCaseRepository
from app.problems.service import ProblemCaseService
from app.rules.audit_repository import RuleChangeAuditRepository
from app.rules.audit_service import RuleChangeAuditService
from app.rules.loader import RuleLoader
from app.rules.policy_access import PolicyAccessLayer
from app.telegram.clarification_repository import TelegramClarificationRepository
from app.telegram.clarification_service import TelegramClarificationService
from app.telegram.communicator.memory.chat_history_store import ChatHistoryStore
from app.telegram.communicator.memory.conversation_store import ConversationMemoryStore
from app.telegram.communicator.memory.user_store import UserMemoryStore
from app.telegram.communicator.service import TelegramCommunicatorService
from app.telegram.document_analyst_deep_path_service import TelegramDocumentAnalystDeepPathService
from app.telegram.document_analyst_followup_service import TelegramDocumentAnalystFollowupService
from app.telegram.document_analyst_merge_service import TelegramDocumentAnalystMergeService
from app.telegram.document_analyst_ocr_recheck_service import TelegramDocumentAnalystOcrRecheckService
from app.telegram.document_analyst_review_service import TelegramDocumentAnalystReviewService
from app.telegram.document_analyst_start_service import TelegramDocumentAnalystStartService
from app.telegram.media_service import TelegramMediaIngressService
from app.telegram.notification_service import TelegramNotificationService
from app.telegram.repository import TelegramCaseLinkRepository
from app.telegram.service import TelegramCaseLinkService
from app.llm_config import LLMConfigRepository
from app.telegram.dedup import TelegramUpdateDeduplicator
from app.email_intake.repository import EmailIntakeRepository
from app.email_intake.service import EmailIntakeService
from app.auth.user_repository import UserRepository
from app.auth.reset_service import PasswordResetService
from app.email.mail_service import MailService
from app.auth.tenant_repository import TenantRepository
from app.case_engine.repository import CaseRepository
from app.bulk_upload.repository import BulkUploadRepository
from app.bulk_upload.service import BulkUploadService


@lru_cache
def get_file_store() -> FileStore:
    settings = get_settings()
    return FileStore(settings.data_dir)


@lru_cache
def get_rule_loader() -> RuleLoader:
    settings = get_settings()
    return RuleLoader(settings.rules_dir)


@lru_cache
def get_policy_access_layer() -> PolicyAccessLayer:
    return PolicyAccessLayer(get_rule_loader())


@lru_cache
def get_audit_repository() -> AuditRepository:
    settings = get_settings()
    return AuditRepository(settings.database_url)


@lru_cache
def get_audit_service() -> AuditService:
    return AuditService(get_audit_repository())


@lru_cache
def get_approval_repository() -> ApprovalRepository:
    settings = get_settings()
    return ApprovalRepository(settings.database_url)


@lru_cache
def get_approval_service() -> ApprovalService:
    return ApprovalService(get_approval_repository(), open_items_service=get_open_items_service())


@lru_cache
def get_open_items_repository() -> OpenItemsRepository:
    settings = get_settings()
    return OpenItemsRepository(settings.database_url)


@lru_cache
def get_n8n_connector() -> N8NConnector:
    settings = get_settings()
    return N8NConnector(settings.n8n_base_url, settings.n8n_token)


@lru_cache
def get_paperless_connector() -> PaperlessConnector:
    settings = get_settings()
    return PaperlessConnector(settings.paperless_base_url, settings.paperless_token)


@lru_cache
def get_document_analysis_service() -> DocumentAnalysisService:
    return DocumentAnalysisService()


@lru_cache
def get_accounting_analysis_service() -> AccountingAnalysisService:
    return AccountingAnalysisService()


@lru_cache
def get_telegram_connector() -> TelegramConnector:
    settings = get_settings()
    return TelegramConnector(settings.telegram_bot_token)


@lru_cache
def get_telegram_deduplicator() -> TelegramUpdateDeduplicator:
    settings = get_settings()
    return TelegramUpdateDeduplicator(settings.redis_url, settings.telegram_dedup_ttl_seconds)


@lru_cache
def get_telegram_case_link_repository() -> TelegramCaseLinkRepository:
    settings = get_settings()
    return TelegramCaseLinkRepository(settings.database_url)


@lru_cache
def get_telegram_case_link_service() -> TelegramCaseLinkService:
    return TelegramCaseLinkService(get_telegram_case_link_repository())


@lru_cache
def get_telegram_clarification_repository() -> TelegramClarificationRepository:
    settings = get_settings()
    return TelegramClarificationRepository(settings.database_url)


@lru_cache
def get_telegram_clarification_service() -> TelegramClarificationService:
    return TelegramClarificationService(
        get_telegram_clarification_repository(),
        get_audit_service(),
        get_open_items_service(),
        get_telegram_connector(),
        get_telegram_notification_service(),
    )


@lru_cache
def get_telegram_notification_service() -> TelegramNotificationService:
    return TelegramNotificationService(
        get_audit_service(),
        get_telegram_case_link_service(),
        get_telegram_connector(),
    )


@lru_cache
def get_telegram_media_ingress_service() -> TelegramMediaIngressService:
    settings = get_settings()
    allowed_mime_types = {item.strip() for item in settings.telegram_media_allowed_mime_types.split(',') if item.strip()}
    allowed_extensions = {item.strip().lower() for item in settings.telegram_media_allowed_extensions.split(',') if item.strip()}
    return TelegramMediaIngressService(
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
        telegram_connector=get_telegram_connector(),
        telegram_case_link_service=get_telegram_case_link_service(),
        file_store=get_file_store(),
        max_bytes=settings.telegram_media_max_bytes,
        allowed_mime_types=allowed_mime_types,
        allowed_extensions=allowed_extensions,
        paperless_connector=get_paperless_connector(),
    )


@lru_cache
def get_telegram_document_analyst_followup_service() -> TelegramDocumentAnalystFollowupService:
    return TelegramDocumentAnalystFollowupService(
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
        telegram_case_link_service=get_telegram_case_link_service(),
        telegram_clarification_service=get_telegram_clarification_service(),
    )


@lru_cache
def get_telegram_document_analyst_deep_path_service() -> TelegramDocumentAnalystDeepPathService:
    return TelegramDocumentAnalystDeepPathService(
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
    )


@lru_cache
def get_telegram_document_analyst_merge_service() -> TelegramDocumentAnalystMergeService:
    return TelegramDocumentAnalystMergeService(
        audit_service=get_audit_service(),
    )


@lru_cache
def get_telegram_document_analyst_ocr_recheck_service() -> TelegramDocumentAnalystOcrRecheckService:
    return TelegramDocumentAnalystOcrRecheckService(
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
    )


@lru_cache
def get_telegram_document_analyst_review_service() -> TelegramDocumentAnalystReviewService:
    return TelegramDocumentAnalystReviewService(
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
        followup_service=get_telegram_document_analyst_followup_service(),
        deep_path_service=get_telegram_document_analyst_deep_path_service(),
    )


def get_telegram_communicator_service() -> TelegramCommunicatorService:
    """Stateless — no lru_cache needed."""
    return TelegramCommunicatorService()


@lru_cache
def get_communicator_conversation_store() -> ConversationMemoryStore:
    settings = get_settings()
    return ConversationMemoryStore(settings.redis_url)


@lru_cache
def get_communicator_user_store() -> UserMemoryStore:
    settings = get_settings()
    return UserMemoryStore(settings.database_url)


@lru_cache
def get_chat_history_store() -> ChatHistoryStore:
    settings = get_settings()
    return ChatHistoryStore(settings.redis_url)


@lru_cache
def get_telegram_document_analyst_start_service() -> TelegramDocumentAnalystStartService:
    return TelegramDocumentAnalystStartService(
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
        review_service=get_telegram_document_analyst_review_service(),
        merge_service=get_telegram_document_analyst_merge_service(),
    )


@lru_cache
def get_open_items_service() -> OpenItemsService:
    settings = get_settings()
    return OpenItemsService(get_open_items_repository(), settings.redis_url, workflow_connector=get_n8n_connector())


@lru_cache
def get_problem_case_repository() -> ProblemCaseRepository:
    settings = get_settings()
    return ProblemCaseRepository(settings.database_url)


@lru_cache
def get_problem_case_service() -> ProblemCaseService:
    return ProblemCaseService(get_problem_case_repository())


@lru_cache
def get_accounting_operator_review_service() -> AccountingOperatorReviewService:
    return AccountingOperatorReviewService(
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
        problem_service=get_problem_case_service(),
    )


@lru_cache
def get_akaunting_connector() -> AkauntingConnector:
    settings = get_settings()
    return AkauntingConnector(
        settings.akaunting_base_url,
        token=settings.akaunting_token,
        email=settings.akaunting_email,
        password=settings.akaunting_password,
    )


@lru_cache
def get_akaunting_reconciliation_service() -> AkauntingReconciliationService:
    return AkauntingReconciliationService(
        akaunting_connector=get_akaunting_connector(),
        audit_service=get_audit_service(),
    )


@lru_cache
def get_bank_transaction_service() -> BankTransactionService:
    return BankTransactionService(
        akaunting_connector=get_akaunting_connector(),
        audit_service=get_audit_service(),
    )


@lru_cache
def get_reconciliation_context_service() -> ReconciliationContextService:
    return ReconciliationContextService(
        bank_service=get_bank_transaction_service(),
        akaunting_connector=get_akaunting_connector(),
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
    )


@lru_cache
def get_bank_reconciliation_review_service() -> BankReconciliationReviewService:
    return BankReconciliationReviewService(
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
        reconciliation_context_service=get_reconciliation_context_service(),
    )


@lru_cache
def get_llm_config_repository() -> LLMConfigRepository:
    settings = get_settings()
    return LLMConfigRepository(settings.database_url, settings.redis_url, settings.config_encryption_key)


@lru_cache
def get_rule_change_audit_repository() -> RuleChangeAuditRepository:
    settings = get_settings()
    return RuleChangeAuditRepository(settings.database_url)


@lru_cache
def get_rule_change_audit_service() -> RuleChangeAuditService:
    return RuleChangeAuditService(get_rule_change_audit_repository())


@lru_cache
def get_email_intake_repository() -> EmailIntakeRepository:
    settings = get_settings()
    return EmailIntakeRepository(settings.database_url)


@lru_cache
def get_email_intake_service() -> EmailIntakeService:
    settings = get_settings()
    return EmailIntakeService(
        repository=get_email_intake_repository(),
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
        file_store=get_file_store(),
        mailgun_signing_key=settings.mailgun_webhook_signing_key,
    )


@lru_cache
def get_user_repository() -> UserRepository:
    settings = get_settings()
    return UserRepository(settings.database_url)


@lru_cache
def get_password_reset_service() -> PasswordResetService:
    settings = get_settings()
    return PasswordResetService(settings.redis_url)


@lru_cache
def get_mail_service() -> MailService:
    settings = get_settings()
    return MailService(
        audit_service=get_audit_service(),
        database_url=settings.database_url,
        mailgun_api_key=settings.mailgun_api_key,
        mailgun_domain=settings.mailgun_domain,
        mailgun_from=settings.mailgun_from,
        encryption_key=settings.config_encryption_key,
        brevo_api_key=settings.brevo_api_key,
        mail_provider=settings.mail_provider,
    )


@lru_cache
def get_tenant_repository() -> TenantRepository:
    settings = get_settings()
    return TenantRepository(settings.database_url)


@lru_cache
def get_case_repository() -> CaseRepository:
    settings = get_settings()
    return CaseRepository(settings.database_url)


@lru_cache
def get_bulk_upload_repository() -> BulkUploadRepository:
    settings = get_settings()
    return BulkUploadRepository(settings.database_url)


@lru_cache
def get_bulk_upload_service() -> BulkUploadService:
    return BulkUploadService(
        bulk_repo=get_bulk_upload_repository(),
        case_repo=get_case_repository(),
        paperless=get_paperless_connector(),
        audit_service=get_audit_service(),
    )
