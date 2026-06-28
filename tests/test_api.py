import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from signoff_system.api import app, get_db
from signoff_system.models import Base

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=engine)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        
        # Helper to get token
        def get_token(username):
            response = self.client.post("/api/auth/login", data={"username": username, "password": "x"})
            return response.json()["access_token"]
            
        self.emp_token = get_token("EMP001")
        self.pm_tnn_token = get_token("PM-TNN")
        self.wh_tnn_token = get_token("WH-TNN")
        self.wh_khh_token = get_token("WH-KHH")
        self.fin_tpe_token = get_token("FIN-TPE")

    def test_bom_api_flow(self):
        created = self.client.post(
            "/api/boms",
            json={
                "site_code": "TNN",
                "product_id": "P100",
                "items": [{"material_id": "M100", "quantity": 25}],
            },
            headers={"Authorization": f"Bearer {self.emp_token}"}
        )
        self.assertEqual(created.status_code, 200)
        bom_id = created.json()["id"]

        submitted = self.client.post(f"/api/boms/{bom_id}/submit", json={}, headers={"Authorization": f"Bearer {self.emp_token}"})
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.json()["status"], "APPROVING")
        self.assertEqual(submitted.json()["current_step"]["role"], "生產主管")

        approved = self.client.post(
            f"/api/boms/{bom_id}/approve",
            json={"comment": "數量確認無誤"},
            headers={"Authorization": f"Bearer {self.pm_tnn_token}"}
        )
        self.assertEqual(approved.status_code, 200)
        # BackgroundTasks 會將會計同步排入背景，API 立即回傳 APPROVED (CLOSED 由背景任務完成)
        self.assertIn(approved.json()["status"], ["APPROVED", "CLOSED"])

        # Test logs
        logs = self.client.get(f"/api/documents/{bom_id}/logs")
        self.assertEqual(logs.status_code, 200)
        self.assertGreater(len(logs.json()), 0)

    def test_cross_site_transfer_api_flow(self):
        created = self.client.post(
            "/api/transfers",
            json={
                "source_site": "TNN",
                "target_site": "KHH",
                "from_warehouse": "台南原料倉",
                "to_warehouse": "高雄原料倉",
                "material_id": "M200",
                "quantity": 10,
            },
            headers={"Authorization": f"Bearer {self.emp_token}"}
        )
        self.assertEqual(created.status_code, 200)
        transfer_id = created.json()["id"]

        submitted = self.client.post(f"/api/transfers/{transfer_id}/submit", json={}, headers={"Authorization": f"Bearer {self.emp_token}"})
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual([step["site_code"] for step in submitted.json()["approval_steps"]], ["TNN", "KHH", "TPE"])

        denied = self.client.post(f"/api/transfers/{transfer_id}/approve", json={}, headers={"Authorization": f"Bearer {self.fin_tpe_token}"})
        self.assertEqual(denied.status_code, 403)

        first = self.client.post(f"/api/transfers/{transfer_id}/approve", json={}, headers={"Authorization": f"Bearer {self.wh_tnn_token}"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["current_step"]["site_code"], "KHH")

        second = self.client.post(f"/api/transfers/{transfer_id}/approve", json={}, headers={"Authorization": f"Bearer {self.wh_khh_token}"})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["current_step"]["role"], "台北財務")

        final = self.client.post(f"/api/transfers/{transfer_id}/approve", json={}, headers={"Authorization": f"Bearer {self.fin_tpe_token}"})
        self.assertEqual(final.status_code, 200)
        # BackgroundTasks 會將會計同步排入背景，API 立即回傳 APPROVED (CLOSED 由背景任務完成)
        self.assertIn(final.json()["status"], ["APPROVED", "CLOSED"])
        
    def test_cancel_api(self):
        created = self.client.post(
            "/api/boms",
            json={
                "site_code": "TNN",
                "product_id": "P101",
                "items": [{"material_id": "M101", "quantity": 25}],
            },
            headers={"Authorization": f"Bearer {self.emp_token}"}
        )
        bom_id = created.json()["id"]
        self.client.post(f"/api/boms/{bom_id}/submit", json={}, headers={"Authorization": f"Bearer {self.emp_token}"})
        
        canceled = self.client.post(f"/api/boms/{bom_id}/cancel", json={}, headers={"Authorization": f"Bearer {self.emp_token}"})
        self.assertEqual(canceled.status_code, 200)
        self.assertEqual(canceled.json()["status"], "CANCELED")

    def test_tpe_bom_validation(self):
        created = self.client.post(
            "/api/boms",
            json={
                "site_code": "TPE",
                "product_id": "P102",
                "items": [{"material_id": "M102", "quantity": 1}],
            },
            headers={"Authorization": f"Bearer {self.fin_tpe_token}"}
        )
        self.assertEqual(created.status_code, 422)
        self.assertIn("TPE", created.text)

    def test_erp_inventory_auto_reject(self):
        created = self.client.post(
            "/api/transfers",
            json={
                "source_site": "TNN",
                "target_site": "KHH",
                "from_warehouse": "台南原料倉",
                "to_warehouse": "高雄原料倉",
                "material_id": "M-GPU-NVIDIA",
                "quantity": 500,  # exceeds inventory 200 but < 1000
            },
            headers={"Authorization": f"Bearer {self.emp_token}"}
        )
        self.assertEqual(created.status_code, 200)
        transfer_id = created.json()["id"]

        submitted = self.client.post(f"/api/transfers/{transfer_id}/submit", json={}, headers={"Authorization": f"Bearer {self.emp_token}"})
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.json()["status"], "REJECTED")
        self.assertIn("庫存不足", submitted.json()["rejection_reason"])

if __name__ == "__main__":
    unittest.main()
