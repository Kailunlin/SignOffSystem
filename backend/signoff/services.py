"""
Service Layer (services.py)
封裝核心業務邏輯，讓 View 層保持輕量。
"""
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import (
    User, Delegation, SignoffDocument, BomDetail, BomItemDetail,
    TransferDetail, ApprovalStep, ApprovalLog,
    DocumentType, DocumentStatus, ApprovalStepStatus, ActionType
)
from .exceptions import ConcurrencyException, InvalidTransitionException, PermissionDeniedException


# ==========================================
# Delegation Service
# ==========================================

class DelegationService:
    @staticmethod
    def get_effective_approver(user: User) -> User:
        """
        若目標 user 有生效中的代理設定，返回代理人；
        否則返回原始 user 本身。
        """
        now = timezone.now()
        delegation = Delegation.objects.filter(
            delegator=user,
            start_at__lte=now,
            end_at__gte=now
        ).select_related('delegate').first()
        return delegation.delegate if delegation else user

    @staticmethod
    def get_delegators_for(user: User) -> list[User]:
        """
        返回該 user 目前正代理的所有主管列表。
        """
        now = timezone.now()
        delegations = Delegation.objects.filter(
            delegate=user,
            start_at__lte=now,
            end_at__gte=now
        ).select_related('delegator')
        return [d.delegator for d in delegations]


def _validate_step_permission(current_step: ApprovalStep, actor: User) -> User | None:
    """確認簽核人或其被代理主管符合目前關卡的角色與廠區。若為代簽則回傳被代理人，否則回傳 None。"""
    if actor.position == current_step.role and actor.site_code == current_step.site_code:
        return None

    delegators = DelegationService.get_delegators_for(actor)
    for delegator in delegators:
        if delegator.position == current_step.role and delegator.site_code == current_step.site_code:
            return delegator

    raise PermissionDeniedException(
        f"目前關卡需要 {current_step.site_code} / {current_step.role}，"
        f"但簽核者（或其代理主管）權限不符。"
    )


# ==========================================
# Workflow Builder
# ==========================================

class WorkflowBuilder:
    """
    依據 SA.md 的業務規則動態建立 ApprovalStep 列表。
    """
    @staticmethod
    def build_for_bom(document: SignoffDocument) -> list[ApprovalStep]:
        """
        BOM 審核路徑：
        1. 生產主管 (來源廠區)
        2. 廠區主管 (若 high_risk 或 cost_impact_high)
        3. 台北財務 (若 high_risk 或 cost_impact_high)
        """
        bom = document.bom_detail
        steps = []
        seq = 1

        # 強制禁止 TPE 發起 BOM（應由 Serializer Validator 攔截，這裡二次防護）
        if bom.site_code == 'TPE':
            raise PermissionDeniedException("台北廠區不得建立 BOM 單。")

        steps.append(ApprovalStep(
            document=document,
            sequence=seq,
            role='生產主管',
            site_code=bom.site_code,
        ))
        seq += 1

        if bom.high_risk or bom.cost_impact_high:
            steps.append(ApprovalStep(
                document=document,
                sequence=seq,
                role='廠區主管',
                site_code=bom.site_code,
            ))
            seq += 1
            steps.append(ApprovalStep(
                document=document,
                sequence=seq,
                role='台北財務',
                site_code='TPE',
            ))
            seq += 1

        return steps

    @staticmethod
    def build_for_transfer(document: SignoffDocument) -> list[ApprovalStep]:
        """
        轉移單審核路徑 (SA.md 規則)：
        1. 來源廠倉庫主管 (若來源是 TPE，改為台北財務)
        2. 目標廠倉庫主管 (若跨廠 且目標不是 TPE)
        3. 末關永遠加掛台北財務
        """
        transfer = document.transfer_detail
        steps = []
        seq = 1

        # Step 1: 來源廠主管
        if transfer.source_site == 'TPE':
            steps.append(ApprovalStep(document=document, sequence=seq, role='台北財務', site_code='TPE'))
        else:
            steps.append(ApprovalStep(document=document, sequence=seq, role='倉庫主管', site_code=transfer.source_site))
        seq += 1

        # Step 2: 跨廠時加掛目標廠主管 (目標為 TPE 則豁免)
        is_cross_site = transfer.source_site != transfer.target_site
        if is_cross_site and transfer.target_site != 'TPE':
            steps.append(ApprovalStep(document=document, sequence=seq, role='倉庫主管', site_code=transfer.target_site))
            seq += 1

        # Step 末: 台北財務終審 (避免重複加入)
        has_tpe_finance = any(s.role == '台北財務' and s.site_code == 'TPE' for s in steps)
        if not has_tpe_finance:
            steps.append(ApprovalStep(document=document, sequence=seq, role='台北財務', site_code='TPE'))

        return steps


# ==========================================
# Document Service
# ==========================================

class DocumentService:
    """
    核心單據狀態機服務。
    """

    # 合法的狀態移轉規則
    VALID_TRANSITIONS = {
        'submit': [DocumentStatus.DRAFT],
        'approve': [DocumentStatus.APPROVING],
        'reject': [DocumentStatus.APPROVING, DocumentStatus.SUBMITTED],
        'cancel': [DocumentStatus.DRAFT, DocumentStatus.SUBMITTED, DocumentStatus.APPROVING],
        'revise': [DocumentStatus.REJECTED],
        'retry_sync': [DocumentStatus.SYNC_FAILED],
    }

    @staticmethod
    def _check_transition(document: SignoffDocument, action: str):
        allowed = DocumentService.VALID_TRANSITIONS.get(action, [])
        if document.status not in allowed:
            raise InvalidTransitionException(
                f"單據目前狀態為 '{document.status}'，不允許執行 '{action}' 操作。"
            )

    @staticmethod
    def _write_log(document: SignoffDocument, action: str, actor: User, comment: str | None = None):
        ApprovalLog.objects.create(
            document=document,
            action=action,
            actor=actor,
            comment=comment
        )

    @staticmethod
    def _auto_reject_reason(document: SignoffDocument) -> str | None:
        from .external.mock_erp import MockERPService

        if document.document_type == DocumentType.BOM:
            for item in document.bom_detail.items.all():
                if item.material_status == 'DISABLED':
                    return f"[系統自動駁回] 物料 {item.material_id} 已停用。"
                if item.quantity > 1000:
                    return f"[系統自動駁回] 物料 {item.material_id} 數量超過安全上限 1000。"
            return None

        transfer = document.transfer_detail
        if transfer.from_warehouse == transfer.to_warehouse:
            return "[系統自動駁回] 來源倉庫與目標倉庫不可相同。"
        if transfer.quantity > 1000:
            return "[系統自動駁回] 轉移數量超過安全上限 1000。"
        inventory = MockERPService.check_inventory(transfer.material_id, transfer.quantity)
        if not inventory.get('success'):
            return f"[系統自動駁回] {inventory.get('message', '來源庫存不足。')}"
        return None

    @staticmethod
    @transaction.atomic
    def submit(document: SignoffDocument, actor: User, version: int):
        """提交單據：執行驗證、建立簽核路徑。"""
        DocumentService._check_transition(document, 'submit')

        if document.created_by_id != actor.id:
            raise PermissionDeniedException("只有單據建立者可以提交單據。")

        auto_reject_reason = DocumentService._auto_reject_reason(document)
        if auto_reject_reason:
            updated = SignoffDocument.objects.filter(
                id=document.id, version=version
            ).update(
                status=DocumentStatus.REJECTED,
                version=F('version') + 1
            )
            if updated == 0:
                raise ConcurrencyException()
            DocumentService._write_log(document, ActionType.AUTO_REJECT, actor, auto_reject_reason)
            return

        # 樂觀鎖：update WHERE id=X AND version=Y
        updated = SignoffDocument.objects.filter(
            id=document.id, version=version
        ).update(
            status=DocumentStatus.APPROVING,
            version=F('version') + 1
        )
        if updated == 0:
            raise ConcurrencyException()

        # 建立動態簽核關卡
        if document.document_type == DocumentType.BOM:
            steps = WorkflowBuilder.build_for_bom(document)
        else:
            steps = WorkflowBuilder.build_for_transfer(document)
        ApprovalStep.objects.bulk_create(steps)

        DocumentService._write_log(document, ActionType.SUBMIT, actor)

    @staticmethod
    @transaction.atomic
    def approve(document: SignoffDocument, actor: User, version: int, comment: str | None = None):
        """主管同意簽核。"""
        DocumentService._check_transition(document, 'approve')

        # 找到目前最低 sequence 的 PENDING 關卡
        current_step = ApprovalStep.objects.filter(
            document=document, status=ApprovalStepStatus.PENDING
        ).order_by('sequence').first()

        if current_step is None:
            raise InvalidTransitionException("找不到待簽核的關卡。")

        # 代理人與權限判斷
        delegator = _validate_step_permission(current_step, actor)
        delegated_from_id = delegator.user_id if delegator else None

        # 更新當前關卡
        current_step.status = ApprovalStepStatus.APPROVED
        current_step.approver = actor
        current_step.comment = comment
        current_step.delegated_from = delegated_from_id
        current_step.save()

        DocumentService._write_log(document, ActionType.APPROVE, actor, comment)

        # 判斷是否全部通過
        remaining = ApprovalStep.objects.filter(
            document=document, status=ApprovalStepStatus.PENDING
        ).exists()

        if not remaining:
            # 全部簽核完成 -> APPROVED，後續由 Celery 觸發外部同步
            updated = SignoffDocument.objects.filter(
                id=document.id, version=version
            ).update(status=DocumentStatus.APPROVED, version=F('version') + 1)
            if updated == 0:
                raise ConcurrencyException()

            # 觸發非同步外部系統同步任務
            from .tasks import sync_document_to_external
            sync_document_to_external.delay(document.id)
        else:
            # 仍有待審關卡，只更新版本號防止舊資料衝突
            updated = SignoffDocument.objects.filter(
                id=document.id, version=version
            ).update(version=F('version') + 1)
            if updated == 0:
                raise ConcurrencyException()

    @staticmethod
    @transaction.atomic
    def reject(document: SignoffDocument, actor: User, version: int, comment: str):
        """主管駁回單據。"""
        DocumentService._check_transition(document, 'reject')

        # 將所有 PENDING 關卡標記為 REJECTED
        ApprovalStep.objects.filter(
            document=document, status=ApprovalStepStatus.PENDING
        ).update(status=ApprovalStepStatus.REJECTED)

        updated = SignoffDocument.objects.filter(
            id=document.id, version=version
        ).update(status=DocumentStatus.REJECTED, version=F('version') + 1)
        if updated == 0:
            raise ConcurrencyException()

        DocumentService._write_log(document, ActionType.REJECT, actor, comment)

    @staticmethod
    @transaction.atomic
    def cancel(document: SignoffDocument, actor: User, version: int):
        """申請人撤回單據。"""
        DocumentService._check_transition(document, 'cancel')

        if document.created_by_id != actor.id:
            raise PermissionDeniedException("只有單據建立者可以撤回單據。")

        updated = SignoffDocument.objects.filter(
            id=document.id, version=version
        ).update(status=DocumentStatus.CANCELED, version=F('version') + 1)
        if updated == 0:
            raise ConcurrencyException()

        DocumentService._write_log(document, ActionType.CANCEL, actor)

    @staticmethod
    @transaction.atomic
    def revise(document: SignoffDocument, actor: User, version: int):
        """申請人修改重提 (REJECTED -> DRAFT)。"""
        DocumentService._check_transition(document, 'revise')

        if document.created_by_id != actor.id:
            raise PermissionDeniedException("只有單據建立者可以重提單據。")

        # 清除舊的簽核關卡
        ApprovalStep.objects.filter(document=document).delete()

        updated = SignoffDocument.objects.filter(
            id=document.id, version=version
        ).update(status=DocumentStatus.DRAFT, version=F('version') + 1)
        if updated == 0:
            raise ConcurrencyException()

        DocumentService._write_log(document, ActionType.REVISE, actor)

    @staticmethod
    @transaction.atomic
    def retry_sync(document: SignoffDocument, actor: User, version: int):
        """手動重試外部系統同步 (SYNC_FAILED)。"""
        DocumentService._check_transition(document, 'retry_sync')

        # 重置重試次數，觸發 Celery 任務（Celery 任務將在 tasks.py 中實作）
        updated = SignoffDocument.objects.filter(
            id=document.id, version=version
        ).update(sync_retries=0, version=F('version') + 1)
        if updated == 0:
            raise ConcurrencyException()

        DocumentService._write_log(document, ActionType.RETRY_SYNC, actor, "手動觸發重試外部系統同步")
        from .tasks import sync_document_to_external
        sync_document_to_external.delay(document.id)
