from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .domain import (
    ApprovalError, ApprovalLog, ApprovalStep, BOM,
    MaterialTransfer, SignoffDocument, Status, User,
)
from .models import (
    ApprovalLogORM, ApprovalStepORM, BOMDetailORM,
    DelegationORM, SignoffDocumentORM, TransferDetailORM,
)

logger = logging.getLogger(__name__)

MAX_SYNC_RETRIES = 3


class DatabaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ──────────────────────────── CREATE ────────────────────────────

    def create_bom(
        self,
        *,
        product_id: str,
        items: List[dict],
        created_by: str,
        site_code: str = "",
        high_risk: bool = False,
        cost_impact_high: bool = False,
        reason: str = "",
        attachments: str = "",
    ) -> BOM:
        doc_orm = SignoffDocumentORM(
            document_type="BOM",
            status=Status.DRAFT.value,
            created_by=created_by,
        )
        self.session.add(doc_orm)
        self.session.flush()

        bom_orm = BOMDetailORM(
            document_id=doc_orm.id,
            site_code=site_code,
            product_id=product_id,
            high_risk=high_risk,
            cost_impact_high=cost_impact_high,
            reason=reason,
            attachments=attachments,
        )
        self.session.add(bom_orm)
        self.session.flush()
        
        from .models import BOMItemORM
        for item in items:
            self.session.add(BOMItemORM(
                document_id=doc_orm.id,
                material_id=item["material_id"],
                quantity=item["quantity"],
                material_status=item.get("material_status", "ACTIVE")
            ))

        self.session.commit()
        return self.get_bom(doc_orm.id)

    def create_transfer(
        self,
        *,
        from_warehouse: str,
        to_warehouse: str,
        material_id: str,
        quantity: int,
        created_by: str,
        material_status: str = "ACTIVE",
        source_site: str = "",
        target_site: str = "",
        urgent: bool = False,
        reason: str = "",
    ) -> MaterialTransfer:
        doc_orm = SignoffDocumentORM(
            document_type="MATERIAL_TRANSFER",
            status=Status.DRAFT.value,
            created_by=created_by,
        )
        self.session.add(doc_orm)
        self.session.flush()

        transfer_orm = TransferDetailORM(
            document_id=doc_orm.id,
            source_site=source_site,
            target_site=target_site,
            from_warehouse=from_warehouse,
            to_warehouse=to_warehouse,
            material_id=material_id,
            quantity=quantity,
            material_status=material_status,
            urgent=urgent,
            reason=reason,
        )
        self.session.add(transfer_orm)
        self.session.commit()
        return self.get_transfer(doc_orm.id)

    # ──────────────────────────── READ ────────────────────────────

    def get_bom(self, document_id: int) -> BOM:
        orm = self.session.query(SignoffDocumentORM).filter_by(id=document_id, document_type="BOM").first()
        if not orm:
            raise ApprovalError(f"BOM {document_id} not found")
        bom_orm = orm.bom_detail
        from .domain import BOMItem
        bom_items = [
            BOMItem(material_id=i.material_id, quantity=i.quantity, material_status=i.material_status)
            for i in bom_orm.items
        ]
        bom = BOM(
            id=orm.id,
            created_by=orm.created_by,
            status=Status(orm.status),
            version=orm.version,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            approved_by=orm.approved_by,
            approved_at=orm.approved_at,
            rejection_reason=orm.rejection_reason or "",
            sync_retries=orm.sync_retries,
            product_id=bom_orm.product_id,
            site_code=bom_orm.site_code or "",
            high_risk=bom_orm.high_risk,
            cost_impact_high=bom_orm.cost_impact_high,
            reason=bom_orm.reason or "",
            attachments=bom_orm.attachments or "",
            items=bom_items,
        )
        self._load_steps(bom, orm)
        return bom

    def get_transfer(self, document_id: int) -> MaterialTransfer:
        orm = self.session.query(SignoffDocumentORM).filter_by(id=document_id, document_type="MATERIAL_TRANSFER").first()
        if not orm:
            raise ApprovalError(f"Material transfer {document_id} not found")
        transfer_orm = orm.transfer_detail
        transfer = MaterialTransfer(
            id=orm.id,
            material_id=transfer_orm.material_id,
            quantity=transfer_orm.quantity,
            created_by=orm.created_by,
            material_status=transfer_orm.material_status,
            status=Status(orm.status),
            version=orm.version,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            approved_by=orm.approved_by,
            approved_at=orm.approved_at,
            rejection_reason=orm.rejection_reason or "",
            sync_retries=orm.sync_retries,
            from_warehouse=transfer_orm.from_warehouse,
            to_warehouse=transfer_orm.to_warehouse,
            source_site=transfer_orm.source_site or "",
            target_site=transfer_orm.target_site or "",
            urgent=transfer_orm.urgent,
            reason=transfer_orm.reason or "",
        )
        self._load_steps(transfer, orm)
        return transfer

    def _load_steps(self, document: SignoffDocument, orm: SignoffDocumentORM) -> None:
        document.approval_steps = [
            ApprovalStep(
                sequence=step.sequence,
                role=step.role,
                site_code=step.site_code or "",
                status=Status(step.status),
                approver_id=step.approver_id,
                approved_at=step.approved_at,
                comment=step.comment or "",
                delegated_from=step.delegated_from,
            )
            for step in orm.steps
        ]

    def save_document(self, document: SignoffDocument) -> None:
        orm = self.session.query(SignoffDocumentORM).get(document.id)
        if not orm:
            raise ApprovalError(f"Document {document.id} not found")

        if orm.version != document.version:
            raise ApprovalError("單據狀態已變更，請重新整理 (Concurrency Conflict)")

        try:
            orm.status = document.status.value
            orm.approved_by = document.approved_by
            orm.approved_at = document.approved_at
            orm.rejection_reason = document.rejection_reason
            orm.sync_retries = document.sync_retries
            orm.version = document.version

            orm.steps.clear()
            for step in document.approval_steps:
                orm.steps.append(ApprovalStepORM(
                    sequence=step.sequence,
                    role=step.role,
                    site_code=step.site_code,
                    status=step.status.value,
                    approver_id=step.approver_id,
                    approved_at=step.approved_at,
                    comment=step.comment,
                    delegated_from=step.delegated_from,
                ))

            self.session.commit()
            document.version += 1

        except StaleDataError as exc:
            self.session.rollback()
            raise ApprovalError("單據狀態已變更，請重新整理 (Concurrency Conflict)") from exc
        except Exception:
            self.session.rollback()
            raise

    def add_log(self, log: ApprovalLog) -> ApprovalLog:
        log_orm = ApprovalLogORM(
            document_id=log.document_id,
            action=log.action,
            actor_id=log.actor_id,
            comment=log.comment,
        )
        self.session.add(log_orm)
        self.session.commit()
        log.created_at = log_orm.created_at
        return log

    def get_logs(self, document_id: int) -> List[ApprovalLog]:
        orms = self.session.query(ApprovalLogORM).filter_by(document_id=document_id).order_by(ApprovalLogORM.created_at).all()
        doc_orm = self.session.query(SignoffDocumentORM).get(document_id)
        doc_type = doc_orm.document_type if doc_orm else ""
        return [
            ApprovalLog(
                document_type=doc_type,
                document_id=orm.document_id,
                action=orm.action,
                actor_id=orm.actor_id,
                comment=orm.comment or "",
                created_at=orm.created_at,
            ) for orm in orms
        ]

    def list_boms(self, *, status: Optional[str] = None, created_by: Optional[str] = None, skip: int = 0, limit: int = 100) -> List[BOM]:
        query = self.session.query(SignoffDocumentORM).filter(SignoffDocumentORM.document_type == "BOM")
        if status:
            query = query.filter(SignoffDocumentORM.status == status)
        if created_by:
            query = query.filter(SignoffDocumentORM.created_by == created_by)
        orms = query.order_by(SignoffDocumentORM.id.desc()).offset(skip).limit(limit).all()
        return [self.get_bom(orm.id) for orm in orms]

    def list_transfers(self, *, status: Optional[str] = None, created_by: Optional[str] = None, skip: int = 0, limit: int = 100) -> List[MaterialTransfer]:
        query = self.session.query(SignoffDocumentORM).filter(SignoffDocumentORM.document_type == "MATERIAL_TRANSFER")
        if status:
            query = query.filter(SignoffDocumentORM.status == status)
        if created_by:
            query = query.filter(SignoffDocumentORM.created_by == created_by)
        orms = query.order_by(SignoffDocumentORM.id.desc()).offset(skip).limit(limit).all()
        return [self.get_transfer(orm.id) for orm in orms]

    # ──────────────────────── DELEGATION ────────────────────────

    def set_delegation(self, delegator_id: str, delegate_id: str, start_at: datetime, end_at: datetime) -> None:
        """設定或更新代理人（同 delegator 只保留最新一筆）"""
        existing = self.session.query(DelegationORM).filter_by(delegator_id=delegator_id).first()
        if existing:
            existing.delegate_id = delegate_id
            existing.start_at = start_at
            existing.end_at = end_at
        else:
            self.session.add(DelegationORM(
                delegator_id=delegator_id,
                delegate_id=delegate_id,
                start_at=start_at,
                end_at=end_at,
            ))
        self.session.commit()

    def get_active_delegate(self, user_id: str) -> Optional[str]:
        """若 user_id 目前處於代理期間，回傳代理人 ID；否則回傳 None"""
        now = datetime.utcnow()
        row = self.session.query(DelegationORM).filter(
            DelegationORM.delegator_id == user_id,
            DelegationORM.start_at <= now,
            DelegationORM.end_at >= now,
        ).first()
        return row.delegate_id if row else None

    def list_pending_documents(self, sla_days: int = 3):
        """列出所有超過 SLA 天數仍在 APPROVING 的單據，供催辦使用"""
        from sqlalchemy import func
        threshold = datetime.utcnow()
        orms = self.session.query(SignoffDocumentORM).filter(
            SignoffDocumentORM.status == Status.APPROVING.value,
        ).all()
        result = []
        for orm in orms:
            if orm.updated_at:
                delta = (threshold - orm.updated_at).days
                if delta >= sla_days:
                    result.append((orm.id, orm.document_type, delta))
        return result


class MockHRService:
    def __init__(self, users: Iterable[User]) -> None:
        self._users: Dict[str, User] = {user.user_id: user for user in users}

    def get_position(self, user_id: str) -> Optional[str]:
        user = self._users.get(user_id)
        return user.position if user else None

    def get_user(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    def upsert_user(self, user: User) -> None:
        self._users[user.user_id] = user


class MockERPService:
    """SA 9.1: 模擬 ERP/WMS 庫存與物料主檔查詢"""

    # 預設模擬資料：material_id -> {stock, status}
    _inventory: Dict[str, dict] = {
        "M-CPU-INTEL":  {"stock": 500,  "status": "ACTIVE"},
        "M-GPU-NVIDIA": {"stock": 200,  "status": "ACTIVE"},
        "M-RAM-64G":    {"stock": 800,  "status": "ACTIVE"},
        "M-SCREW-01":   {"stock": 9999, "status": "ACTIVE"},
        "M-PANEL-15":   {"stock": 300,  "status": "ACTIVE"},
        "M-DEPRECATED": {"stock": 10,   "status": "DISABLED"},
    }

    # 預占記錄：{material_id -> {document_id -> reserved_qty}}
    _reserved: Dict[str, Dict[int, int]] = {}

    def get_material_status(self, material_id: str) -> str:
        return self._inventory.get(material_id, {}).get("status", "ACTIVE")

    def get_stock(self, material_id: str, site_code: str = "") -> int:
        return self._inventory.get(material_id, {}).get("stock", 9999)

    def _reserved_total(self, material_id: str) -> int:
        """計算指定物料目前所有單據的預佔總量"""
        return sum(self._reserved.get(material_id, {}).values())

    def check_inventory(self, material_id: str, quantity: int, site_code: str = "") -> str:
        """回傳錯誤訊息；若無問題則回傳空字串。可用庫存 = 實際庫存 - 已預占量"""
        mat = self._inventory.get(material_id)
        if mat and mat["status"] == "DISABLED":
            return f"物料 {material_id} 已停用 (ERP)"
        if mat:
            available = mat["stock"] - self._reserved_total(material_id)
            if available < quantity:
                return (
                    f"物料 {material_id} 可用庫存不足："
                    f"實際 {mat['stock']}，已預占 {self._reserved_total(material_id)}，"
                    f"可用 {available}，需求 {quantity} (ERP)"
                )
        return ""

    def reserve_inventory(self, material_id: str, quantity: int, document_id: int, source_site: str) -> None:
        """SA Reserve: 單據提交簽核時預占庫存，防止其他單據重複允諸"""
        if material_id not in self._reserved:
            self._reserved[material_id] = {}
        self._reserved[material_id][document_id] = quantity
        logger.info(
            f"[ERP 庫存預占] 物料={material_id} 預占={quantity} "
            f"單據=#{document_id} 來源廠={source_site}"
        )

    def release_inventory(self, material_id: str, document_id: int, source_site: str) -> None:
        """SA Release: 單據撤回時釋放預占庫存，避免死庫"""
        reserved_qty = self._reserved.get(material_id, {}).pop(document_id, 0)
        logger.info(
            f"[ERP 庫存釋放] 物料={material_id} 釋放={reserved_qty} "
            f"單據=#{document_id} 來源廠={source_site}"
        )

    def deduct_inventory(self, material_id: str, quantity: int, source_site: str, target_site: str) -> None:
        """SA: 轉移單簽核完成後，正式扣減來源庫存並增加目標庫存 (模擬)"""
        mat = self._inventory.get(material_id)
        if mat:
            mat["stock"] -= quantity
            logger.info(
                f"[ERP 庫存異動] 物料={material_id} 扣減={quantity} "
                f"({source_site} -> {target_site})，剩餘庫存={mat['stock']}"
            )


class MockAccountingService:
    def __init__(self) -> None:
        self.synced_events: List[dict] = []

    def sync_document(self, document: SignoffDocument) -> dict:
        event = {
            "transaction_id": f"{document.document_type}-{document.id}",
            "type": document.document_type,
            "payload": self._payload(document),
        }
        self.synced_events.append(event)
        return event

    @staticmethod
    def _payload(document: SignoffDocument) -> dict:
        data = asdict(document)
        data["status"] = document.status.value
        data["created_at"] = document.created_at.isoformat()
        data["approved_at"] = document.approved_at.isoformat() if document.approved_at else None
        
        # 處理 Enum 或時間格式轉換
        if hasattr(document, "items"):
            data["items"] = [asdict(item) for item in document.items]
        
        data["approval_steps"] = [
            {
                **step,
                "status": step["status"].value,
                "approved_at": step["approved_at"].isoformat() if step["approved_at"] else None,
            }
            for step in data["approval_steps"]
        ]
        return data


class NotificationService:
    """SA 10: 模擬多管道通知（Email / In-App / Webhook 急件推播）"""

    def notify(self, event: str, recipients: List[str], message: str, urgent: bool = False) -> None:
        if urgent:
            logger.info(f"[🚨 WEBHOOK 推播 Teams/Slack - {event}] To: {', '.join(recipients)} | Msg: {message}")
        else:
            logger.info(f"[NOTIFICATION - {event}] To: {', '.join(recipients)} | Msg: {message}")


class ApprovalWorkflow:
    def __init__(
        self,
        repository: DatabaseRepository,
        hr_service: MockHRService,
        accounting_service: MockAccountingService,
        notification_service: NotificationService,
        erp_service: Optional[MockERPService] = None,
        *,
        safety_quantity_limit: int = 1000,
    ) -> None:
        self.repository = repository
        self.hr_service = hr_service
        self.accounting_service = accounting_service
        self.notification_service = notification_service
        self.erp_service = erp_service or MockERPService()
        self.safety_quantity_limit = safety_quantity_limit

    def submit(self, document: SignoffDocument, actor_id: str, comment: str = "") -> SignoffDocument:
        document.submit()
        reason = self._auto_reject_reason(document)
        if reason:
            document.reject(actor_id, reason)
            self.repository.save_document(document)
            self._log(document, "AUTO_REJECT", actor_id, reason)
            self.notification_service.notify("REJECTED", [document.created_by], f"您的單據 #{document.id} 被系統自動駁回：{reason}")
            return document

        steps = self._build_steps(document)
        # SA Phase 3: 代理人攔截 - 若步驟中的簽核人有代理人，替換簽核人
        steps = self._apply_delegation(steps, document)
        document.start_approval(steps)
        self.repository.save_document(document)
        self._log(document, "SUBMIT", actor_id, comment)

        # SA Reserve: 物料轉移單提交後，預占 ERP 庫存，防止其他單據重複允諸
        if isinstance(document, MaterialTransfer):
            try:
                self.erp_service.reserve_inventory(
                    material_id=document.material_id,
                    quantity=document.quantity,
                    document_id=document.id,
                    source_site=document.source_site,
                )
            except Exception as reserve_exc:
                logger.warning(f"[ERP 庫存預占失敗] 單據 #{document.id}: {reserve_exc}")

        next_step = document.current_step()
        if next_step:
            is_urgent = getattr(document, "urgent", False)
            self.notification_service.notify(
                "SUBMITTED",
                [f"Role: {next_step.role} @ {next_step.site_code}"],
                f"新單據 #{document.id} ({document.document_type}) 需要您審核",
                urgent=is_urgent,
            )

        return document

    def approve(self, document: SignoffDocument, approver_id: str, comment: str = "") -> SignoffDocument:
        approver = self.hr_service.get_user(approver_id)
        step = document.current_step()
        if step is None:
            raise ApprovalError("No pending approval step found")
        if approver is None:
            raise ApprovalError(f"Approver {approver_id} not found")

        # 支援代理人：若 step 已指派代理人，允許代理人操作
        effective_role = approver.position
        if step.approver_id and step.approver_id == approver_id:
            # 已預設為代理人，直接允許
            pass
        elif effective_role != step.role:
            raise ApprovalError(f"{document.document_type} requires {step.role}; approver position={approver.position}")

        if step.site_code and approver.site_code != step.site_code:
            # 若是代理人，其 site_code 不一定與原主管同廠，仍允許
            if step.delegated_from is None:
                raise ApprovalError(f"{document.document_type} requires approver at {step.site_code}; approver site={approver.site_code}")

        delegated_from = step.delegated_from if step.delegated_from else None
        document.approve_current_step(approver_id, comment, delegated_from)
        self.repository.save_document(document)
        self._log(document, "APPROVE", approver_id, comment + (f" (代理: {delegated_from})" if delegated_from else ""))

        self.notification_service.notify("APPROVED", [document.created_by], f"您的單據 #{document.id} 已由 {approver_id} 核准")

        if document.status == Status.APPROVED:
            # SA: 若為物料轉移單，簽核完成後立即向 ERP 執行庫存扣除
            if isinstance(document, MaterialTransfer):
                try:
                    self.erp_service.deduct_inventory(
                        material_id=document.material_id,
                        quantity=document.quantity,
                        source_site=document.source_site,
                        target_site=document.target_site,
                    )
                except Exception as erp_exc:
                    logger.warning(f"[ERP 庫存扣除失敗] 單據 #{document.id}: {erp_exc}")
            # 會計同步交由呼叫方 (api.py BackgroundTasks) 非同步執行
            # 此處僅標記單據進入「待同步」狀態，不阻塞 API 回應
        else:
            next_step = document.current_step()
            if next_step:
                is_urgent = getattr(document, "urgent", False)
                self.notification_service.notify(
                    "STEP_PENDING",
                    [f"Role: {next_step.role} @ {next_step.site_code}"],
                    f"單據 #{document.id} 已進入下一關，請審核",
                    urgent=is_urgent,
                )

        return document

    def reject(self, document: SignoffDocument, approver_id: str, reason: str) -> SignoffDocument:
        document.reject(approver_id, reason)
        self.repository.save_document(document)
        self._log(document, "REJECT", approver_id, reason)
        self.notification_service.notify("REJECTED", [document.created_by], f"您的單據 #{document.id} 已由 {approver_id} 駁回：{reason}")
        return document

    def cancel(self, document: SignoffDocument, actor_id: str) -> SignoffDocument:
        # SA 5.5: 撤回前收集已簽核過的主管，撤回後通知他們
        already_approved_by = [
            step.approver_id for step in document.approval_steps
            if step.status == Status.APPROVED and step.approver_id
        ]

        document.cancel(actor_id)
        self.repository.save_document(document)
        self._log(document, "CANCEL", actor_id, "單據由申請人撤回")

        # SA Release: 物料轉移單撤回時，釋放在 ERP 中預占的庫存，避免死庫
        if isinstance(document, MaterialTransfer):
            try:
                self.erp_service.release_inventory(
                    material_id=document.material_id,
                    document_id=document.id,
                    source_site=document.source_site,
                )
            except Exception as release_exc:
                logger.warning(f"[ERP 庫存釋放失敗] 單據 #{document.id}: {release_exc}")

        # SA 5.5: 通知已簽核主管
        if already_approved_by:
            self.notification_service.notify(
                "CANCELED",
                already_approved_by,
                f"您先前已核准的單據 #{document.id} 已被申請人 {actor_id} 撤回作廢",
            )
        # 通知目前待簽核主管
        step = document.current_step()
        if step:
            self.notification_service.notify("CANCELED", [f"Role: {step.role}"], f"單據 #{document.id} 已撤回，無需繼續審核")
        return document

    def revise(self, document: SignoffDocument, actor_id: str) -> SignoffDocument:
        document.revise()
        self.repository.save_document(document)
        self._log(document, "REVISE", actor_id, "單據已修改，準備重新提交")
        self.notification_service.notify("REVISED", [document.created_by], f"您的單據 #{document.id} 已恢復為草稿，請修改後重新提交")
        return document

    def retry_accounting_sync(self, document: SignoffDocument, actor_id: str) -> SignoffDocument:
        """SA: 台北財務或管理員手動重試會計同步；超過上限則轉為 SYNC_FAILED"""
        if document.status not in {Status.APPROVED, Status.SYNC_FAILED}:
            raise ApprovalError(f"只有 APPROVED 或 SYNC_FAILED 的單據才可重試同步；目前狀態={document.status}")
        document.sync_retries += 1
        try:
            self.accounting_service.sync_document(document)
            document.status = Status.APPROVED  # 讓 close() 可以執行
            document.close()
            self.repository.save_document(document)
            self._log(document, "SYNC_RETRY_SUCCESS", actor_id, "手動重試會計同步成功")
            self.notification_service.notify("SYNC_SUCCESS", [document.created_by], f"單據 #{document.id} 會計同步成功（手動重試）")
        except Exception as e:
            if document.sync_retries >= MAX_SYNC_RETRIES:
                document.mark_sync_failed()
                self._log(document, "SYNC_FAILED", actor_id, f"手動重試仍失敗：{e}")
                self.notification_service.notify("SYNC_FAILED", ["Role: 台北財務", "Role: 系統管理員"], f"單據 #{document.id} 手動重試失敗，請人工介入")
            else:
                self._log(document, "SYNC_RETRY", actor_id, f"手動重試第 {document.sync_retries} 次失敗：{e}")
            self.repository.save_document(document)
        return document

    def trigger_sla_check(self, sla_days: int = 3) -> List[dict]:
        """SA 10.1: 手動觸發 SLA 逾期檢查，模擬排程催辦通知"""
        overdue = self.repository.list_pending_documents(sla_days=sla_days)
        results = []
        for doc_id, doc_type, days_overdue in overdue:
            try:
                if doc_type == "BOM":
                    doc = self.repository.get_bom(doc_id)
                else:
                    doc = self.repository.get_transfer(doc_id)
                step = doc.current_step()
                if step:
                    self.notification_service.notify(
                        "SLA_OVERDUE",
                        [f"Role: {step.role} @ {step.site_code}", "Role: 系統管理員"],
                        f"[催辦] 單據 #{doc_id} 已逾期 {days_overdue} 天，請盡速處理",
                        urgent=days_overdue >= 5,
                    )
                    results.append({"id": doc_id, "type": doc_type, "days_overdue": days_overdue, "step_role": step.role})
            except Exception:
                pass
        return results

    def _apply_delegation(self, steps: List[ApprovalStep], document: SignoffDocument) -> List[ApprovalStep]:
        """SA Phase 3: 查詢簽核路徑中每個角色的預設簽核人，若其有代理人則替換"""
        for step in steps:
            # 找到符合角色與廠區的簽核人
            target_user = self._find_user_for_step(step)
            if target_user:
                delegate_id = self.repository.get_active_delegate(target_user.user_id)
                if delegate_id:
                    step.delegated_from = target_user.user_id
                    step.approver_id = delegate_id
                    logger.info(f"[DELEGATION] 單據 #{document.id} 第 {step.sequence} 關由代理人 {delegate_id} 代替 {target_user.user_id} 簽核")
        return steps

    def _find_user_for_step(self, step: ApprovalStep) -> Optional[User]:
        """根據 role 與 site_code 找到對應的使用者"""
        for user in self.hr_service._users.values():
            if user.position == step.role and (not step.site_code or user.site_code == step.site_code):
                return user
        return None

    def _auto_reject_reason(self, document: SignoffDocument) -> str:
        # ERP 整合檢查
        if isinstance(document, MaterialTransfer):
            if document.quantity > self.safety_quantity_limit:
                return "數量超過安全上限"
            erp_msg = self.erp_service.check_inventory(document.material_id, document.quantity, document.source_site)
            if erp_msg:
                return erp_msg
            if document.source_site == document.target_site and document.from_warehouse == document.to_warehouse:
                return "來源與目標倉庫不能相同"
            if not document.source_site or not document.target_site:
                return "必須指定來源廠區與目標廠區"
        if isinstance(document, BOM):
            if not document.items:
                return "BOM 必須至少包含一項物料"
            for item in document.items:
                if item.quantity > self.safety_quantity_limit:
                    return f"物料 {item.material_id} 數量超過安全上限"
                erp_status = self.erp_service.get_material_status(item.material_id)
                if erp_status == "DISABLED" or item.material_status.upper() == "DISABLED":
                    return f"物料 {item.material_id} 已停用，無法建立 BOM"
            if not document.site_code:
                return "BOM 必須指定廠區"
            if document.site_code == "TPE":
                return "總公司台北場 (TPE) 違規發起 BOM 單"
        return ""

    def _build_steps(self, document: SignoffDocument) -> List[ApprovalStep]:
        if isinstance(document, BOM):
            return self._build_bom_steps(document)
        if isinstance(document, MaterialTransfer):
            return self._build_transfer_steps(document)
        raise ApprovalError(f"Unsupported document type: {document.document_type}")

    def _build_bom_steps(self, bom: BOM) -> List[ApprovalStep]:
        steps = [ApprovalStep(sequence=1, role="生產主管", site_code=bom.site_code)]
        needs_extra_review = bom.high_risk or bom.cost_impact_high or bom.site_code == "TPE"
        if needs_extra_review:
            if bom.site_code != "TPE":
                steps.append(ApprovalStep(sequence=len(steps) + 1, role="廠區主管", site_code=bom.site_code))
            steps.append(ApprovalStep(sequence=len(steps) + 1, role="台北財務", site_code="TPE"))
        return steps

    def _build_transfer_steps(self, transfer: MaterialTransfer) -> List[ApprovalStep]:
        first_role = "台北財務" if transfer.source_site == "TPE" else "倉庫主管"
        steps = [ApprovalStep(sequence=1, role=first_role, site_code=transfer.source_site)]
        is_cross_site = transfer.source_site != transfer.target_site
        if is_cross_site and transfer.target_site != "TPE":
            steps.append(ApprovalStep(sequence=len(steps) + 1, role="倉庫主管", site_code=transfer.target_site))
        steps.append(ApprovalStep(sequence=len(steps) + 1, role="台北財務", site_code="TPE"))
        return steps

    def _log(self, document: SignoffDocument, action: str, actor_id: str, comment: str = "") -> None:
        self.repository.add_log(
            ApprovalLog(
                document_type=document.document_type,
                document_id=document.id,
                action=action,
                actor_id=actor_id,
                comment=comment,
            )
        )


def do_accounting_sync(
    document: SignoffDocument,
    workflow: "ApprovalWorkflow",
    actor_id: str = "SYSTEM",
) -> None:
    """
    SA: 非同步會計同步任務，由 FastAPI BackgroundTasks 呼叫。
    負責執行 accounting_service.sync_document，並在成功後將單據狀態轉為 CLOSED。
    失敗時自動重試，超過上限則標記 SYNC_FAILED 並通知相關人員。
    """
    document_id = document.id
    try:
        workflow.accounting_service.sync_document(document)
        document.close()
        workflow.repository.save_document(document)
        workflow._log(document, "CLOSE", actor_id, "會計同步完成 (背景任務)")
        workflow.notification_service.notify(
            "SYNC_SUCCESS",
            [document.created_by, "Role: 台北財務"],
            f"單據 #{document_id} 已成功同步至會計系統",
        )
        logger.info(f"[BACKGROUND SYNC] 單據 #{document_id} 會計同步成功")
    except Exception as exc:
        document.sync_retries += 1
        logger.warning(f"[BACKGROUND SYNC] 單據 #{document_id} 會計同步失敗 (第 {document.sync_retries} 次): {exc}")
        if document.sync_retries >= MAX_SYNC_RETRIES:
            document.mark_sync_failed()
            workflow._log(document, "SYNC_FAILED", "SYSTEM", f"會計同步失敗超過 {MAX_SYNC_RETRIES} 次，請人工介入")
            workflow.notification_service.notify(
                "SYNC_FAILED",
                ["Role: 台北財務", "Role: 系統管理員"],
                f"單據 #{document_id} 會計同步失敗，已達最大重試次數，需人工介入",
            )
        else:
            workflow._log(document, "SYNC_RETRY", "SYSTEM", f"會計同步失敗，第 {document.sync_retries} 次重試：{exc}")
        workflow.repository.save_document(document)
