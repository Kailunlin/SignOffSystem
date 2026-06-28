import pytest
from core.models import User, SignoffDocument, BomDetail, BomItemDetail

@pytest.mark.django_db
def test_create_user():
    user = User.objects.create(user_id='EMP001', name='Test User', position='Manager', site_code='TNN')
    assert user.user_id == 'EMP001'
    assert User.objects.count() == 1

@pytest.mark.django_db
def test_create_signoff_document():
    user = User.objects.create(user_id='EMP001', name='Test User', position='Manager', site_code='TNN')
    doc = SignoffDocument.objects.create(document_type='BOM', status='DRAFT', created_by=user)
    
    assert doc.id is not None
    assert doc.version == 1
    assert doc.status == 'DRAFT'
    assert doc.created_by == user

@pytest.mark.django_db
def test_create_bom_detail():
    user = User.objects.create(user_id='EMP001', name='Test User', position='Manager', site_code='TNN')
    doc = SignoffDocument.objects.create(document_type='BOM', status='DRAFT', created_by=user)
    
    bom = BomDetail.objects.create(
        document=doc,
        site_code='TNN',
        product_id='P-123',
        high_risk=True
    )
    
    assert bom.document_id == doc.id
    assert bom.high_risk is True
    assert hasattr(doc, 'bom_detail')
