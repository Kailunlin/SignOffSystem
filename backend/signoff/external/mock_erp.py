"""
signoff/external/mock_erp.py
模擬外部 ERP 系統服務，供開發與測試環境使用。
"""
import random


class ERPSyncException(Exception):
    """外部系統同步失敗的例外。"""
    pass


class MockERPService:
    """
    模擬 ERP 系統的所有互動。
    在正式環境中可替換為真實的 HTTP Client。
    """

    # 控制旗標：設為 True 時強制讓同步失敗（方便測試 SYNC_FAILED 流程）
    FORCE_SYNC_FAILURE = False

    # 模擬庫存資料庫：{material_id: available_quantity}
    MOCK_INVENTORY = {
        'MAT-001': 500,
        'MAT-009': 200,
        'MAT-999': 10,
    }

    @classmethod
    def check_inventory(cls, material_id: str, required_quantity: int) -> dict:
        """
        查詢指定物料的可用庫存。
        若庫存不足，回傳包含差額明細的結果；否則回傳成功。
        """
        available = cls.MOCK_INVENTORY.get(material_id, 0)
        if available < required_quantity:
            return {
                'success': False,
                'material_id': material_id,
                'available': available,
                'required': required_quantity,
                'shortage': required_quantity - available,
                'message': f"物料 {material_id} 庫存不足：現有 {available}，需求 {required_quantity}，短缺 {required_quantity - available}。"
            }
        return {
            'success': True,
            'material_id': material_id,
            'available': available,
            'required': required_quantity,
        }

    @classmethod
    def sync_bom(cls, document_id: int):
        """
        模擬 BOM 單同步至 ERP 生產模組。
        隨機有 10% 機率失敗（模擬外部系統不穩定）。
        """
        if cls.FORCE_SYNC_FAILURE:
            raise ERPSyncException(f"[MOCK] BOM #{document_id} 同步失敗：ERP 系統回應超時。")

        # 模擬 10% 失敗率
        if random.random() < 0.1:
            raise ERPSyncException(f"[MOCK] BOM #{document_id} 同步失敗：ERP 系統回應超時。")

        print(f"[MockERP] BOM #{document_id} 已成功同步至 ERP 生產模組。")

    @classmethod
    def sync_transfer(cls, document_id: int):
        """
        模擬物料轉移單同步至外部系統（含會計分錄生成）。
        隨機有 10% 機率失敗。
        """
        if cls.FORCE_SYNC_FAILURE:
            raise ERPSyncException(f"[MOCK] Transfer #{document_id} 同步失敗：外部系統不可用。")

        if random.random() < 0.1:
            raise ERPSyncException(f"[MOCK] Transfer #{document_id} 同步失敗：外部系統不可用。")

        print(f"[MockERP] Transfer #{document_id} 已成功同步至外部系統，會計分錄已生成。")
