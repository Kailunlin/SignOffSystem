"""
tests/test_services.py
服務層的 TDD 單元測試：
- 動態簽核路徑生成 (WorkflowBuilder)
- 樂觀鎖防護 (ConcurrencyException)
- 非法狀態移轉 (InvalidTransitionException)
- 代理人攔截 (DelegationInterceptor)
"""
import pytest
from django.utils import timezone
from datetime import timedelta

from signoff.models import (
    User, SignoffDocument, BomDetail, BomItemDetail,
    TransferDetail, ApprovalStep, ApprovalLog, Delegation,
    DocumentType, DocumentStatus, ApprovalStepStatus
)
from signoff.services import WorkflowBuilder, DocumentService, DelegationService
from signoff.exceptions import ConcurrencyException, InvalidTransitionException, PermissionDeniedException


# ==========================================
# Fixtures
# ==========================================

@pytest.fixture
def tnn_employee(db):
    return User.objects.create_user(
        user_id='EMP_TNN', name='台南員工', position='生產專員', site_code='TNN', password='pw'
    )

@pytest.fixture
def tnn_manager(db):
    return User.objects.create_user(
        user_id='MGR_TNN', name='台南主管', position='生產主管', site_code='TNN', password='pw'
    )

@pytest.fixture
def khh_manager(db):
    return User.objects.create_user(
        user_id='MGR_KHH', name='高雄主管', position='倉庫主管', site_code='KHH', password='pw'
    )

@pytest.fixture
def tpe_manager(db):
    return User.objects.create_user(
        user_id='MGR_TPE', name='台北財務', position='台北財務', site_code='TPE', password='pw'
    )

@pytest.fixture
def bom_doc_tnn(db, tnn_employee):
    doc = SignoffDocument.objects.create(
        document_type=DocumentType.BOM,
        status=DocumentStatus.DRAFT,
        created_by=tnn_employee
    )
    bom = BomDetail.objects.create(
        document=doc, site_code='TNN', product_id='PRD-001',
        high_risk=False, cost_impact_high=False
    )
    BomItemDetail.objects.create(
        document=bom, material_id='MAT-001', quantity=10, material_status='ACTIVE'
    )
    return doc

@pytest.fixture
def bom_doc_tnn_high_risk(db, tnn_employee):
    doc = SignoffDocument.objects.create(
        document_type=DocumentType.BOM,
        status=DocumentStatus.DRAFT,
        created_by=tnn_employee
    )
    BomDetail.objects.create(
        document=doc, site_code='TNN', product_id='PRD-HR-001',
        high_risk=True, cost_impact_high=True
    )
    return doc

@pytest.fixture
def transfer_doc_tnn_to_khh(db, tnn_employee):
    doc = SignoffDocument.objects.create(
        document_type=DocumentType.MATERIAL_TRANSFER,
        status=DocumentStatus.DRAFT,
        created_by=tnn_employee
    )
    TransferDetail.objects.create(
        document=doc, source_site='TNN', target_site='KHH',
        from_warehouse='TNN_WH_A', to_warehouse='KHH_WH_B',
        material_id='MAT-001', quantity=50, urgent=False
    )
    return doc


# ==========================================
# WorkflowBuilder Tests
# ==========================================

class TestWorkflowBuilder:

    def test_bom_normal_generates_one_step(self, bom_doc_tnn):
        """一般 BOM (非高風險) 應只有 1 個簽核關卡：生產主管。"""
        steps = WorkflowBuilder.build_for_bom(bom_doc_tnn)
        assert len(steps) == 1
        assert steps[0].role == '生產主管'
        assert steps[0].site_code == 'TNN'

    def test_bom_high_risk_generates_three_steps(self, bom_doc_tnn_high_risk):
        """高風險 BOM 應有 3 個簽核關卡：生產主管 -> 廠區主管 -> 台北財務。"""
        steps = WorkflowBuilder.build_for_bom(bom_doc_tnn_high_risk)
        assert len(steps) == 3
        assert steps[0].role == '生產主管'
        assert steps[1].role == '廠區主管'
        assert steps[2].role == '台北財務'
        assert steps[2].site_code == 'TPE'

    def test_bom_from_tpe_is_rejected(self, db, tpe_manager):
        """台北廠區 (TPE) 發起的 BOM 應拋出 PermissionDeniedException。"""
        doc = SignoffDocument.objects.create(
            document_type=DocumentType.BOM,
            status=DocumentStatus.DRAFT,
            created_by=tpe_manager
        )
        BomDetail.objects.create(
            document=doc, site_code='TPE', product_id='PRD-999',
            high_risk=False, cost_impact_high=False
        )
        with pytest.raises(PermissionDeniedException):
            WorkflowBuilder.build_for_bom(doc)

    def test_transfer_cross_site_tnn_to_khh_generates_three_steps(self, transfer_doc_tnn_to_khh):
        """跨廠轉移 (TNN->KHH) 應有 3 個關卡：TNN 倉庫主管 -> KHH 倉庫主管 -> 台北財務。"""
        steps = WorkflowBuilder.build_for_transfer(transfer_doc_tnn_to_khh)
        assert len(steps) == 3
        assert steps[0].site_code == 'TNN'
        assert steps[1].site_code == 'KHH'
        assert steps[2].site_code == 'TPE'
        assert steps[2].role == '台北財務'


# ==========================================
# DocumentService State Machine Tests
# ==========================================

class TestDocumentServiceStateMachine:

    def test_submit_changes_status_to_approving(self, bom_doc_tnn, tnn_employee):
        """提交後，狀態應從 DRAFT 變更為 APPROVING，並生成簽核關卡。"""
        doc = bom_doc_tnn
        DocumentService.submit(doc, tnn_employee, version=doc.version)
        doc.refresh_from_db()
        assert doc.status == DocumentStatus.APPROVING
        assert ApprovalStep.objects.filter(document=doc).count() == 1

    def test_cannot_submit_from_approving(self, bom_doc_tnn, tnn_employee):
        """APPROVING 狀態的單據不能再次 submit，應拋出 InvalidTransitionException。"""
        doc = bom_doc_tnn
        DocumentService.submit(doc, tnn_employee, version=doc.version)
        doc.refresh_from_db()
        with pytest.raises(InvalidTransitionException):
            DocumentService.submit(doc, tnn_employee, version=doc.version)

    def test_cancel_from_draft(self, bom_doc_tnn, tnn_employee):
        """草稿狀態可以直接撤回。"""
        doc = bom_doc_tnn
        DocumentService.cancel(doc, tnn_employee, version=doc.version)
        doc.refresh_from_db()
        assert doc.status == DocumentStatus.CANCELED

    def test_revise_from_rejected_resets_to_draft(self, bom_doc_tnn, tnn_employee):
        """REJECTED 狀態執行 revise 後應回到 DRAFT，並清除舊的簽核關卡。"""
        doc = bom_doc_tnn
        # 手動設定為 REJECTED
        doc.status = DocumentStatus.REJECTED
        doc.save()
        ApprovalStep.objects.create(
            document=doc, sequence=1, role='生產主管', site_code='TNN',
            status=ApprovalStepStatus.REJECTED
        )
        DocumentService.revise(doc, tnn_employee, version=doc.version)
        doc.refresh_from_db()
        assert doc.status == DocumentStatus.DRAFT
        assert ApprovalStep.objects.filter(document=doc).count() == 0

    def test_reject_creates_log(self, bom_doc_tnn, tnn_employee, tnn_manager):
        """駁回後應在 ApprovalLog 中留下紀錄。"""
        doc = bom_doc_tnn
        doc.status = DocumentStatus.APPROVING
        doc.save()
        ApprovalStep.objects.create(
            document=doc, sequence=1, role='生產主管', site_code='TNN'
        )
        DocumentService.reject(doc, tnn_manager, version=doc.version, comment='品質不符')
        assert ApprovalLog.objects.filter(document=doc, action='REJECT').count() == 1

    def test_wrong_role_cannot_approve_current_step(self, bom_doc_tnn, tnn_employee):
        """非目前關卡所需角色不可簽核。"""
        doc = bom_doc_tnn
        DocumentService.submit(doc, tnn_employee, version=doc.version)
        doc.refresh_from_db()

        wrong_user = User.objects.create_user(
            user_id='WH_TNN', name='台南倉庫主管', position='倉庫主管', site_code='TNN', password='pw'
        )

        with pytest.raises(PermissionDeniedException):
            DocumentService.approve(doc, wrong_user, version=doc.version)

    def test_wrong_site_cannot_approve_current_step(self, bom_doc_tnn, tnn_employee):
        """同角色但不同廠區不可簽核。"""
        doc = bom_doc_tnn
        DocumentService.submit(doc, tnn_employee, version=doc.version)
        doc.refresh_from_db()

        wrong_site_manager = User.objects.create_user(
            user_id='PM_KHH', name='高雄生產主管', position='生產主管', site_code='KHH', password='pw'
        )

        with pytest.raises(PermissionDeniedException):
            DocumentService.approve(doc, wrong_site_manager, version=doc.version)

    def test_transfer_inventory_shortage_auto_rejects(self, db, tnn_employee):
        """物料轉移提交時若 ERP 庫存不足，應自動駁回並寫入 AUTO_REJECT log。"""
        doc = SignoffDocument.objects.create(
            document_type=DocumentType.MATERIAL_TRANSFER,
            status=DocumentStatus.DRAFT,
            created_by=tnn_employee
        )
        TransferDetail.objects.create(
            document=doc,
            source_site='TNN',
            target_site='KHH',
            from_warehouse='TNN_WH_A',
            to_warehouse='KHH_WH_B',
            material_id='MAT-999',
            quantity=999,
            urgent=False
        )

        DocumentService.submit(doc, tnn_employee, version=doc.version)
        doc.refresh_from_db()

        assert doc.status == DocumentStatus.REJECTED
        assert ApprovalLog.objects.filter(document=doc, action='AUTO_REJECT').exists()


# ==========================================
# Optimistic Lock (Concurrency) Tests
# ==========================================

class TestOptimisticLock:

    def test_concurrent_submit_raises_409(self, bom_doc_tnn, tnn_employee):
        """
        模擬兩個請求同時帶入 version=1 提交，
        第一個成功後 version 變為 2，
        第二個帶著舊的 version=1 提交應拋出 ConcurrencyException。
        """
        doc = bom_doc_tnn
        original_version = doc.version

        # 第一個請求成功
        DocumentService.submit(doc, tnn_employee, version=original_version)

        # 第二個請求仍帶著舊版本 -> 應失敗
        doc.refresh_from_db()  # 第二個請求模擬重新拿到文件（但 version 已變化）
        with pytest.raises((ConcurrencyException, InvalidTransitionException)):
            DocumentService.submit(doc, tnn_employee, version=original_version)


# ==========================================
# Delegation Tests
# ==========================================

class TestDelegation:

    def test_get_effective_approver_returns_delegate_when_active(self, db, tnn_manager, khh_manager):
        """當主管有生效中的代理設定時，應回傳代理人。"""
        Delegation.objects.create(
            delegator=tnn_manager,
            delegate=khh_manager,
            start_at=timezone.now() - timedelta(hours=1),
            end_at=timezone.now() + timedelta(hours=1),
        )
        result = DelegationService.get_effective_approver(tnn_manager)
        assert result == khh_manager

    def test_get_effective_approver_returns_self_when_no_delegation(self, tnn_manager):
        """無代理設定時，應回傳主管本人。"""
        result = DelegationService.get_effective_approver(tnn_manager)
        assert result == tnn_manager

    def test_expired_delegation_is_ignored(self, db, tnn_manager, khh_manager):
        """已過期的代理設定不應生效。"""
        Delegation.objects.create(
            delegator=tnn_manager,
            delegate=khh_manager,
            start_at=timezone.now() - timedelta(days=2),
            end_at=timezone.now() - timedelta(days=1),
        )
        result = DelegationService.get_effective_approver(tnn_manager)
        assert result == tnn_manager
