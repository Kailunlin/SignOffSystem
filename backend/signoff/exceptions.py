"""
自訂例外定義 (exceptions.py)
"""
from rest_framework.exceptions import APIException
from rest_framework import status


class ConcurrencyException(APIException):
    """樂觀鎖衝突：資料已被另一位使用者修改。"""
    status_code = status.HTTP_409_CONFLICT
    default_detail = "資料已被其他人修改，請重新讀取後再試。"
    default_code = "concurrency_conflict"


class InvalidTransitionException(APIException):
    """非法的狀態移轉。"""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "目前狀態不允許此操作。"
    default_code = "invalid_transition"


class PermissionDeniedException(APIException):
    """業務層權限拒絕。"""
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "您沒有權限執行此操作。"
    default_code = "permission_denied"
