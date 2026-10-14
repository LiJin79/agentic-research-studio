import uuid
from dataclasses import asdict

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.api.dependencies import DocumentServiceDependency
from app.core.config import get_settings
from app.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    RetrievalHit,
    RetrievalTestRequest,
)

router = APIRouter()


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    service: DocumentServiceDependency,
    file: UploadFile = File(description="支持 txt、md、csv、json、pdf、docx"),
    owner_id: uuid.UUID | None = Form(default=None),
) -> DocumentUploadResponse:
    """接收文件并同步完成解析、切分、向量化和索引。"""
    content = await file.read(get_settings().max_upload_bytes + 1)
    try:
        document, deduplicated = await service.upload(
            filename=file.filename or "unnamed.txt",
            content_type=file.content_type,
            content=content,
            owner_id=owner_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DocumentUploadResponse(
        document=DocumentResponse.model_validate(document),
        deduplicated=deduplicated,
    )


@router.post("/{document_id}/reindex", response_model=DocumentResponse, status_code=202)
async def reindex_document(document_id: uuid.UUID, service: DocumentServiceDependency):
    """将原文件重新排队，供失败重试或模型版本切换使用。"""
    try:
        return DocumentResponse.model_validate(await service.reindex(document_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{document_id}/download")
async def download_document(document_id: uuid.UUID, service: DocumentServiceDependency):
    """在受控目录内下载原文，引用可以追溯到真正的原文件。"""
    document = await service.get_document(document_id)
    try:
        path = service.original_path(document)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=document.filename)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    service: DocumentServiceDependency,
    owner_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> DocumentListResponse:
    """分页列出知识库文档。"""
    documents, total = await service.list_documents(
        owner_id=owner_id,
        limit=limit,
        offset=offset,
    )
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(item) for item in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/search/test", response_model=list[RetrievalHit])
async def test_retrieval(
    payload: RetrievalTestRequest,
    service: DocumentServiceDependency,
) -> list[RetrievalHit]:
    """直接观察 Qdrant 检索结果，便于学习和调参。"""
    hits = await service.search(payload.query, limit=payload.limit)
    return [RetrievalHit(**asdict(hit)) for hit in hits]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    service: DocumentServiceDependency,
) -> DocumentResponse:
    """读取单个文档及其索引元数据。"""
    return DocumentResponse.model_validate(await service.get_document(document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    service: DocumentServiceDependency,
) -> Response:
    """删除文档、原文件和对应的 Qdrant 向量。"""
    await service.delete_document(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
