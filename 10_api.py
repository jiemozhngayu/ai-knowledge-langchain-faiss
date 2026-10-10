"""LangChain + FAISS 新方案的本地 FastAPI 服务。"""

import re
import threading
from pathlib import Path
from typing import Literal

import requests
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from pydantic import BaseModel, Field

from faiss_config import DOCUMENTS_DIR, INDEX_DIR
from knowledge_database import (
    add_audit_log,
    get_summary,
    initialize_database,
    list_documents,
    mark_document_failed,
    sync_document_catalog,
)
from knowledge_index import SUPPORTED_SUFFIXES, rebuild_index
from rag_chat import generate_answer
from reranker import is_reranker_ready
from search_faiss import search


app = FastAPI(title="企业知识库助手 - LangChain + FAISS API", version="0.5.0")
initialize_database()

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_SCOPES = {"全员", "财务部", "管理层"}
FEISHU_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")
INDEX_UPDATE_LOCK = threading.Lock()


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    department: str = Field(default="普通员工", min_length=1, max_length=30)
    role: Literal["employee", "admin"] = "employee"
    history: list[dict[str, str]] = Field(default_factory=list, max_length=6)


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    retrieval_query: str
    query_optimized: bool


class ReindexResponse(BaseModel):
    message: str
    chunk_count: int


class FeishuDocumentSyncRequest(BaseModel):
    """由本机飞书机器人推送的已授权云文档快照。"""

    document_token: str = Field(min_length=10, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    revision_id: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=2_000_000)
    access_scope: str = Field(default="全员", min_length=1, max_length=30)


class FeishuDocumentSyncResponse(ReindexResponse):
    source: str
    revision_id: int


def require_demo_admin(x_demo_role: str | None = Header(default=None)) -> None:
    """学习版保护：仅用于页面演示，不能替代正式登录与服务端鉴权。"""
    if x_demo_role != "admin":
        raise HTTPException(status_code=403, detail="当前账号没有管理员权限")


def validate_scope(access_scope: str) -> str:
    scope = access_scope.strip()
    if scope not in ALLOWED_SCOPES or any(character in scope for character in "\\/"):
        raise HTTPException(status_code=422, detail="访问范围仅可选：全员、财务部、管理层")
    return scope


def rebuild_and_sync(action: str) -> ReindexResponse:
    try:
        with INDEX_UPDATE_LOCK:
            result = rebuild_index()
            sync_document_catalog(result.file_chunk_counts)
            add_audit_log(action, f"FAISS 索引已更新，共 {result.chunk_count} 个知识片段")
        return ReindexResponse(message="FAISS 索引已更新", chunk_count=result.chunk_count)
    except Exception as error:
        add_audit_log(f"{action}失败", str(error)[:300])
        raise HTTPException(status_code=500, detail="索引构建失败，原有索引已保留，可查看后端日志后重试") from error


def require_loopback_request(request: Request) -> None:
    """同步接口只接收本机机器人，避免在学习版中暴露文档写入入口。"""
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="飞书文档同步接口仅允许本机访问")


def feishu_document_path(document_token: str, access_scope: str) -> Path:
    """使用稳定 Token 作为文件名，文档改名或更新不会产生重复资料。"""
    return DOCUMENTS_DIR / access_scope / f"飞书文档_{document_token}.txt"


def write_text_atomically(target_path: Path, content: str) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_suffix(target_path.suffix + ".tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(target_path)


@app.get("/api/health")
def health() -> dict:
    """检查新方案的索引和本机 Ollama 服务是否可用。"""
    ollama_online = False
    try:
        response = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
        response.raise_for_status()
        ollama_online = True
    except requests.RequestException:
        pass
    return {
        "status": "ok" if INDEX_DIR.exists() and ollama_online else "degraded",
        "faiss_index_ready": INDEX_DIR.exists(),
        "ollama_online": ollama_online,
        "reranker_ready": is_reranker_ready(),
    }


@app.get("/api/admin/summary")
def admin_summary(_: None = Depends(require_demo_admin)) -> dict:
    """管理员查看本地资料目录、索引状态和最近操作日志。"""
    sync_document_catalog()
    return {"faiss_index_ready": INDEX_DIR.exists(), **get_summary()}


@app.get("/api/admin/documents")
def admin_documents(_: None = Depends(require_demo_admin)) -> list[dict]:
    """管理员查看 SQLite 中的资料元数据目录。"""
    sync_document_catalog()
    return list_documents()


@app.post("/api/admin/reindex", response_model=ReindexResponse)
def admin_reindex(_: None = Depends(require_demo_admin)) -> ReindexResponse:
    """根据 documents 文件夹重建 FAISS 索引。"""
    return rebuild_and_sync("管理员重建索引")


@app.post("/api/admin/documents/upload", response_model=ReindexResponse)
async def admin_upload_documents(
    access_scope: str = Form(...),
    files: list[UploadFile] = File(...),
    _: None = Depends(require_demo_admin),
) -> ReindexResponse:
    """上传资料后自动向量化；同名资料不会被静默覆盖。"""
    scope = validate_scope(access_scope)
    if not files:
        raise HTTPException(status_code=422, detail="请至少选择一个资料文件")

    target_dir = DOCUMENTS_DIR / scope
    target_dir.mkdir(parents=True, exist_ok=True)
    saved_sources: list[str] = []
    try:
        for uploaded_file in files:
            raw_name = uploaded_file.filename or ""
            file_name = Path(raw_name).name
            if not file_name or file_name != raw_name or not re.fullmatch(r"[^\\/:*?\"<>|]+", file_name):
                raise HTTPException(status_code=422, detail="文件名包含不允许的路径或字符")
            if Path(file_name).suffix.lower() not in SUPPORTED_SUFFIXES:
                raise HTTPException(status_code=422, detail="仅支持 PDF、DOCX、XLSX、TXT 文件")
            target_path = target_dir / file_name
            if target_path.exists():
                raise HTTPException(status_code=409, detail=f"资料已存在，未覆盖：{file_name}")

            content = await uploaded_file.read(MAX_UPLOAD_BYTES + 1)
            if not content:
                raise HTTPException(status_code=422, detail=f"文件为空：{file_name}")
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail=f"单个文件不能超过 20 MB：{file_name}")
            target_path.write_bytes(content)
            saved_sources.append(str(target_path.relative_to(DOCUMENTS_DIR)))

        response = rebuild_and_sync("管理员上传并入库")
        add_audit_log("上传资料", "、".join(saved_sources))
        return response
    except HTTPException:
        # 已保存的文件保留，管理员可修正后使用“重建索引”重试，不静默删除原始资料。
        sync_document_catalog()
        for source in saved_sources:
            mark_document_failed(source)
        raise
    except Exception as error:
        sync_document_catalog()
        for source in saved_sources:
            mark_document_failed(source)
        raise HTTPException(status_code=500, detail="文件已保留，但自动入库失败，可在管理后台重建索引重试") from error


@app.post(
    "/api/internal/feishu-documents/sync",
    response_model=FeishuDocumentSyncResponse,
)
def sync_feishu_document(
    payload: FeishuDocumentSyncRequest,
    _: None = Depends(require_loopback_request),
) -> FeishuDocumentSyncResponse:
    """将机器人已读取的飞书 docx/Wiki 正文写入本地 FAISS 资料目录。"""
    document_token = payload.document_token.strip()
    if not FEISHU_TOKEN_PATTERN.fullmatch(document_token):
        raise HTTPException(status_code=422, detail="飞书文档 Token 格式无效")
    title = " ".join(payload.title.split())
    if not title:
        raise HTTPException(status_code=422, detail="飞书文档标题不能为空")
    scope = validate_scope(payload.access_scope)
    source_path = feishu_document_path(document_token, scope)
    source = str(source_path.relative_to(DOCUMENTS_DIR))
    document_text = "\n".join(
        [
            f"飞书文档标题：{title}",
            f"飞书文档 Token：{document_token}",
            f"飞书文档版本：{payload.revision_id}",
            "",
            payload.content.strip(),
            "",
        ]
    )
    try:
        write_text_atomically(source_path, document_text)
    except OSError as error:
        raise HTTPException(status_code=500, detail="飞书文档本地保存失败") from error

    result = rebuild_and_sync("飞书文档同步入库")
    add_audit_log("飞书文档同步", f"{source}｜版本 {payload.revision_id}")
    return FeishuDocumentSyncResponse(
        message=result.message,
        chunk_count=result.chunk_count,
        source=source,
        revision_id=payload.revision_id,
    )


@app.get("/api/admin/search")
def admin_search(question: str, _: None = Depends(require_demo_admin)) -> list[dict]:
    """管理员直接测试 FAISS 检索，不调用问答模型。"""
    if not question.strip():
        raise HTTPException(status_code=422, detail="请输入检索关键词或问题")
    if not INDEX_DIR.exists():
        raise HTTPException(status_code=503, detail="FAISS 索引未建立")
    results = search(question.strip(), department="管理层", role="admin", limit=5)
    return [
        {
            "rank": number,
            "source": result.document.metadata.get(
                "display_source", result.document.metadata["source"]
            ),
            "page": result.document.metadata["page"],
            "access_scope": result.document.metadata["access_scope"],
            "reranker_match_reference": (
                round(result.reranker_score * 100, 1)
                if result.reranker_score is not None
                else None
            ),
            "faiss_distance": round(result.faiss_distance, 4),
            "preview": result.document.page_content[:220],
        }
        for number, result in enumerate(results, start=1)
    ]


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """开发演示接口：部门和角色由调用方传入；正式版必须替换为登录态中的身份。"""
    if not INDEX_DIR.exists():
        raise HTTPException(status_code=503, detail="FAISS 索引未建立，请先执行 02_build_faiss_index.py")
    try:
        answer, sources, retrieval_query, query_optimized = generate_answer(
            request.question,
            request.department,
            request.role,
            request.history,
        )
    except requests.RequestException as error:
        raise HTTPException(status_code=503, detail="本机 Ollama 问答服务暂不可用") from error
    except Exception as error:
        # 学习版将本地模型或索引错误转为明确的服务不可用提示，避免页面只看到模糊的 500。
        raise HTTPException(
            status_code=503,
            detail=f"本地检索或模型服务不可用：{str(error)[:180]}",
        ) from error
    return ChatResponse(
        answer=answer,
        sources=sources,
        retrieval_query=retrieval_query,
        query_optimized=query_optimized,
    )
