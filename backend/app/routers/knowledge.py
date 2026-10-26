from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from ..deps import Ctx, get_ctx, require_manager
from ..models import KnowledgeDocument
from ..services import audit

router = APIRouter(prefix="/knowledge")


class DocIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=50000)
    is_approved: bool = False


class DocPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = Field(default=None, min_length=1, max_length=50000)
    is_approved: bool | None = None


def doc_out(d: KnowledgeDocument) -> dict:
    return {
        "id": d.id,
        "organization_id": d.organization_id,
        "title": d.title,
        "content": d.content,
        "is_approved": d.is_approved,
        "approved_by": d.approved_by,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }


@router.get("")
def list_docs(ctx: Ctx = Depends(get_ctx), approved_only: bool = False):
    q = select(KnowledgeDocument).where(KnowledgeDocument.organization_id == ctx.org_id)
    if approved_only:
        q = q.where(KnowledgeDocument.is_approved.is_(True))
    docs = ctx.db.scalars(q.order_by(KnowledgeDocument.updated_at.desc())).all()
    return [doc_out(d) for d in docs]


@router.post("", status_code=201)
def create_doc(body: DocIn, ctx: Ctx = Depends(require_manager)):
    doc = KnowledgeDocument(
        organization_id=ctx.org_id,
        title=body.title,
        content=body.content,
        is_approved=body.is_approved,
        approved_by=ctx.user.id if body.is_approved else None,
    )
    ctx.db.add(doc)
    audit(ctx.db, ctx.org_id, ctx.user.id, "knowledge.created", "knowledge_document", doc.id)
    ctx.db.commit()
    return doc_out(doc)


@router.patch("/{doc_id}")
def update_doc(doc_id: str, body: DocPatch, ctx: Ctx = Depends(require_manager)):
    doc = ctx.db.scalar(select(KnowledgeDocument).where(
        KnowledgeDocument.id == doc_id,
        KnowledgeDocument.organization_id == ctx.org_id
    ))
    if not doc:
        raise HTTPException(404, "Knowledge document not found")

    if body.title is not None:
        doc.title = body.title
    if body.content is not None:
        doc.content = body.content
    if body.is_approved is not None:
        doc.is_approved = body.is_approved
        doc.approved_by = ctx.user.id if body.is_approved else None

    audit(ctx.db, ctx.org_id, ctx.user.id, "knowledge.updated", "knowledge_document", doc.id)
    ctx.db.commit()
    return doc_out(doc)


@router.delete("/{doc_id}", status_code=204)
def delete_doc(doc_id: str, ctx: Ctx = Depends(require_manager)):
    doc = ctx.db.scalar(select(KnowledgeDocument).where(
        KnowledgeDocument.id == doc_id,
        KnowledgeDocument.organization_id == ctx.org_id
    ))
    if not doc:
        raise HTTPException(404, "Knowledge document not found")

    ctx.db.delete(doc)
    audit(ctx.db, ctx.org_id, ctx.user.id, "knowledge.deleted", "knowledge_document", doc_id)
    ctx.db.commit()
