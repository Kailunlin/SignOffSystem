import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from signoff_system.domain import ApprovalError, Status, User
from signoff_system.models import Base
from signoff_system.services import ApprovalWorkflow, DatabaseRepository, MockAccountingService, MockHRService, NotificationService


class ApprovalWorkflowTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        self.session = SessionLocal()
        
        self.repo = DatabaseRepository(self.session)
        self.production_manager = User(
            user_id="PM-TNN",
            name="台南生產主管",
            position="生產主管",
            department="生產部",
            site_code="TNN",
            site_name="台南廠",
        )
        self.site_manager = User(
            user_id="GM-TNN",
            name="台南廠區主管",
            position="廠區主管",
            department="廠務部",
            site_code="TNN",
            site_name="台南廠",
        )
        self.tnn_warehouse_supervisor = User(
            user_id="WH-TNN",
            name="台南倉庫主管",
            position="倉庫主管",
            department="倉儲部",
            site_code="TNN",
            site_name="台南廠",
        )
        self.khh_warehouse_supervisor = User(
            user_id="WH-KHH",
            name="高雄倉庫主管",
            position="倉庫主管",
            department="倉儲部",
            site_code="KHH",
            site_name="高雄廠",
        )
        self.finance = User(
            user_id="FIN-TPE",
            name="台北財務",
            position="台北財務",
            department="財務部",
            site_code="TPE",
            site_name="總公司台北場",
        )
        self.employee = User(
            user_id="EMP001",
            name="林員工",
            position="員工",
            department="生產部",
            site_code="TNN",
            site_name="台南廠",
        )
        self.users = [
            self.production_manager,
            self.site_manager,
            self.tnn_warehouse_supervisor,
            self.khh_warehouse_supervisor,
            self.finance,
            self.employee,
        ]

        self.hr = MockHRService(self.users)
        self.accounting = MockAccountingService()
        self.notification = NotificationService()
        self.workflow = ApprovalWorkflow(self.repo, self.hr, self.accounting, self.notification)

    def tearDown(self):
        self.session.close()

    def test_general_bom_closes_after_site_production_manager_approval(self):
        bom = self.repo.create_bom(
            site_code="TNN",
            product_id="P001",
            items=[{"material_id": "M001", "quantity": 100, "material_status": "ACTIVE"}],
            created_by=self.employee.user_id,
        )

        self.workflow.submit(bom, self.employee.user_id)
        self.assertEqual(bom.status, Status.APPROVING)
        self.assertEqual(bom.current_step().role, "生產主管")
        self.assertEqual(bom.current_step().site_code, "TNN")

        self.workflow.approve(bom, self.production_manager.user_id, "數量確認無誤")

        # 注意：service 層 approve 完成後狀態為 APPROVED，
        # CLOSED 由 api.py 的 BackgroundTasks 非同步執行會計同步後才觸發
        self.assertEqual(bom.status, Status.APPROVED)
        self.assertEqual(len(self.accounting.synced_events), 0)  # 背景任務未觸發

    def test_high_risk_bom_requires_site_manager_and_taipei_finance(self):
        bom = self.repo.create_bom(
            site_code="TNN",
            product_id="P002",
            items=[{"material_id": "M002", "quantity": 100, "material_status": "ACTIVE"}],
            created_by=self.employee.user_id,
            high_risk=True,
        )

        self.workflow.submit(bom, self.employee.user_id)
        self.assertEqual([step.role for step in bom.approval_steps], ["生產主管", "廠區主管", "台北財務"])

        self.workflow.approve(bom, self.production_manager.user_id)
        self.assertEqual(bom.status, Status.APPROVING)
        self.assertEqual(bom.current_step().role, "廠區主管")

        self.workflow.approve(bom, self.site_manager.user_id)
        self.assertEqual(bom.status, Status.APPROVING)
        self.assertEqual(bom.current_step().role, "台北財務")

        self.workflow.approve(bom, self.finance.user_id)
        # 注意：service 層 approve 完成後狀態為 APPROVED，CLOSED 由 BackgroundTasks 觸發
        self.assertEqual(bom.status, Status.APPROVED)

    def test_wrong_site_approver_cannot_approve_current_step(self):
        bom = self.repo.create_bom(
            site_code="TNN",
            product_id="P003",
            items=[{"material_id": "M003", "quantity": 100, "material_status": "ACTIVE"}],
            created_by=self.employee.user_id,
        )
        self.workflow.submit(bom, self.employee.user_id)

        khh_production_manager = User(
            user_id="PM-KHH",
            name="高雄生產主管",
            position="生產主管",
            department="生產部",
            site_code="KHH",
            site_name="高雄廠",
        )
        self.hr.upsert_user(khh_production_manager)

        with self.assertRaises(ApprovalError):
            self.workflow.approve(bom, khh_production_manager.user_id)

        self.assertEqual(bom.status, Status.APPROVING)

    def test_cross_site_transfer_requires_source_target_and_finance_steps(self):
        transfer = self.repo.create_transfer(
            source_site="TNN",
            target_site="KHH",
            from_warehouse="台南原料倉",
            to_warehouse="高雄原料倉",
            material_id="M001",
            quantity=50,
            created_by=self.employee.user_id,
        )

        self.workflow.submit(transfer, self.employee.user_id)
        self.assertEqual([step.role for step in transfer.approval_steps], ["倉庫主管", "倉庫主管", "台北財務"])
        self.assertEqual([step.site_code for step in transfer.approval_steps], ["TNN", "KHH", "TPE"])

        self.workflow.approve(transfer, self.tnn_warehouse_supervisor.user_id)
        self.workflow.approve(transfer, self.khh_warehouse_supervisor.user_id)
        self.workflow.approve(transfer, self.finance.user_id)

        # 注意：service 層 approve 完成後狀態為 APPROVED，CLOSED 由 BackgroundTasks 觸發
        self.assertEqual(transfer.status, Status.APPROVED)

    def test_quantity_over_safety_limit_is_auto_rejected(self):
        bom = self.repo.create_bom(
            site_code="TNN",
            product_id="P004",
            items=[{"material_id": "M004", "quantity": 1500, "material_status": "ACTIVE"}],
            created_by=self.employee.user_id,
        )

        self.workflow.submit(bom, self.employee.user_id)

        self.assertEqual(bom.status, Status.REJECTED)
        self.assertIn("數量超過安全上限", bom.rejection_reason)

    def test_disabled_material_is_auto_rejected(self):
        transfer = self.repo.create_transfer(
            source_site="TNN",
            target_site="TNN",
            from_warehouse="台南原料倉",
            to_warehouse="台南線邊倉",
            material_id="M-DEPRECATED",  # MockERP 中已設定為 DISABLED 的物料
            quantity=10,
            created_by=self.employee.user_id,
            material_status="DISABLED",
        )

        self.workflow.submit(transfer, self.employee.user_id)

        self.assertEqual(transfer.status, Status.REJECTED)
        self.assertIn("停用", transfer.rejection_reason)

    def test_cancel_document(self):
        bom = self.repo.create_bom(
            site_code="TNN",
            product_id="P006",
            items=[{"material_id": "M006", "quantity": 100, "material_status": "ACTIVE"}],
            created_by=self.employee.user_id,
        )
        self.workflow.submit(bom, self.employee.user_id)
        self.assertEqual(bom.status, Status.APPROVING)
        
        self.workflow.cancel(bom, self.employee.user_id)
        self.assertEqual(bom.status, Status.CANCELED)

    def test_optimistic_locking(self):
        bom = self.repo.create_bom(
            site_code="TNN",
            product_id="P007",
            items=[{"material_id": "M007", "quantity": 10, "material_status": "ACTIVE"}],
            created_by=self.employee.user_id,
        )
        self.workflow.submit(bom, self.employee.user_id)
        
        # Simulate two concurrent reads
        bom1 = self.repo.get_bom(bom.id)
        bom2 = self.repo.get_bom(bom.id)
        
        self.workflow.approve(bom1, self.production_manager.user_id)
        
        with self.assertRaises(ApprovalError) as context:
            # bom2 has old version
            self.workflow.approve(bom2, self.production_manager.user_id)
            
        self.assertIn("Concurrency", str(context.exception))

if __name__ == "__main__":
    unittest.main()
