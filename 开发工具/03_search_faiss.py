"""命令行检索入口；实际权限与检索逻辑使用项目根目录的 search_faiss.py。"""

import argparse
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from search_faiss import search  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="检索本地 FAISS 企业知识库")
    parser.add_argument("question", help="要查询的问题")
    parser.add_argument("--department", default="普通员工", help="当前用户所属部门")
    parser.add_argument("--role", choices=["employee", "admin"], default="employee", help="当前用户角色")
    args = parser.parse_args()

    results = search(args.question, args.department, args.role)
    if not results:
        print("没有找到当前账号可访问的相关资料。")
        return

    for number, result in enumerate(results, start=1):
        document = result.document
        meta = document.metadata
        print(f"{number}. {document.page_content}")
        print(f"   来源：{meta['source']}（第 {meta['page']} 页，范围：{meta['access_scope']}，FAISS 距离：{result.faiss_distance:.4f}）")
        if result.reranker_score is not None:
            print(f"   Reranker 匹配参考分：{result.reranker_score * 100:.1f}（不代表答案正确率）")


if __name__ == "__main__":
    main()
