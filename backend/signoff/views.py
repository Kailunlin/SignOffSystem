"""
Views (views.py)
所有 API 端點的 View 實作，職責僅限於：接收請求 -> 驗證 -> 呼叫 Service -> 回傳結果。
"""
from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from .models import (
    SignoffDocument, BomDetail, BomItemDetail,
    TransferDetail, ApprovalLog, DocumentType, DocumentStatus
)
from .serializers import (
    BomDocumentDetailSerializer, TransferDocumentDetailSerializer,
    SignoffDocumentListSerializer, CreateBomDocumentSerializer,
    CreateTransferDocumentSerializer, DocumentActionSerializer,
    ApprovalLogSerializer, DelegationSerializer
)
from .services import DocumentService, is_admin_or_tpe_finance
from .models import Delegation


def visible_documents_for_user(queryset, user):
    if user.is_staff or user.is_superuser:
        return queryset

    own_documents = Q(created_by=user)

    if queryset.model is not SignoffDocument:
        return queryset.none()

    if user.site_code == 'TPE':
        bom_visibility = Q(
            document_type=DocumentType.BOM,
            bom_detail__high_risk=True,
        ) | Q(
            document_type=DocumentType.BOM,
            bom_detail__cost_impact_high=True,
        )
    else:
        bom_visibility = Q(
            document_type=DocumentType.BOM,
            bom_detail__site_code=user.site_code,
        )

    transfer_visibility = Q(
        document_type=DocumentType.MATERIAL_TRANSFER,
        transfer_detail__source_site=user.site_code,
    ) | Q(
        document_type=DocumentType.MATERIAL_TRANSFER,
        transfer_detail__target_site=user.site_code,
    )
    if user.site_code == 'TPE':
        transfer_visibility = Q(document_type=DocumentType.MATERIAL_TRANSFER)

    return queryset.filter(own_documents | bom_visibility | transfer_visibility).distinct()


class BomViewSet(viewsets.GenericViewSet):
    """
    BOM 單據的 CRUD 端點。
    GET /api/boms/           -> list()
    POST /api/boms/          -> create()
    GET /api/boms/{id}/      -> retrieve()
    PUT /api/boms/{id}/      -> update()
    """
    permission_classes = [IsAuthenticated]
    serializer_class = SignoffDocumentListSerializer  # for drf-yasg schema generation

    def get_queryset(self):
        queryset = SignoffDocument.objects.filter(
            document_type=DocumentType.BOM
        ).select_related('bom_detail', 'created_by').prefetch_related(
            'bom_detail__items', 'approval_steps__approver', 'logs__actor'
        )
        return visible_documents_for_user(queryset, self.request.user)

    def list(self, request):
        queryset = self.get_queryset()
        serializer = SignoffDocumentListSerializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            doc = self.get_queryset().get(pk=pk)
        except SignoffDocument.DoesNotExist:
            return Response({'detail': '找不到該單據。'}, status=status.HTTP_404_NOT_FOUND)
        serializer = BomDocumentDetailSerializer(doc)
        return Response(serializer.data)

    @transaction.atomic
    def create(self, request):
        serializer = CreateBomDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        bom_data = serializer.validated_data['bom_detail']
        items_data = bom_data.pop('items')

        doc = SignoffDocument.objects.create(
            document_type=DocumentType.BOM,
            created_by=request.user
        )
        bom = BomDetail.objects.create(document=doc, **bom_data)
        for item_data in items_data:
            BomItemDetail.objects.create(document=bom, **item_data)

        result = BomDocumentDetailSerializer(doc)
        return Response(result.data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request, pk=None):
        try:
            doc = self.get_queryset().get(pk=pk)
        except SignoffDocument.DoesNotExist:
            return Response({'detail': '找不到該單據。'}, status=status.HTTP_404_NOT_FOUND)

        if doc.created_by_id != request.user.id:
            return Response({'detail': 'Only the applicant can update this document.'}, status=status.HTTP_403_FORBIDDEN)
        if doc.status not in ['DRAFT', 'REJECTED']:
            return Response({'detail': 'Only draft or rejected documents can be updated.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = CreateBomDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        bom_data = serializer.validated_data['bom_detail']
        items_data = bom_data.pop('items')

        BomDetail.objects.filter(document=doc).update(**bom_data)
        BomItemDetail.objects.filter(document__document=doc).delete()
        bom = doc.bom_detail
        for item_data in items_data:
            BomItemDetail.objects.create(document=bom, **item_data)

        result = BomDocumentDetailSerializer(doc)
        return Response(result.data)


class TransferViewSet(viewsets.GenericViewSet):
    """
    物料轉移單的 CRUD 端點。
    GET /api/transfers/           -> list()
    POST /api/transfers/          -> create()
    GET /api/transfers/{id}/      -> retrieve()
    PUT /api/transfers/{id}/      -> update()
    """
    permission_classes = [IsAuthenticated]
    serializer_class = SignoffDocumentListSerializer  # for drf-yasg schema generation

    def get_queryset(self):
        queryset = SignoffDocument.objects.filter(
            document_type=DocumentType.MATERIAL_TRANSFER
        ).select_related('transfer_detail', 'created_by').prefetch_related(
            'approval_steps__approver', 'logs__actor'
        )
        return visible_documents_for_user(queryset, self.request.user)

    def list(self, request):
        queryset = self.get_queryset()
        serializer = SignoffDocumentListSerializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            doc = self.get_queryset().get(pk=pk)
        except SignoffDocument.DoesNotExist:
            return Response({'detail': '找不到該單據。'}, status=status.HTTP_404_NOT_FOUND)
        serializer = TransferDocumentDetailSerializer(doc)
        return Response(serializer.data)

    @transaction.atomic
    def create(self, request):
        serializer = CreateTransferDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        transfer_data = serializer.validated_data['transfer_detail']
        doc = SignoffDocument.objects.create(
            document_type=DocumentType.MATERIAL_TRANSFER,
            created_by=request.user
        )
        TransferDetail.objects.create(document=doc, **transfer_data)

        result = TransferDocumentDetailSerializer(doc)
        return Response(result.data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request, pk=None):
        try:
            doc = self.get_queryset().get(pk=pk)
        except SignoffDocument.DoesNotExist:
            return Response({'detail': '找不到該單據。'}, status=status.HTTP_404_NOT_FOUND)

        if doc.created_by_id != request.user.id:
            return Response({'detail': 'Only the applicant can update this document.'}, status=status.HTTP_403_FORBIDDEN)
        if doc.status not in ['DRAFT', 'REJECTED']:
            return Response({'detail': 'Only draft or rejected documents can be updated.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = CreateTransferDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        transfer_data = serializer.validated_data['transfer_detail']
        TransferDetail.objects.filter(document=doc).update(**transfer_data)

        result = TransferDocumentDetailSerializer(doc)
        return Response(result.data)


class DocumentActionView(APIView):
    """
    單據工作流操作的統一入口。
    POST /api/documents/{id}/submit/
    POST /api/documents/{id}/approve/
    POST /api/documents/{id}/reject/
    POST /api/documents/{id}/cancel/
    POST /api/documents/{id}/revise/
    POST /api/documents/{id}/retry-sync/
    """
    permission_classes = [IsAuthenticated]

    def _get_document(self, pk):
        try:
            return SignoffDocument.objects.get(pk=pk)
        except SignoffDocument.DoesNotExist:
            return None

    def post(self, request, pk, action_name):
        doc = self._get_document(pk)
        if doc is None:
            return Response({'detail': '找不到該單據。'}, status=status.HTTP_404_NOT_FOUND)

        serializer = DocumentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        version = serializer.validated_data['version']
        comment = serializer.validated_data.get('comment')

        action_map = {
            'submit': lambda: DocumentService.submit(doc, request.user, version),
            'approve': lambda: DocumentService.approve(doc, request.user, version, comment),
            'reject': lambda: DocumentService.reject(doc, request.user, version, comment),
            'cancel': lambda: DocumentService.cancel(doc, request.user, version),
            'revise': lambda: DocumentService.revise(doc, request.user, version),
            'retry-sync': lambda: DocumentService.retry_sync(doc, request.user, version),
        }

        handler = action_map.get(action_name)
        if handler is None:
            return Response({'detail': f'不支援的操作：{action_name}'}, status=status.HTTP_400_BAD_REQUEST)

        handler()  # ConcurrencyException / InvalidTransitionException 將由 DRF 自動處理

        # 重新讀取最新狀態回傳
        doc.refresh_from_db()
        if doc.document_type == DocumentType.BOM:
            result_serializer = BomDocumentDetailSerializer(doc)
        else:
            result_serializer = TransferDocumentDetailSerializer(doc)

        return Response(result_serializer.data)


class DocumentLogsView(generics.ListAPIView):
    """
    GET /api/documents/{id}/logs/
    取得指定單據的稽核日誌。
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ApprovalLogSerializer

    def get_queryset(self):
        pk = self.kwargs.get('pk')
        visible_docs = visible_documents_for_user(SignoffDocument.objects.filter(id=pk), self.request.user)
        if not visible_docs.exists():
            return ApprovalLog.objects.none()
        return ApprovalLog.objects.filter(
            document_id=pk
        ).select_related('actor').order_by('created_at')


class MyDelegationView(APIView):
    """
    POST   /api/users/me/delegation/  -> 設定代理人
    DELETE /api/users/me/delegation/  -> 移除代理人
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DelegationSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        Delegation.objects.update_or_create(
            delegator=request.user,
            defaults={
                'delegate': serializer.validated_data['delegate'],
                'start_at': serializer.validated_data['start_at'],
                'end_at': serializer.validated_data['end_at'],
            }
        )
        return Response({'detail': '代理人設定成功。'}, status=status.HTTP_200_OK)

    def delete(self, request):
        deleted, _ = Delegation.objects.filter(delegator=request.user).delete()
        if deleted == 0:
            return Response({'detail': '您目前沒有設定代理人。'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'detail': '代理人已移除。'}, status=status.HTTP_204_NO_CONTENT)


class TriggerSlaCheckView(APIView):
    """
    POST /api/admin/trigger-sla-check/
    手動觸發 SLA 逾期催辦掃描。
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone
        from .tasks import check_sla_overdue

        if not is_admin_or_tpe_finance(request.user):
            return Response({'detail': 'Only TPE finance or system administrators can trigger SLA checks.'}, status=status.HTTP_403_FORBIDDEN)

        sla_days = int(request.query_params.get('sla_days', 3))
        threshold = timezone.now() - timezone.timedelta(days=sla_days)
        checked = SignoffDocument.objects.filter(
            status=DocumentStatus.APPROVING,
            updated_at__lt=threshold
        ).count()
        check_sla_overdue.delay()
        return Response({'detail': 'SLA 檢查已排入背景任務。', 'checked': checked})
