from django.urls import path
from .views import (
    BomViewSet, TransferViewSet,
    DocumentActionView, DocumentLogsView, MyDelegationView, TriggerSlaCheckView
)

# BOM ViewSet 路由
bom_list   = BomViewSet.as_view({'get': 'list',   'post': 'create'})
bom_detail = BomViewSet.as_view({'get': 'retrieve', 'put': 'update'})

# Transfer ViewSet 路由
transfer_list   = TransferViewSet.as_view({'get': 'list',   'post': 'create'})
transfer_detail = TransferViewSet.as_view({'get': 'retrieve', 'put': 'update'})

urlpatterns = [
    # BOM
    path('boms/',      bom_list,   name='bom-list'),
    path('boms/<int:pk>/', bom_detail, name='bom-detail'),

    # Transfer
    path('transfers/',          transfer_list,   name='transfer-list'),
    path('transfers/<int:pk>/', transfer_detail, name='transfer-detail'),

    # Document Workflow Actions
    path('documents/<int:pk>/<str:action_name>/', DocumentActionView.as_view(), name='document-action'),

    # Logs
    path('documents/<int:pk>/logs/', DocumentLogsView.as_view(), name='document-logs'),

    # Delegation
    path('users/me/delegation/', MyDelegationView.as_view(), name='my-delegation'),

    # Admin tools
    path('admin/trigger-sla-check/', TriggerSlaCheckView.as_view(), name='trigger-sla-check'),
]
