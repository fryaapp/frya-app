from functools import lru_cache

from app.accounting_analysis.akaunting_reconciliation_service import AkauntingReconciliationService
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
from app.telegram.dedup import TelegramUpdateDeduplicator


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
def get_rule_change_audit_repository() -> RuleChangeAuditRepository:
    settings = get_settings()
    return RuleChangeAuditRepository(settings.database_url)


@lru_cache
def get_rule_change_audit_service() -> RuleChangeAuditService:
    return RuleChangeAuditService(get_rule_change_audit_repository())
