from django.contrib import admin
from .models import User, Delegation, SignoffDocument, BomDetail, BomItemDetail, TransferDetail, ApprovalStep, ApprovalLog

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('user_id', 'name', 'position', 'site_code')
    search_fields = ('user_id', 'name')

@admin.register(Delegation)
class DelegationAdmin(admin.ModelAdmin):
    list_display = ('delegator', 'delegate', 'start_at', 'end_at')

class BomDetailInline(admin.StackedInline):
    model = BomDetail

class TransferDetailInline(admin.StackedInline):
    model = TransferDetail

@admin.register(SignoffDocument)
class SignoffDocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'document_type', 'status', 'created_by', 'version', 'sync_retries', 'created_at')
    list_filter = ('document_type', 'status')
    inlines = [BomDetailInline, TransferDetailInline]

@admin.register(BomItemDetail)
class BomItemDetailAdmin(admin.ModelAdmin):
    list_display = ('id', 'document', 'material_id', 'quantity', 'material_status')

@admin.register(ApprovalStep)
class ApprovalStepAdmin(admin.ModelAdmin):
    list_display = ('id', 'document', 'sequence', 'role', 'site_code', 'status', 'approver')
    list_filter = ('status', 'role', 'site_code')

@admin.register(ApprovalLog)
class ApprovalLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'document', 'action', 'actor', 'created_at')
    list_filter = ('action',)
