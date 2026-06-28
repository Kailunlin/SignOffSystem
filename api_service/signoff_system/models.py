from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class UserORM(Base):
    __tablename__ = "core_user"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    position = Column(String(50), nullable=False)
    department = Column(String(100), nullable=True)
    site_code = Column(String(10), nullable=True)
    site_name = Column(String(100), nullable=True)


class DelegationORM(Base):
    """代理人設定：主管可設定讓代理人在指定區間內代為簽核"""
    __tablename__ = "core_delegation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    delegator_id = Column(String(50), nullable=False, index=True)   # 被代理人 (主管)
    delegate_id = Column(String(50), nullable=False)                 # 代理人
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SignoffDocumentORM(Base):
    __tablename__ = "core_signoffdocument"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_type = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_by = Column(String(50), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    sync_retries = Column(Integer, nullable=False, default=0)  # 會計同步失敗重試次數

    __mapper_args__ = {
        "version_id_col": version,
    }

    bom_detail = relationship("BOMDetailORM", back_populates="document", uselist=False, cascade="all, delete-orphan")
    transfer_detail = relationship("TransferDetailORM", back_populates="document", uselist=False, cascade="all, delete-orphan")
    steps = relationship("ApprovalStepORM", back_populates="document", cascade="all, delete-orphan", order_by="ApprovalStepORM.sequence")
    logs = relationship("ApprovalLogORM", back_populates="document", cascade="all, delete-orphan", order_by="ApprovalLogORM.created_at")


class BOMDetailORM(Base):
    __tablename__ = "core_bomdetail"

    document_id = Column(Integer, ForeignKey("core_signoffdocument.id"), primary_key=True)
    site_code = Column(String(10), nullable=True)
    product_id = Column(String(50), nullable=False)
    high_risk = Column(Boolean, default=False)
    cost_impact_high = Column(Boolean, default=False)
    reason = Column(Text, nullable=True)          # 建立原因 (SA 補充)
    attachments = Column(Text, nullable=True)     # 附件 URL / ID (SA 補充)

    document = relationship("SignoffDocumentORM", back_populates="bom_detail")
    items = relationship("BOMItemORM", back_populates="bom_detail", cascade="all, delete-orphan")


class BOMItemORM(Base):
    __tablename__ = "core_bomitemdetail"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("core_bomdetail.document_id"), nullable=False)
    material_id = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False)
    material_status = Column(String(20), nullable=False)

    bom_detail = relationship("BOMDetailORM", back_populates="items")


class TransferDetailORM(Base):
    __tablename__ = "core_transferdetail"

    document_id = Column(Integer, ForeignKey("core_signoffdocument.id"), primary_key=True)
    source_site = Column(String(10), nullable=True)
    target_site = Column(String(10), nullable=True)
    from_warehouse = Column(String(50), nullable=False)
    to_warehouse = Column(String(50), nullable=False)
    material_id = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False)
    material_status = Column(String(20), nullable=False)
    urgent = Column(Boolean, default=False)
    reason = Column(Text, nullable=True)          # 轉移原因 (SA 補充)

    document = relationship("SignoffDocumentORM", back_populates="transfer_detail")


class ApprovalStepORM(Base):
    __tablename__ = "core_approvalstep"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("core_signoffdocument.id"), nullable=False)
    sequence = Column(Integer, nullable=False)
    role = Column(String(50), nullable=False)
    site_code = Column(String(10), nullable=True)
    status = Column(String(20), nullable=False)
    approver_id = Column(String(50), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)
    delegated_from = Column(String(50), nullable=True)  # 若由代理人執行，記錄原始簽核人

    document = relationship("SignoffDocumentORM", back_populates="steps")


class ApprovalLogORM(Base):
    __tablename__ = "core_approvallog"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("core_signoffdocument.id"), nullable=False)
    action = Column(String(30), nullable=False)
    actor_id = Column(String(50), nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    document = relationship("SignoffDocumentORM", back_populates="logs")
