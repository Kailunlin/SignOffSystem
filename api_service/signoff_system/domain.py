from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


class Status(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVING = "APPROVING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"
    CANCELED = "CANCELED"
    PENDING = "PENDING"


class ApprovalError(ValueError):
    """Raised when a sign-off action violates workflow rules."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class User:
    user_id: str
    name: str
    position: str
    department: str = ""
    site_code: str = ""
    site_name: str = ""


@dataclass
class ApprovalStep:
    sequence: int
    role: str
    site_code: str
    status: Status = Status.PENDING
    approver_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    comment: str = ""
    delegated_from: Optional[str] = None  # 若由代理人執行，記錄原始負責人 ID

    def approve(self, approver_id: str, comment: str = "", delegated_from: Optional[str] = None) -> None:
        if self.status != Status.PENDING:
            raise ApprovalError(f"Only pending approval steps can be approved; current={self.status}")
        self.status = Status.APPROVED
        self.approver_id = approver_id
        self.approved_at = now_utc()
        self.comment = comment
        self.delegated_from = delegated_from

    def reject(self, approver_id: str, reason: str) -> None:
        if self.status != Status.PENDING:
            raise ApprovalError(f"Only pending approval steps can be rejected; current={self.status}")
        self.status = Status.REJECTED
        self.approver_id = approver_id
        self.approved_at = now_utc()
        self.comment = reason


@dataclass
class ApprovalLog:
    document_type: str
    document_id: int
    action: str
    actor_id: str
    comment: str = ""
    created_at: datetime = field(default_factory=now_utc)


@dataclass
class BOMItem:
    material_id: str
    quantity: int
    material_status: str = "ACTIVE"


@dataclass
class SignoffDocument:
    id: int
    created_by: str
    status: Status = Status.DRAFT
    version: int = 1
    created_at: datetime = field(default_factory=now_utc)
    updated_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejection_reason: str = ""
    sync_retries: int = 0
    approval_steps: List[ApprovalStep] = field(default_factory=list)

    @property
    def document_type(self) -> str:
        raise NotImplementedError

    def submit(self) -> None:
        if self.status != Status.DRAFT:
            raise ApprovalError(f"Only DRAFT documents can be submitted; current={self.status}")
        self.status = Status.SUBMITTED

    def start_approval(self, steps: List[ApprovalStep]) -> None:
        if self.status != Status.SUBMITTED:
            raise ApprovalError(f"Only SUBMITTED documents can start approval; current={self.status}")
        if not steps:
            raise ApprovalError("Approval steps are required")
        self.approval_steps = steps
        self.status = Status.APPROVING

    def current_step(self) -> Optional[ApprovalStep]:
        for step in self.approval_steps:
            if step.status == Status.PENDING:
                return step
        return None

    def approve_current_step(self, approver_id: str, comment: str = "", delegated_from: Optional[str] = None) -> None:
        if self.status != Status.APPROVING:
            raise ApprovalError(f"Only APPROVING documents can be approved; current={self.status}")
        step = self.current_step()
        if step is None:
            raise ApprovalError("No pending approval step found")
        step.approve(approver_id, comment, delegated_from)
        self.approved_by = approver_id
        self.approved_at = step.approved_at
        if self.current_step() is None:
            self.mark_approved()

    def mark_approved(self) -> None:
        self.status = Status.APPROVED
        self.rejection_reason = ""

    def reject(self, approver_id: str, reason: str) -> None:
        if self.status not in {Status.DRAFT, Status.SUBMITTED, Status.APPROVING}:
            raise ApprovalError(f"Only DRAFT, SUBMITTED, or APPROVING documents can be rejected; current={self.status}")
        step = self.current_step()
        if step is not None:
            step.reject(approver_id, reason)
        self.status = Status.REJECTED
        self.approved_by = approver_id
        self.approved_at = now_utc()
        self.rejection_reason = reason

    def close(self) -> None:
        if self.status != Status.APPROVED:
            raise ApprovalError(f"Only APPROVED documents can be closed; current={self.status}")
        self.status = Status.CLOSED

    def mark_sync_failed(self) -> None:
        """SA: 會計同步重試 3 次後標記 SYNC_FAILED，需人工介入"""
        self.status = Status.SYNC_FAILED

    def revise(self) -> None:
        if self.status != Status.REJECTED:
            raise ApprovalError(f"Only REJECTED documents can be revised; current={self.status}")
        self.status = Status.DRAFT
        self.approved_by = None
        self.approved_at = None
        self.rejection_reason = ""
        self.approval_steps = []

    def cancel(self, actor_id: str) -> None:
        if self.status not in {Status.SUBMITTED, Status.APPROVING}:
            raise ApprovalError(f"Only SUBMITTED or APPROVING documents can be canceled; current={self.status}")
        if self.created_by != actor_id:
            raise ApprovalError(f"Only the creator can cancel the document")
        self.status = Status.CANCELED


@dataclass
class BOM(SignoffDocument):
    product_id: str = ""
    site_code: str = ""
    high_risk: bool = False
    cost_impact_high: bool = False
    reason: str = ""           # SA: 建立原因
    attachments: str = ""      # SA: 附件參考
    items: List[BOMItem] = field(default_factory=list)

    @property
    def document_type(self) -> str:
        return "BOM"


@dataclass
class MaterialTransfer(SignoffDocument):
    material_id: str = ""
    quantity: int = 0
    material_status: str = "ACTIVE"
    from_warehouse: str = ""
    to_warehouse: str = ""
    source_site: str = ""
    target_site: str = ""
    urgent: bool = False
    reason: str = ""           # SA: 轉移原因

    @property
    def document_type(self) -> str:
        return "MATERIAL_TRANSFER"
