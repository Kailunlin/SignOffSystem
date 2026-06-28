import sys
import os

sys.path.insert(0, os.path.abspath('src'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from signoff_system.models import Base
from signoff_system.services import DatabaseRepository

SQLALCHEMY_DATABASE_URL = "sqlite:///./signoff.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def seed_data():
    db = SessionLocal()
    try:
        repo = DatabaseRepository(db)

        repo.create_bom(
            product_id="P-LAPTOP-001",
            items=[{"material_id": "M-CPU-INTEL", "quantity": 1, "material_status": "ACTIVE"},
                   {"material_id": "M-RAM-64G", "quantity": 2, "material_status": "ACTIVE"}],
            created_by="EMP001", site_code="TNN",
            high_risk=False, cost_impact_high=False,
            reason="新產品量產導入，建立初始 BOM", attachments="",
        )
        print("建立: 台南廠普通 BOM 單 #1")

        repo.create_bom(
            product_id="P-DESKTOP-PRO",
            items=[{"material_id": "M-GPU-NVIDIA", "quantity": 2, "material_status": "ACTIVE"}],
            created_by="EMP-KHH", site_code="KHH",
            high_risk=True, cost_impact_high=True,
            reason="高性能工作站 GPU 建立，高風險管制物料", attachments="spec_GPU.pdf",
        )
        print("建立: 高雄廠高風險 BOM 單 #2")

        repo.create_bom(
            product_id="P-SERVER-01",
            items=[{"material_id": "M-RAM-64G", "quantity": 10, "material_status": "ACTIVE"}],
            created_by="EMP-KHH", site_code="KHH",
            high_risk=False, cost_impact_high=True,
            reason="高雄廠伺服器擴充用記憶體，成本影響大", attachments="po_2024.pdf",
        )
        print("建立: 高雄廠高成本 BOM 單 #3")

        repo.create_transfer(
            from_warehouse="台南原料倉", to_warehouse="台南線邊倉",
            material_id="M-SCREW-01", quantity=5000,
            created_by="EMP001", material_status="ACTIVE",
            source_site="TNN", target_site="TNN",
            urgent=False, reason="產線補料，維持生產節拍",
        )
        print("建立: 台南廠內轉移單 #4")

        repo.create_transfer(
            from_warehouse="台南成品倉", to_warehouse="高雄支援倉",
            material_id="M-PANEL-15", quantity=200,
            created_by="EMP001", material_status="ACTIVE",
            source_site="TNN", target_site="KHH",
            urgent=True, reason="高雄廠急需補料，跨廠緊急調撥",
        )
        print("建立: 台南轉高雄跨廠急件單 #5")

        repo.create_bom(
            product_id="P-LAPTOP-002",
            items=[{"material_id": "M-CPU-INTEL", "quantity": 5, "material_status": "ACTIVE"}],
            created_by="EMP001", site_code="TNN",
            high_risk=False, cost_impact_high=False,
            reason="第二款筆電新 BOM 建立", attachments="",
        )
        print("建立: 台南廠第二筆 BOM 草稿 #6")

        print("\n測試資料建立完成！共 6 筆單據。")
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
