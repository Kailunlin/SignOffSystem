"""
Serializers (serializers.py)
定義 DRF 的資料序列化與反序列化規則，並包含業務層的輸入校驗。
"""
from rest_framework import serializers
from .models import (
    User, Delegation, SignoffDocument,
    BomDetail, BomItemDetail, TransferDetail,
    ApprovalStep, ApprovalLog
)


# ==========================================
# User & Delegation Serializers
# ==========================================

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'user_id', 'name', 'position', 'site_code']


class DelegationSerializer(serializers.ModelSerializer):
    delegator_display = UserSerializer(source='delegator', read_only=True)
    delegate_display = UserSerializer(source='delegate', read_only=True)

    class Meta:
        model = Delegation
        fields = ['id', 'delegator', 'delegate', 'delegator_display', 'delegate_display', 'start_at', 'end_at']

    def validate(self, data):
        if data['delegator'] == data['delegate']:
            raise serializers.ValidationError("代理人不能是主管本人。")
        if data['start_at'] >= data['end_at']:
            raise serializers.ValidationError("代理結束時間必須晚於起始時間。")
        return data


# ==========================================
# BOM Serializers
# ==========================================

class BomItemDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = BomItemDetail
        fields = ['id', 'material_id', 'quantity', 'material_status']

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("數量必須大於 0。")
        return value


class BomDetailReadSerializer(serializers.ModelSerializer):
    items = BomItemDetailSerializer(many=True, read_only=True)

    class Meta:
        model = BomDetail
        fields = ['site_code', 'product_id', 'high_risk', 'cost_impact_high', 'reason', 'items']


class BomDetailWriteSerializer(serializers.ModelSerializer):
    items = BomItemDetailSerializer(many=True)

    class Meta:
        model = BomDetail
        fields = ['site_code', 'product_id', 'high_risk', 'cost_impact_high', 'reason', 'items']

    def validate_site_code(self, value):
        if value == 'TPE':
            raise serializers.ValidationError("台北廠區 (TPE) 不得發起 BOM 單。")
        return value

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("BOM 至少需要一筆物料明細。")
        return value


# ==========================================
# Transfer Serializers
# ==========================================

class TransferDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransferDetail
        fields = ['source_site', 'target_site', 'from_warehouse', 'to_warehouse', 'material_id', 'quantity', 'urgent']

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("數量必須大於 0。")
        return value


# ==========================================
# ApprovalStep & Log Serializers
# ==========================================

class ApprovalStepSerializer(serializers.ModelSerializer):
    approver_display = UserSerializer(source='approver', read_only=True)
    approver_id = serializers.CharField(source='approver.user_id', read_only=True, allow_null=True)

    class Meta:
        model = ApprovalStep
        fields = ['id', 'sequence', 'role', 'site_code', 'status', 'approver_id', 'approver_display', 'delegated_from', 'comment']


class ApprovalLogSerializer(serializers.ModelSerializer):
    actor_display = UserSerializer(source='actor', read_only=True)
    actor_id = serializers.CharField(source='actor.user_id', read_only=True)

    class Meta:
        model = ApprovalLog
        fields = ['id', 'action', 'actor_id', 'actor_display', 'comment', 'created_at']


# ==========================================
# Document Serializers
# ==========================================

class SignoffDocumentListSerializer(serializers.ModelSerializer):
    """列表頁用：輕量化，僅包含摘要欄位。"""
    created_by = serializers.CharField(source='created_by.user_id', read_only=True)
    created_by_display = UserSerializer(source='created_by', read_only=True)
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    bom_detail = BomDetailReadSerializer(read_only=True)
    transfer_detail = TransferDetailSerializer(read_only=True)
    approval_steps = ApprovalStepSerializer(many=True, read_only=True)

    class Meta:
        model = SignoffDocument
        fields = ['id', 'document_type', 'document_type_display', 'status', 'status_display',
                  'created_by', 'created_by_display', 'version', 'sync_retries', 'created_at',
                  'updated_at', 'bom_detail', 'transfer_detail', 'approval_steps']


class BomDocumentDetailSerializer(serializers.ModelSerializer):
    """BOM 詳情頁用。"""
    bom_detail = BomDetailReadSerializer(read_only=True)
    approval_steps = ApprovalStepSerializer(many=True, read_only=True)
    logs = ApprovalLogSerializer(many=True, read_only=True)
    created_by = serializers.CharField(source='created_by.user_id', read_only=True)
    created_by_display = UserSerializer(source='created_by', read_only=True)

    class Meta:
        model = SignoffDocument
        fields = ['id', 'document_type', 'status', 'created_by', 'created_by_display', 'version', 'sync_retries',
                  'created_at', 'updated_at', 'bom_detail', 'approval_steps', 'logs']


class TransferDocumentDetailSerializer(serializers.ModelSerializer):
    """轉移單詳情頁用。"""
    transfer_detail = TransferDetailSerializer(read_only=True)
    approval_steps = ApprovalStepSerializer(many=True, read_only=True)
    logs = ApprovalLogSerializer(many=True, read_only=True)
    created_by = serializers.CharField(source='created_by.user_id', read_only=True)
    created_by_display = UserSerializer(source='created_by', read_only=True)

    class Meta:
        model = SignoffDocument
        fields = ['id', 'document_type', 'status', 'created_by', 'created_by_display', 'version', 'sync_retries',
                  'created_at', 'updated_at', 'transfer_detail', 'approval_steps', 'logs']


class CreateBomDocumentSerializer(serializers.Serializer):
    """建立 BOM 單據的輸入校驗。"""
    bom_detail = BomDetailWriteSerializer()


class CreateTransferDocumentSerializer(serializers.Serializer):
    """建立轉移單的輸入校驗。"""
    transfer_detail = TransferDetailSerializer()


class DocumentActionSerializer(serializers.Serializer):
    """單據工作流操作 (approve/reject/cancel...) 的輸入校驗。"""
    version = serializers.IntegerField(required=True, help_text="目前單據版本號，用於樂觀鎖防護")
    comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)
