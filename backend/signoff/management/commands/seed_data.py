from django.core.management.base import BaseCommand
from signoff.models import User, SignoffDocument, BomDetail, BomItemDetail, TransferDetail, DocumentType, DocumentStatus, MaterialStatus
from django.db import transaction

class Command(BaseCommand):
    help = 'Seed the database with sample users and documents'

    @transaction.atomic
    def handle(self, *args, **kwargs):
        self.stdout.write('Clearing existing data...')
        SignoffDocument.objects.all().delete()
        User.objects.all().delete()
        
        self.stdout.write('Creating users...')
        users_data = [
            # Supervisors
            {'user_id': 'MGR_TPE', 'name': '台北主管', 'position': '台北財務', 'site_code': 'TPE', 'password': 'password123'},
            {'user_id': 'MGR_TNN', 'name': '台南主管', 'position': '生產主管', 'site_code': 'TNN', 'password': 'password123'},
            {'user_id': 'MGR_KHH', 'name': '高雄主管', 'position': '倉庫主管', 'site_code': 'KHH', 'password': 'password123'},
            # Staff
            {'user_id': 'EMP_TPE', 'name': '台北員工', 'position': '財務專員', 'site_code': 'TPE', 'password': 'password123'},
            {'user_id': 'EMP_TNN', 'name': '台南員工', 'position': '生產專員', 'site_code': 'TNN', 'password': 'password123'},
            {'user_id': 'EMP_KHH', 'name': '高雄員工', 'position': '倉管專員', 'site_code': 'KHH', 'password': 'password123'},
        ]
        
        users = {}
        for u in users_data:
            user = User.objects.create_user(**u)
            users[u['user_id']] = user
            
        self.stdout.write('Creating sample BOM documents...')
        
        # TNN BOM (DRAFT)
        doc1 = SignoffDocument.objects.create(
            document_type=DocumentType.BOM,
            status=DocumentStatus.DRAFT,
            created_by=users['EMP_TNN']
        )
        bom1 = BomDetail.objects.create(
            document=doc1,
            site_code='TNN',
            product_id='PRD-TNN-001',
            high_risk=False,
            cost_impact_high=False,
            reason='測試台南 BOM 草稿'
        )
        BomItemDetail.objects.create(
            document=bom1,
            material_id='MAT-001',
            quantity=100,
            material_status=MaterialStatus.ACTIVE
        )
        
        # KHH BOM (High Risk)
        doc2 = SignoffDocument.objects.create(
            document_type=DocumentType.BOM,
            status=DocumentStatus.SUBMITTED,
            created_by=users['EMP_KHH']
        )
        bom2 = BomDetail.objects.create(
            document=doc2,
            site_code='KHH',
            product_id='PRD-KHH-999',
            high_risk=True,
            cost_impact_high=True,
            reason='測試高雄高風險 BOM'
        )
        BomItemDetail.objects.create(
            document=bom2,
            material_id='MAT-009',
            quantity=500,
            material_status=MaterialStatus.ACTIVE
        )

        self.stdout.write('Creating sample Transfer documents...')
        
        # Transfer TNN -> KHH (DRAFT)
        doc3 = SignoffDocument.objects.create(
            document_type=DocumentType.MATERIAL_TRANSFER,
            status=DocumentStatus.DRAFT,
            created_by=users['EMP_TNN']
        )
        TransferDetail.objects.create(
            document=doc3,
            source_site='TNN',
            target_site='KHH',
            from_warehouse='TNN_WH_A',
            to_warehouse='KHH_WH_B',
            material_id='MAT-001',
            quantity=200,
            urgent=True
        )

        self.stdout.write(self.style.SUCCESS('Successfully seeded the database with test data.'))
