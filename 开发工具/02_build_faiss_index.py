"""命令行建立本地 FAISS 索引；实际逻辑位于 knowledge_index.py。"""

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from faiss_config import INDEX_DIR
from knowledge_database import add_audit_log, initialize_database, sync_document_catalog
from knowledge_index import rebuild_index


def build_index(rebuild: bool) -> int:
    if INDEX_DIR.exists() and not rebuild:
        raise RuntimeError("FAISS 索引已存在。如确认重建，请加 --rebuild 参数。")
    result = rebuild_index()
    initialize_database()
    sync_document_catalog(result.file_chunk_counts)
    add_audit_log("重建索引", f"命令行重建完成：{result.chunk_count} 个知识片段")
    return result.chunk_count


def main() -> None:
    parser = argparse.ArgumentParser(description="建立本地 LangChain + FAISS 企业知识库索引")
    parser.add_argument("--rebuild", action="store_true", help="确认删除并重建新项目的已有 FAISS 索引")
    args = parser.parse_args()

    count = build_index(rebuild=args.rebuild)
    print(f"入库完成：{count} 个知识片段")
    print(f"索引位置：{INDEX_DIR}")


if __name__ == "__main__":
    main()
