from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils.translation import gettext_lazy as _

# ==========================================
# Enums (TextChoices)
# ==========================================

class DocumentType(models.TextChoices):
    BOM = 'BOM', _('物料清單 (BOM)')
    MATERIAL_TRANSFER = 'MATERIAL_TRANSFER', _('物料轉移 (Material Transfer)')

class DocumentStatus(models.TextChoices):
    DRAFT = 'DRAFT', _('草稿')
    SUBMITTED = 'SUBMITTED', _('已提交 (系統檢查中)')
    APPROVING = 'APPROVING', _('簽核中')
    APPROVED = 'APPROVED', _('簽核核准')
    REJECTED = 'REJECTED', _('已駁回')
    CLOSED = 'CLOSED', _('已結案 (外部同步成功)')
    CANCELED = 'CANCELED', _('已撤銷')
    SYNC_FAILED = 'SYNC_FAILED', _('外部同步失敗')

class ApprovalStepStatus(models.TextChoices):
    PENDING = 'PENDING', _('待簽核')
    APPROVED = 'APPROVED', _('已同意')
    REJECTED = 'REJECTED', _('已駁回')

class ActionType(models.TextChoices):
    SUBMIT = 'SUBMIT', _('提交')
    APPROVE = 'APPROVE', _('核准')
    REJECT = 'REJECT', _('駁回')
    AUTO_REJECT = 'AUTO_REJECT', _('系統自動駁回')
    CANCEL = 'CANCEL', _('撤回')
    REVISE = 'REVISE', _('修改重提')
    RETRY_SYNC = 'RETRY_SYNC', _('重試外部同步')
    CLOSE = 'CLOSE', _('結案')
    SLA_REMIND = 'SLA_REMIND', _('SLA 催辦')
    SYNC_FAILED = 'SYNC_FAILED', _('外部同步失敗')

class MaterialStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', _('啟用中')
    DISABLED = 'DISABLED', _('已停用')


# ==========================================
# Users & Auth Models
# ==========================================

class UserManager(BaseUserManager):
    def create_user(self, user_id, name, position, site_code, password=None, **extra_fields):
        if not user_id:
            raise ValueError('Users must have a user_id')
        user = self.model(
            user_id=user_id,
            name=name,
            position=position,
            site_code=site_code,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, user_id, name, position, site_code, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(user_id, name, position, site_code, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    """使用者模型 - 同步自 HR 系統"""
    user_id = models.CharField(max_length=50, unique=True, verbose_name="員工代號")
    name = models.CharField(max_length=100, verbose_name="姓名")
    position = models.CharField(max_length=50, verbose_name="職位")
    site_code = models.CharField(max_length=10, verbose_name="所屬廠區")
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    objects = UserManager()

    USERNAME_FIELD = 'user_id'
    REQUIRED_FIELDS = ['name', 'position', 'site_code']

    class Meta:
        db_table = 'users'

    def __str__(self):
        return f"{self.name} ({self.user_id})"

class Delegation(models.Model):
    """代理人設定表"""
    delegator = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='delegation_given', verbose_name="被代理的主管"
    )
    delegate = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='delegations_received', verbose_name="代理人"
    )
    start_at = models.DateTimeField(verbose_name="代理生效起始時間")
    end_at = models.DateTimeField(verbose_name="代理生效結束時間")

    class Meta:
        db_table = 'delegations'

    def __str__(self):
        return f"{self.delegator.name} -> {self.delegate.name}"


# ==========================================
# Core Document Models
# ==========================================

class SignoffDocument(models.Model):
    """主單據表 - 結合樂觀鎖的單據根實體"""
    document_type = models.CharField(max_length=30, choices=DocumentType.choices)
    status = models.CharField(max_length=20, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='documents')
    version = models.IntegerField(default=1, verbose_name="樂觀鎖版本號")
    sync_retries = models.IntegerField(default=0, verbose_name="外部同步重試次數")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'signoff_documents'

    def __str__(self):
        return f"{self.get_document_type_display()} #{self.id} [{self.status}]"


class BomDetail(models.Model):
    """BOM 單據屬性"""
    document = models.OneToOneField(SignoffDocument, on_delete=models.CASCADE, related_name='bom_detail', primary_key=True)
    site_code = models.CharField(max_length=10)
    product_id = models.CharField(max_length=50)
    high_risk = models.BooleanField(default=False)
    cost_impact_high = models.BooleanField(default=False)
    reason = models.TextField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = 'bom_details'

    def __str__(self):
        return f"BOM Detail for Doc #{self.document_id}"


class BomItemDetail(models.Model):
    """BOM 明細項目"""
    document = models.ForeignKey(BomDetail, on_delete=models.CASCADE, related_name='items')
    material_id = models.CharField(max_length=50)
    quantity = models.PositiveIntegerField()
    material_status = models.CharField(max_length=20, choices=MaterialStatus.choices)

    class Meta:
        db_table = 'bom_item_details'

    def __str__(self):
        return f"Item {self.material_id} x{self.quantity}"


class TransferDetail(models.Model):
    """物料轉移單據屬性"""
    document = models.OneToOneField(SignoffDocument, on_delete=models.CASCADE, related_name='transfer_detail', primary_key=True)
    source_site = models.CharField(max_length=10)
    target_site = models.CharField(max_length=10)
    from_warehouse = models.CharField(max_length=50)
    to_warehouse = models.CharField(max_length=50)
    material_id = models.CharField(max_length=50)
    quantity = models.PositiveIntegerField()
    urgent = models.BooleanField(default=False)

    class Meta:
        db_table = 'transfer_details'

    def __str__(self):
        return f"Transfer {self.material_id} ({self.source_site} -> {self.target_site})"


# ==========================================
# Workflow & Audit Models
# ==========================================

class ApprovalStep(models.Model):
    """動態簽核關卡表"""
    document = models.ForeignKey(SignoffDocument, on_delete=models.CASCADE, related_name='approval_steps')
    sequence = models.PositiveIntegerField(verbose_name="關卡順序")
    role = models.CharField(max_length=50, verbose_name="所需角色")
    site_code = models.CharField(max_length=10, verbose_name="所需廠區")
    status = models.CharField(max_length=20, choices=ApprovalStepStatus.choices, default=ApprovalStepStatus.PENDING)
    
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, 
        verbose_name="實際簽核人", related_name='steps_approved'
    )
    delegated_from = models.CharField(max_length=50, null=True, blank=True, verbose_name="原被代理主管 ID")
    comment = models.TextField(null=True, blank=True, verbose_name="審核意見")

    class Meta:
        db_table = 'approval_steps'
        ordering = ['sequence']

    def __str__(self):
        return f"Doc #{self.document_id} - Step {self.sequence} ({self.status})"


class ApprovalLog(models.Model):
    """稽核日誌表 - Append Only"""
    document = models.ForeignKey(SignoffDocument, on_delete=models.CASCADE, related_name='logs')
    action = models.CharField(max_length=30, choices=ActionType.choices)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='performed_logs')
    comment = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'approval_logs'
        ordering = ['created_at']

    def __str__(self):
        return f"Doc #{self.document_id} Log: {self.get_action_display()} by {self.actor.name}"
