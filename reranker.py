"""本地 LLM Reranker：对 FAISS 候选片段打分并二次排序。"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import requests

from faiss_config import RERANKER_MODEL

if TYPE_CHECKING:
    from langchain_core.documents import Document


OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
OLLAMA_CHAT_URL = "http://127.0.0.1:11434/v1/chat/completions"


def is_reranker_ready() -> bool:
    """检查本机 Ollama 是否已安装重排所需模型，不触发模型加载。"""
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=3)
        response.raise_for_status()
        names = {item.get("name") for item in response.json().get("models", [])}
        return RERANKER_MODEL in names
    except requests.RequestException:
        return False


def _parse_scores(content: str, expected_count: int) -> list[float]:
    """从模型回答中提取与候选数量一一对应的 0~100 分数。"""
    matched = re.search(r"\[[\s\d.,-]+\]", content)
    if not matched:
        raise ValueError("Reranker 未返回 JSON 分数数组")
    values = json.loads(matched.group(0))
    if not isinstance(values, list) or len(values) != expected_count:
        raise ValueError("Reranker 返回分数数量与候选数量不一致")
    return [max(0.0, min(float(value), 100.0)) / 100.0 for value in values]


def rerank(question: str, documents: list["Document"]) -> list[tuple["Document", float]]:
    """仅将已授权候选片段交给本地模型，返回按匹配分从高到低的列表。

    分数是模型给出的排序参考分，不是答案正确率或置信度承诺。
    """
    if not documents:
        return []
    candidates = "\n\n".join(
        f"[{number}] {document.page_content[:900]}"
        for number, document in enumerate(documents, start=1)
    )
    prompt = f"""你是企业知识库检索的重排器，只负责判断资料片段与问题的匹配程度。
请为下列 {len(documents)} 个片段依次给出 0 到 100 的相关性分数：100 表示直接回答问题，0 表示无关。
如果问题问的是金额、期限、审批人等具体信息，直接包含该信息的片段必须优先得高分；不要因为片段较短、没有标题或不是完整制度而降低分数。
只有宽泛地提到主题、却不能直接回答问题的片段，应显著低于直接命中片段。
严格只输出一个 JSON 数组，数组长度必须为 {len(documents)}，例如：[96, 18, 4]。
不得回答问题、不得解释、不得添加 Markdown；不要因片段文字长而给高分。

问题：{question}

候选片段：
{candidates}
"""
    response = requests.post(
        OLLAMA_CHAT_URL,
        json={
            "model": RERANKER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": 80,
            "temperature": 0.0,
        },
        timeout=180,
    )
    response.raise_for_status()
    scores = _parse_scores(response.json()["choices"][0]["message"]["content"], len(documents))
    scored = list(zip(documents, scores, strict=True))
    return [(document, score) for document, score in sorted(scored, key=lambda item: item[1], reverse=True)]
