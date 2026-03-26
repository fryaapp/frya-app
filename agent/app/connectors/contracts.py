from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class DocumentRef:
    doc_id: str
    title: str | None = None


@dataclass(slots=True)
class AccountingRef:
    object_id: str
    object_type: str


@dataclass(slots=True)
class NotificationMessage:
    target: str
    text: str
    metadata: dict | None = None
    reply_markup: dict | None = None


class DMSConnector(ABC):
    @abstractmethod
    async def get_document(self, doc_id: str) -> dict: ...

    @abstractmethod
    async def search_documents(self, query: str) -> list[dict]: ...

    @abstractmethod
    async def add_tag(self, doc_id: str, tag: str) -> None: ...


class AccountingConnector(ABC):
    @abstractmethod
    async def get_object(self, object_type: str, object_id: str) -> dict: ...

    @abstractmethod
    async def create_booking_draft(self, payload: dict) -> dict: ...


class NotificationConnector(ABC):
    @abstractmethod
    async def send(self, message: NotificationMessage) -> dict: ...


class WorkflowConnector(ABC):
    @abstractmethod
    async def trigger(self, workflow_name: str, payload: dict, idempotency_key: str) -> dict: ...


class BankFeedConnector(ABC):
    @abstractmethod
    async def ingest_transactions(self, payload: dict) -> list[dict]: ...

    @abstractmethod
    async def match_transactions(self, transactions: list[dict]) -> list[dict]: ...
