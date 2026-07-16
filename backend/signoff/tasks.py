"""
signoff/tasks.py
Celery 非同步任務：外部系統同步、SLA 逾期催辦掃描。
"""
from celery import shared_task
from django.utils import timezone


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_document_to_external(self, document_id: int):
    """
    當單據狀態為 APPROVED 時，非同步同步至外部系統。
    失敗時以指數退避策略最多重試 3 次，超過則標記 SYNC_FAILED。
    """
    from .models import SignoffDocument, DocumentStatus, DocumentType, ActionType
    from .external.mock_erp import MockERPService

    try:
        doc = SignoffDocument.objects.get(id=document_id)
    except SignoffDocument.DoesNotExist:
        return

    if doc.status != DocumentStatus.APPROVED:
        return

    try:
        # 呼叫對應的 Mock 外部服務
        if doc.document_type == DocumentType.BOM:
            MockERPService.sync_bom(document_id)
        else:
            MockERPService.sync_transfer(document_id)

        # 同步成功 -> CLOSED
        SignoffDocument.objects.filter(id=document_id).update(
            status=DocumentStatus.CLOSED
        )
        system_user = doc.created_by
        ApprovalLog.objects.create(
            document=doc,
            action=ActionType.CLOSE,
            actor=system_user,
            comment='外部系統同步成功，單據已結案。'
        )

    except Exception as exc:
        # 更新重試計數
        SignoffDocument.objects.filter(id=document_id).update(
            sync_retries=doc.sync_retries + 1
        )
        # 超過最大重試次數則標記 SYNC_FAILED
        if self.request.retries >= self.max_retries:
            SignoffDocument.objects.filter(id=document_id).update(
                status=DocumentStatus.SYNC_FAILED
            )
            return
        # 指數退避：60s, 120s, 240s
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task
def check_sla_overdue():
    """
    每日掃描所有 APPROVING 狀態的單據，
    找出距提交時間超過 3 天仍未完成簽核的單據，
    並寫入催辦日誌。
    """
    from .models import SignoffDocument, ApprovalLog, DocumentStatus, ActionType
    from .models import User

    sla_threshold = timezone.now() - timezone.timedelta(days=3)
    overdue_docs = SignoffDocument.objects.filter(
        status=DocumentStatus.APPROVING,
        updated_at__lt=sla_threshold
    )

    system_user = User.objects.filter(user_id='SYSTEM').first()
    if not system_user:
        # 若無 SYSTEM 使用者，跳過
        return

    for doc in overdue_docs:
        # 避免重複寫入：如果今天已有催辦紀錄則跳過
        today = timezone.now().date()
        already_reminded = ApprovalLog.objects.filter(
            document=doc,
            action='SLA_REMIND',
            created_at__date=today
        ).exists()

        if not already_reminded:
            ApprovalLog.objects.create(
                document=doc,
                action='SLA_REMIND',
                actor=system_user,
                comment=f'[SLA 逾期催辦] 單據已超過 3 天未完成簽核，請審核人員儘速處理。'
            )
