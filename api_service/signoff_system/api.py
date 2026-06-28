from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .auth import create_access_token, get_current_user_id
from .domain import ApprovalError, ApprovalStep, SignoffDocument, Status, User
from .models import Base
from .services import (
    ApprovalWorkflow, DatabaseRepository, do_accounting_sync,
    MockAccountingService, MockERPService, MockHRService, NotificationService,
)

import os
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "signoff.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

seed_users = [
    User(user_id="PM-TNN",    name="台南生產主管", position="生產主管", department="生產部",  site_code="TNN", site_name="台南廠"),
    User(user_id="PM-KHH",    name="高雄生產主管", position="生產主管", department="生產部",  site_code="KHH", site_name="高雄廠"),
    User(user_id="GM-TNN",    name="台南廠區主管", position="廠區主管", department="廠務部",  site_code="TNN", site_name="台南廠"),
    User(user_id="GM-KHH",    name="高雄廠區主管", position="廠區主管", department="廠務部",  site_code="KHH", site_name="高雄廠"),
    User(user_id="WH-TNN",    name="台南倉庫主管", position="倉庫主管", department="倉儲部",  site_code="TNN", site_name="台南廠"),
    User(user_id="WH-KHH",    name="高雄倉庫主管", position="倉庫主管", department="倉儲部",  site_code="KHH", site_name="高雄廠"),
    User(user_id="FIN-TPE",   name="台北財務",     position="台北財務", department="財務部",  site_code="TPE", site_name="總公司台北場"),
    User(user_id="EMP001",    name="林員工",       position="員工",     department="生產部",  site_code="TNN", site_name="台南廠"),
    User(user_id="EMP-KHH",   name="陳員工",       position="員工",     department="生產部",  site_code="KHH", site_name="高雄廠"),
    User(user_id="ADMIN-TPE", name="系統管理員",   position="系統管理員", department="資訊部", site_code="TPE", site_name="總公司台北場"),
]

hr_service = MockHRService(seed_users)
accounting_service = MockAccountingService()
notification_service = NotificationService()
erp_service = MockERPService()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_workflow(db=Depends(get_db)):
    repo = DatabaseRepository(db)
    return ApprovalWorkflow(repo, hr_service, accounting_service, notification_service, erp_service)


def get_repo(db=Depends(get_db)):
    return DatabaseRepository(db)


app = FastAPI(
    title="簽核系統 API",
    description="BOM 與物料轉移簽核系統",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import os
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/app", StaticFiles(directory=_frontend_dir, html=True), name="frontend")


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/app")


# ─────────────────────── Pydantic Models ───────────────────────

class BOMItemRequest(BaseModel):
    material_id: str
    quantity: int = Field(gt=0)
    material_status: str = "ACTIVE"


class CreateBOMRequest(BaseModel):
    site_code: str
    product_id: str
    items: list[BOMItemRequest]
    high_risk: bool = False
    cost_impact_high: bool = False
    reason: str = ""         # SA: 建立原因
    attachments: str = ""    # SA: 附件參考

    @validator("site_code")
    def validate_site_code(cls, v):
        if v == "TPE":
            raise ValueError("總公司台北場 (TPE) 嚴格禁止發起生產用 BOM 單")
        return v


class CreateTransferRequest(BaseModel):
    source_site: str
    target_site: str
    from_warehouse: str
    to_warehouse: str
    material_id: str
    quantity: int = Field(gt=0)
    material_status: str = "ACTIVE"
    urgent: bool = False
    reason: str = ""         # SA: 轉移原因


class ActionRequest(BaseModel):
    comment: str = ""
    reason: str = ""


class SetDelegationRequest(BaseModel):
    delegate_id: str
    start_at: datetime
    end_at: datetime


class DocumentResponse(BaseModel):
    id: int
    document_type: str
    material_id: Optional[str] = None
    quantity: Optional[int] = None
    status: str
    version: int
    created_by: str
    approved_by: Optional[str]
    rejection_reason: str
    site_code: Optional[str] = None
    source_site: Optional[str] = None
    target_site: Optional[str] = None
    current_step: Optional[dict] = None
    approval_steps: list[dict] = []
    items: list[dict] = []

    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    sync_retries: int = 0
    reason: Optional[str] = None
    attachments: Optional[str] = None
    urgent: Optional[bool] = None
    product_id: Optional[str] = None
    high_risk: Optional[bool] = None
    cost_impact_high: Optional[bool] = None


class LogResponse(BaseModel):
    document_type: str
    document_id: int
    action: str
    actor_id: str
    comment: str
    created_at: str


# ─────────────────────── AUTH ───────────────────────

@app.post("/api/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = hr_service.get_user(form_data.username)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username")
    access_token = create_access_token(data={"sub": user.user_id})
    return {"access_token": access_token, "token_type": "bearer"}


# ─────────────────────── BOM ───────────────────────

@app.get("/api/boms", response_model=list[DocumentResponse])
def list_boms(
    status: Optional[str] = Query(None),
    created_by: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    repo: DatabaseRepository = Depends(get_repo),
) -> list[DocumentResponse]:
    return [to_response(d) for d in repo.list_boms(status=status, created_by=created_by, skip=skip, limit=limit)]


@app.post("/api/boms", response_model=DocumentResponse)
def create_bom(
    request: CreateBOMRequest,
    current_user_id: str = Depends(get_current_user_id),
    repo: DatabaseRepository = Depends(get_repo),
) -> DocumentResponse:
    return to_response(repo.create_bom(
        product_id=request.product_id,
        items=[i.dict() for i in request.items],
        created_by=current_user_id,
        site_code=request.site_code,
        high_risk=request.high_risk,
        cost_impact_high=request.cost_impact_high,
        reason=request.reason,
        attachments=request.attachments,
    ))


@app.get("/api/boms/{bom_id}", response_model=DocumentResponse)
def get_bom(bom_id: int, repo: DatabaseRepository = Depends(get_repo)) -> DocumentResponse:
    return to_response_or_404(lambda: repo.get_bom(bom_id))


@app.post("/api/boms/{bom_id}/submit", response_model=DocumentResponse)
def submit_bom(bom_id: int, request: ActionRequest, current_user_id: str = Depends(get_current_user_id), workflow: ApprovalWorkflow = Depends(get_workflow)) -> DocumentResponse:
    return to_response_or_404(lambda: workflow.submit(workflow.repository.get_bom(bom_id), current_user_id, request.comment))


@app.post("/api/boms/{bom_id}/approve", response_model=DocumentResponse)
def approve_bom(
    bom_id: int,
    request: ActionRequest,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(get_current_user_id),
    workflow: ApprovalWorkflow = Depends(get_workflow),
) -> DocumentResponse:
    doc = workflow.repository.get_bom(bom_id)
    result = to_response_or_404(lambda: workflow.approve(doc, current_user_id, request.comment))
    # 若簽核後狀態變成 APPROVED，將會計同步排入背景執行
    updated = workflow.repository.get_bom(bom_id)
    if updated.status == Status.APPROVED:
        background_tasks.add_task(do_accounting_sync, updated, workflow, current_user_id)
    return result


@app.post("/api/boms/{bom_id}/reject", response_model=DocumentResponse)
def reject_bom(bom_id: int, request: ActionRequest, current_user_id: str = Depends(get_current_user_id), workflow: ApprovalWorkflow = Depends(get_workflow)) -> DocumentResponse:
    return to_response_or_404(lambda: workflow.reject(workflow.repository.get_bom(bom_id), current_user_id, request.reason))


@app.post("/api/boms/{bom_id}/cancel", response_model=DocumentResponse)
def cancel_bom(bom_id: int, current_user_id: str = Depends(get_current_user_id), workflow: ApprovalWorkflow = Depends(get_workflow)) -> DocumentResponse:
    return to_response_or_404(lambda: workflow.cancel(workflow.repository.get_bom(bom_id), current_user_id))


@app.post("/api/boms/{bom_id}/revise", response_model=DocumentResponse)
def revise_bom(bom_id: int, current_user_id: str = Depends(get_current_user_id), workflow: ApprovalWorkflow = Depends(get_workflow)) -> DocumentResponse:
    return to_response_or_404(lambda: workflow.revise(workflow.repository.get_bom(bom_id), current_user_id))


@app.post("/api/boms/{bom_id}/retry-sync", response_model=DocumentResponse)
def retry_sync_bom(bom_id: int, current_user_id: str = Depends(get_current_user_id), workflow: ApprovalWorkflow = Depends(get_workflow)) -> DocumentResponse:
    return to_response_or_404(lambda: workflow.retry_accounting_sync(workflow.repository.get_bom(bom_id), current_user_id))


# ─────────────────────── TRANSFERS ───────────────────────

@app.get("/api/transfers", response_model=list[DocumentResponse])
def list_transfers(
    status: Optional[str] = Query(None),
    created_by: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    repo: DatabaseRepository = Depends(get_repo),
) -> list[DocumentResponse]:
    return [to_response(d) for d in repo.list_transfers(status=status, created_by=created_by, skip=skip, limit=limit)]


@app.post("/api/transfers", response_model=DocumentResponse)
def create_transfer(
    request: CreateTransferRequest,
    current_user_id: str = Depends(get_current_user_id),
    repo: DatabaseRepository = Depends(get_repo),
) -> DocumentResponse:
    return to_response(repo.create_transfer(
        from_warehouse=request.from_warehouse,
        to_warehouse=request.to_warehouse,
        material_id=request.material_id,
        quantity=request.quantity,
        created_by=current_user_id,
        material_status=request.material_status,
        source_site=request.source_site,
        target_site=request.target_site,
        urgent=request.urgent,
        reason=request.reason,
    ))


@app.get("/api/transfers/{transfer_id}", response_model=DocumentResponse)
def get_transfer(transfer_id: int, repo: DatabaseRepository = Depends(get_repo)) -> DocumentResponse:
    return to_response_or_404(lambda: repo.get_transfer(transfer_id))


@app.post("/api/transfers/{transfer_id}/submit", response_model=DocumentResponse)
def submit_transfer(transfer_id: int, request: ActionRequest, current_user_id: str = Depends(get_current_user_id), workflow: ApprovalWorkflow = Depends(get_workflow)) -> DocumentResponse:
    return to_response_or_404(lambda: workflow.submit(workflow.repository.get_transfer(transfer_id), current_user_id, request.comment))


@app.post("/api/transfers/{transfer_id}/approve", response_model=DocumentResponse)
def approve_transfer(
    transfer_id: int,
    request: ActionRequest,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(get_current_user_id),
    workflow: ApprovalWorkflow = Depends(get_workflow),
) -> DocumentResponse:
    doc = workflow.repository.get_transfer(transfer_id)
    result = to_response_or_404(lambda: workflow.approve(doc, current_user_id, request.comment))
    # 若簽核後狀態變成 APPROVED，將會計同步排入背景執行
    updated = workflow.repository.get_transfer(transfer_id)
    if updated.status == Status.APPROVED:
        background_tasks.add_task(do_accounting_sync, updated, workflow, current_user_id)
    return result


@app.post("/api/transfers/{transfer_id}/reject", response_model=DocumentResponse)
def reject_transfer(transfer_id: int, request: ActionRequest, current_user_id: str = Depends(get_current_user_id), workflow: ApprovalWorkflow = Depends(get_workflow)) -> DocumentResponse:
    return to_response_or_404(lambda: workflow.reject(workflow.repository.get_transfer(transfer_id), current_user_id, request.reason))


@app.post("/api/transfers/{transfer_id}/cancel", response_model=DocumentResponse)
def cancel_transfer(transfer_id: int, current_user_id: str = Depends(get_current_user_id), workflow: ApprovalWorkflow = Depends(get_workflow)) -> DocumentResponse:
    return to_response_or_404(lambda: workflow.cancel(workflow.repository.get_transfer(transfer_id), current_user_id))


@app.post("/api/transfers/{transfer_id}/revise", response_model=DocumentResponse)
def revise_transfer(transfer_id: int, current_user_id: str = Depends(get_current_user_id), workflow: ApprovalWorkflow = Depends(get_workflow)) -> DocumentResponse:
    return to_response_or_404(lambda: workflow.revise(workflow.repository.get_transfer(transfer_id), current_user_id))


@app.post("/api/transfers/{transfer_id}/retry-sync", response_model=DocumentResponse)
def retry_sync_transfer(transfer_id: int, current_user_id: str = Depends(get_current_user_id), workflow: ApprovalWorkflow = Depends(get_workflow)) -> DocumentResponse:
    return to_response_or_404(lambda: workflow.retry_accounting_sync(workflow.repository.get_transfer(transfer_id), current_user_id))


# ─────────────────────── LOGS ───────────────────────

@app.get("/api/documents/{document_id}/logs", response_model=list[LogResponse])
def get_document_logs(document_id: int, repo: DatabaseRepository = Depends(get_repo)) -> list[LogResponse]:
    logs = repo.get_logs(document_id)
    return [
        LogResponse(
            document_type=log.document_type,
            document_id=log.document_id,
            action=log.action,
            actor_id=log.actor_id,
            comment=log.comment,
            created_at=log.created_at.isoformat() if log.created_at else "",
        ) for log in logs
    ]


# ─────────────────────── DELEGATION ───────────────────────

@app.post("/api/users/me/delegation")
def set_delegation(
    request: SetDelegationRequest,
    current_user_id: str = Depends(get_current_user_id),
    repo: DatabaseRepository = Depends(get_repo),
):
    repo.set_delegation(
        delegator_id=current_user_id,
        delegate_id=request.delegate_id,
        start_at=request.start_at,
        end_at=request.end_at,
    )
    return {"message": f"代理人設定成功：{current_user_id} → {request.delegate_id}（{request.start_at} ~ {request.end_at}）"}


@app.delete("/api/users/me/delegation")
def clear_delegation(
    current_user_id: str = Depends(get_current_user_id),
    db=Depends(get_db),
):
    from .models import DelegationORM
    db.query(DelegationORM).filter_by(delegator_id=current_user_id).delete()
    db.commit()
    return {"message": "代理人設定已清除"}


# ─────────────────────── ADMIN ───────────────────────

@app.post("/api/admin/trigger-sla-check")
def trigger_sla_check(
    sla_days: int = Query(3, ge=1),
    current_user_id: str = Depends(get_current_user_id),
    workflow: ApprovalWorkflow = Depends(get_workflow),
):
    user = hr_service.get_user(current_user_id)
    if not user or user.position != "系統管理員":
        raise HTTPException(status_code=403, detail="Only system administrators can trigger SLA check")
    results = workflow.trigger_sla_check(sla_days=sla_days)
    return {"checked": len(results), "overdue": results}


@app.get("/api/accounting/events")
def accounting_events() -> list[dict]:
    return accounting_service.synced_events


# ─────────────────────── Helpers ───────────────────────

def to_response_or_404(action) -> DocumentResponse:
    try:
        return to_response(action())
    except ApprovalError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message else 400
        if "requires" in message:
            status_code = 403
        if "Concurrency" in message:
            status_code = 409
        raise HTTPException(status_code=status_code, detail=message) from exc


def to_response(document: SignoffDocument) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        document_type=document.document_type,
        material_id=getattr(document, "material_id", None),
        quantity=getattr(document, "quantity", None),
        status=document.status.value,
        version=getattr(document, "version", 1),
        created_by=document.created_by,
        approved_by=document.approved_by,
        rejection_reason=document.rejection_reason,
        site_code=getattr(document, "site_code", None),
        source_site=getattr(document, "source_site", None),
        target_site=getattr(document, "target_site", None),
        current_step=step_to_dict(document.current_step()),
        approval_steps=[step_to_dict(step) for step in document.approval_steps],
        items=[{"material_id": i.material_id, "quantity": i.quantity, "material_status": i.material_status} for i in getattr(document, "items", [])],
        created_at=document.created_at.isoformat() if document.created_at else None,
        updated_at=document.updated_at.isoformat() if document.updated_at else None,
        sync_retries=document.sync_retries,
        reason=getattr(document, "reason", None),
        attachments=getattr(document, "attachments", None),
        urgent=getattr(document, "urgent", None),
        product_id=getattr(document, "product_id", None),
        high_risk=getattr(document, "high_risk", None),
        cost_impact_high=getattr(document, "cost_impact_high", None),
    )


def step_to_dict(step: Optional[ApprovalStep]) -> Optional[dict]:
    if step is None:
        return None
    return {
        "sequence": step.sequence,
        "role": step.role,
        "site_code": step.site_code,
        "status": step.status.value,
        "approver_id": step.approver_id,
        "approved_at": step.approved_at.isoformat() if step.approved_at else None,
        "comment": step.comment,
        "delegated_from": step.delegated_from,
    }
