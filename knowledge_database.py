"""知识库文件元数据与操作日志。

SQLite 只保存文件清单、访问范围和操作记录；语义向量仍由 FAISS 检索。
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from faiss_config import DATA_DIR, DOCUMENTS_DIR
from knowledge_index import SUPPORTED_SUFFIXES, get_access_scope


DATABASE_PATH = DATA_DIR / "knowledge.db"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    """创建学习版所需的数据表，不保存用户密码或密钥。"""
    with _connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                access_scope TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                indexed_chunks INTEGER NOT NULL DEFAULT 0,
                index_status TEXT NOT NULL DEFAULT '待入库',
                uploaded_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def add_audit_log(action: str, detail: str) -> None:
    with _connection() as connection:
        connection.execute(
            "INSERT INTO audit_logs (action, detail, created_at) VALUES (?, ?, ?)",
            (action, detail, _now()),
        )


def _sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sync_document_catalog(chunk_counts: dict[str, int] | None = None) -> None:
    """把 documents 目录同步到 SQLite 文件目录表。

    只同步元数据；不会复制、移动或删除用户原始资料。
    """
    index_was_built = chunk_counts is not None
    chunk_counts = chunk_counts or {}
    found_sources: set[str] = set()
    with _connection() as connection:
        for file_path in DOCUMENTS_DIR.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            source = str(file_path.relative_to(DOCUMENTS_DIR))
            found_sources.add(source)
            chunks = chunk_counts.get(source, 0)
            status = "已入库" if chunks else "待入库"
            timestamp = _now()
            connection.execute(
                """
                INSERT INTO documents (
                    source, file_name, access_scope, file_size, sha256,
                    indexed_chunks, index_status, uploaded_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    file_name=excluded.file_name,
                    access_scope=excluded.access_scope,
                    file_size=excluded.file_size,
                    sha256=excluded.sha256,
                    updated_at=excluded.updated_at
                """,
                (
                    source,
                    file_path.name,
                    get_access_scope(file_path),
                    file_path.stat().st_size,
                    _sha256(file_path),
                    chunks,
                    status,
                    timestamp,
                    timestamp,
                ),
            )
            if index_was_built:
                connection.execute(
                    "UPDATE documents SET indexed_chunks=?, index_status=?, updated_at=? WHERE source=?",
                    (chunks, status, timestamp, source),
                )

        rows = connection.execute("SELECT source FROM documents").fetchall()
        for row in rows:
            if row["source"] not in found_sources:
                connection.execute(
                    "UPDATE documents SET index_status=?, updated_at=? WHERE source=?",
                    ("文件不存在", _now(), row["source"]),
                )


def mark_document_failed(source: str) -> None:
    with _connection() as connection:
        connection.execute(
            "UPDATE documents SET index_status=?, updated_at=? WHERE source=?",
            ("入库失败，等待重试", _now(), source),
        )


def list_documents() -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT source, file_name, access_scope, file_size, indexed_chunks,
                   index_status, uploaded_at, updated_at
            FROM documents
            ORDER BY updated_at DESC, source ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_summary() -> dict:
    with _connection() as connection:
        document_count = connection.execute(
            "SELECT COUNT(*) FROM documents WHERE index_status != '文件不存在'"
        ).fetchone()[0]
        chunk_count = connection.execute(
            "SELECT COALESCE(SUM(indexed_chunks), 0) FROM documents WHERE index_status = '已入库'"
        ).fetchone()[0]
        recent_logs = connection.execute(
            "SELECT action, detail, created_at FROM audit_logs ORDER BY id DESC LIMIT 8"
        ).fetchall()
    return {
        "document_count": document_count,
        "chunk_count": chunk_count,
        "recent_logs": [dict(row) for row in recent_logs],
    }
