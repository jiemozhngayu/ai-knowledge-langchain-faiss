"""命令行问答入口；实际 RAG 逻辑在 rag_chat.py，便于后端复用。"""

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from rag_chat import generate_answer


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 LangChain + FAISS RAG 问答")
    parser.add_argument("question", help="要提问的内容")
    parser.add_argument("--department", default="普通员工", help="当前用户所属部门")
    parser.add_argument("--role", choices=["employee", "admin"], default="employee", help="当前用户角色")
    args = parser.parse_args()

    answer, sources, retrieval_query, query_optimized = generate_answer(
        args.question, args.department, args.role
    )
    if query_optimized:
        print("检索理解：", retrieval_query)
    print("回答：", answer)
    if sources:
        print("来源：", "；".join(sources))


if __name__ == "__main__":
    main()
