from django.db import models

class User(models.Model):
    user_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    position = models.CharField(max_length=50)
    site_code = models.CharField(max_length=10)

    def __str__(self):
        return f"{self.name} ({self.user_id})"

class Delegation(models.Model):
    delegator = models.OneToOneField(User, on_delete=models.CASCADE, related_name='delegated_to')
    delegate = models.ForeignKey(User, on_delete=models.CASCADE, related_name='acting_as')
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    def __str__(self):
        return f"{self.delegator.name} -> {self.delegate.name}"

class SignoffDocument(models.Model):
    document_type = models.CharField(max_length=30)
    status = models.CharField(max_length=20)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='documents_created')
    version = models.IntegerField(default=1)
    sync_retries = models.IntegerField(default=0)
    rejection_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.document_type} #{self.id} ({self.status})"

class BomDetail(models.Model):
    document = models.OneToOneField(SignoffDocument, on_delete=models.CASCADE, primary_key=True, related_name='bom_detail')
    site_code = models.CharField(max_length=10)
    product_id = models.CharField(max_length=50)
    high_risk = models.BooleanField(default=False)
    cost_impact_high = models.BooleanField(default=False)
    reason = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"BOM Detail for {self.document.id}"

class BomItemDetail(models.Model):
    document = models.ForeignKey(SignoffDocument, on_delete=models.CASCADE, related_name='bom_items')
    material_id = models.CharField(max_length=50)
    quantity = models.IntegerField()
    material_status = models.CharField(max_length=20)

    def __str__(self):
        return f"Item {self.material_id} x{self.quantity}"

class TransferDetail(models.Model):
    document = models.OneToOneField(SignoffDocument, on_delete=models.CASCADE, primary_key=True, related_name='transfer_detail')
    source_site = models.CharField(max_length=10)
    target_site = models.CharField(max_length=10)
    from_warehouse = models.CharField(max_length=50)
    to_warehouse = models.CharField(max_length=50)
    material_id = models.CharField(max_length=50)
    quantity = models.IntegerField()
    urgent = models.BooleanField(default=False)
    reason = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Transfer Detail for {self.document.id}"

class ApprovalStep(models.Model):
    document = models.ForeignKey(SignoffDocument, on_delete=models.CASCADE, related_name='approval_steps')
    sequence = models.IntegerField()
    role = models.CharField(max_length=50)
    site_code = models.CharField(max_length=10)
    status = models.CharField(max_length=20, default='PENDING')
    approver = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='approved_steps')
    delegated_from = models.CharField(max_length=50, null=True, blank=True)
    comment = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Step {self.sequence} - {self.role} ({self.status})"

class ApprovalLog(models.Model):
    document = models.ForeignKey(SignoffDocument, on_delete=models.CASCADE, related_name='approval_logs')
    action = models.CharField(max_length=30)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='action_logs')
    comment = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Log {self.action} on Doc #{self.document.id}"
