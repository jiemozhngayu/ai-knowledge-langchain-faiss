"""FAISS 召回、权限过滤与本地 Reranker 二次排序。"""

from dataclasses import dataclass

from langchain_community.vectorstores import FAISS

from faiss_config import INDEX_DIR, get_embeddings
from reranker import rerank


# 当前资料集的校准样本中：业务问题约 0.47~1.19，无关“食堂”问题约 1.35。
# 先使用 1.20 作为学习版阈值；正式上线前应由真实问答集重新校准。
MAX_DISTANCE = 1.20
# 若最相近资料没有访问权限，而已授权资料明显更不相关，则拒绝用公开资料凑答案。
# 数值基于当前学习资料校准；正式版需要用真实问答集复核。
UNAUTHORIZED_DISTANCE_GAP = 0.20


@dataclass(frozen=True)
class SearchResult:
    """一条可展示的检索结果；距离越低、重排匹配分越高。"""

    document: object
    faiss_distance: float
    reranker_score: float | None


def can_access(access_scope: str, department: str, role: str) -> bool:
    """管理员可访问全部资料；其他用户仅可访问全员资料和本部门资料。"""
    return role == "admin" or access_scope == "全员" or access_scope == department


def search(question: str, department: str, role: str, limit: int = 3) -> list[SearchResult]:
    """先召回并权限过滤，再对候选片段重排。

    Reranker 只会收到已授权资料；不可访问内容不会参与模型计算或展示。
    """
    if not INDEX_DIR.exists():
        raise RuntimeError("尚未建立 FAISS 索引，请先运行 02_build_faiss_index.py。")

    # 只加载本项目自己生成的本地索引。不要加载来源不明的 index.pkl 文件。
    vector_store = FAISS.load_local(
        str(INDEX_DIR),
        get_embeddings(),
        allow_dangerous_deserialization=True,
    )
    candidates = vector_store.similarity_search_with_score(question, k=max(limit * 4, 8))
    # FAISS 返回的是距离，数值越小代表语义越接近。阈值基于当前学习资料
    # 进行了初步验证；上线前应使用企业真实问题集继续校准。
    qualified_candidates = [
        (document, score)
        for document, score in candidates
        if score <= MAX_DISTANCE
    ]
    allowed_results = [
        (document, score)
        for document, score in qualified_candidates
        if can_access(document.metadata["access_scope"], department, role)
    ]
    if not allowed_results:
        return []

    best_candidate_distance = float(qualified_candidates[0][1]) if qualified_candidates else float("inf")
    best_allowed_distance = float(allowed_results[0][1])
    if (
        not can_access(
            qualified_candidates[0][0].metadata["access_scope"], department, role
        )
        and best_allowed_distance - best_candidate_distance > UNAUTHORIZED_DISTANCE_GAP
    ):
        return []
    # Reranker 对较多候选做精排后再截取，避免 FAISS 仅凭向量距离提前排除更贴题的片段。
    rerank_candidates = allowed_results[: max(limit * 3, 6)]
    try:
        reranked = rerank(question, [document for document, _ in rerank_candidates])
    except Exception as error:
        # 重排器运行异常时，保留 FAISS 的可用性，避免整个问答被单点组件阻断。
        print(f"Reranker 不可用，已降级为 FAISS 排序：{error}")
        return [
            SearchResult(document=document, faiss_distance=float(distance), reranker_score=None)
            for document, distance in rerank_candidates[:limit]
        ]

    distance_by_id = {id(document): float(distance) for document, distance in rerank_candidates}
    return [
        SearchResult(
            document=document,
            faiss_distance=distance_by_id[id(document)],
            reranker_score=score,
        )
        for document, score in reranked[:limit]
    ]
