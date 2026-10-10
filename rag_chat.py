"""本地 RAG 问答核心：先理解对话省略，再只向模型传递已授权资料。"""

import re

import requests

from faiss_config import ANSWER_MODEL
from search_faiss import search


NO_ACCESSIBLE_RESULT = "知识库中没有找到当前账号可访问的相关规定。"
OLLAMA_CHAT_URL = "http://127.0.0.1:11434/v1/chat/completions"


def numeric_terms(text: str) -> set[str]:
    """提取阿拉伯数字金额，避免模型把“2 万”错当成“5 万”的依据。"""
    normalized = text.replace(",", "").replace("，", "")
    terms = {str(int(value)) for value in re.findall(r"\d+", normalized)}
    for value in re.findall(r"(\d+(?:\.\d+)?)\s*万", normalized):
        terms.add(str(int(float(value) * 10_000)))
    return terms


def has_required_numeric_terms(question: str, documents: list[object]) -> bool:
    """问题指定金额时，至少一个已授权资料必须包含同一金额。"""
    required_terms = numeric_terms(question)
    if not required_terms:
        return True
    available_terms = numeric_terms(
        "\n".join(str(document.page_content) for document in documents)
    )
    return required_terms.issubset(available_terms)


def call_local_model(prompt: str, *, max_tokens: int, temperature: float) -> str:
    """调用本机模型；不携带企业资料以外的外部数据。"""
    response = requests.post(
        OLLAMA_CHAT_URL,
        json={
            "model": ANSWER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.8,
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def optimize_retrieval_query(question: str, history: list[dict[str, str]] | None) -> tuple[str, bool]:
    """把依赖上下文的短问题补全为独立检索问题。

    只参考之前的用户提问，不把模型上一次回答当作事实来源；改写失败时退回原问题。
    """
    previous_questions = [
        item["content"].strip()
        for item in (history or [])[-6:]
        if item.get("role") == "user" and item.get("content", "").strip()
    ]
    # 无历史时，完整问题直接检索；但“出差”“报销”等短关键词仍值得改写为
    # 通用制度检索问题，避免因为上下文缺失直接拒答。
    if not previous_questions and len(question.strip()) > 4:
        return question, False

    short_question_example = ""
    if not previous_questions:
        short_question_example = (
            f"\n当前问题只有一个主题词时，必须补成带有检索意图的完整问题。"
            f"例如：当前问题为“出差”时，应输出“公司员工出差相关制度、流程和报销标准是什么？”。"
            f"请保留当前主题词“{question.strip()}”，但不要编造具体金额或结论。"
        )

    prompt = f"""你是企业知识库的检索查询改写器。
任务：判断“当前问题”是否依赖前文。如果依赖前文、过短或存在省略，请结合“此前用户问题”补全为一条可独立检索的中文问题；如果没有此前问题且当前问题过短，请扩展为不包含具体结论的通用企业制度检索问题；如果已经完整，原样输出。
{short_question_example}

严格规则：
1. 只输出一条检索问题，不要解释、不要回答、不要加“改写后”。
2. 只能补全前文明确出现的主题，不得虚构制度、金额、部门或结论。
3. 当前问题优先；不要根据助手历史回答补充事实。

此前用户问题：
{chr(10).join(f'- {item}' for item in previous_questions) or '无'}

当前问题：{question}
"""
    try:
        rewritten = call_local_model(prompt, max_tokens=64, temperature=0.0)
    except requests.RequestException:
        return question, False

    rewritten = rewritten.splitlines()[0].strip().strip('“”"')
    for prefix in ("检索问题：", "改写问题：", "改写后："):
        if rewritten.startswith(prefix):
            rewritten = rewritten.removeprefix(prefix).strip()
    if not rewritten or len(rewritten) > 180:
        return question, False
    # 防止模型仅复述“出差相关企业制度查询”这类过于笼统的短句。
    # 此处不写入任何答案，只补充通用检索意图，仍由 FAISS 和资料决定最终结论。
    if not previous_questions and len(question.strip()) <= 4 and len(rewritten) <= 12:
        rewritten = f"公司员工{question.strip()}相关制度、流程和标准是什么？"
    return rewritten, rewritten != question


def generate_answer(
    question: str,
    department: str,
    role: str,
    history: list[dict[str, str]] | None = None,
) -> tuple[str, list[str], str, bool]:
    retrieval_query, query_optimized = optimize_retrieval_query(question, history)
    results = search(retrieval_query, department=department, role=role, limit=2)
    if not results:
        return NO_ACCESSIBLE_RESULT, [], retrieval_query, query_optimized
    if not has_required_numeric_terms(
        question, [result.document for result in results]
    ):
        return NO_ACCESSIBLE_RESULT, [], retrieval_query, query_optimized

    context_parts = []
    sources = []
    for number, result in enumerate(results, start=1):
        document = result.document
        metadata = document.metadata
        context_parts.append(f"[资料 {number}]\n{document.page_content}")
        source_name = metadata.get("display_source", metadata["source"])
        source = f"{source_name}（第 {metadata['page']} 页）"
        if result.reranker_score is not None:
            source += f"｜Reranker 匹配参考分：{result.reranker_score * 100:.1f}｜FAISS 距离：{result.faiss_distance:.3f}"
        else:
            source += f"｜FAISS 距离：{result.faiss_distance:.3f}（Reranker 未启用）"
        if source not in sources:
            sources.append(source)

    prompt = f"""你是企业内部知识库助手。已检索到与问题相关且当前账号可访问的资料。
只依据下方资料回答，不要编造。
输出格式：先写一行“结论：…”，再列出不超过 4 条资料中明确出现的事实。
严禁输出“说明补充”、原因、价值、背景、建议或资料中没有明确写出的内容；只回答用户原问题直接需要的信息。
不得输出“{NO_ACCESSIBLE_RESULT}”。

用户原问题：{question}
用于检索的问题：{retrieval_query}

已授权资料：
{'\n\n'.join(context_parts)}
"""
    answer = call_local_model(prompt, max_tokens=256, temperature=0.2)
    answer = answer.replace(NO_ACCESSIBLE_RESULT, "").strip()
    return answer, sources, retrieval_query, query_optimized
