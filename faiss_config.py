"""新方案的本地 FAISS 与 Ollama 统一配置。"""

from pathlib import Path

from langchain_ollama import OllamaEmbeddings


PROJECT_DIR = Path(__file__).resolve().parent
DOCUMENTS_DIR = PROJECT_DIR / "documents"
DATA_DIR = PROJECT_DIR / "data"
INDEX_DIR = DATA_DIR / "faiss_index"
EMBEDDING_MODEL = "qwen3-embedding:0.6b"
# 当前本机的 qwen3:4b 会强制输出很长的思考过程；学习版默认使用
# 已验证可直接给出简洁答案的 qwen2.5:3b。qwen3:4b 保留为后续升级选项。
ANSWER_MODEL = "qwen2.5:3b"
# Reranker 使用当前已部署的本地模型，不额外传输企业资料到云端。
RERANKER_MODEL = "qwen2.5:3b"


def get_embeddings() -> OllamaEmbeddings:
    """返回本机嵌入模型客户端。

    trust_env=False 用于避免系统代理接管 127.0.0.1 的 Ollama 请求。
    """
    return OllamaEmbeddings(
        model=EMBEDDING_MODEL,
        base_url="http://127.0.0.1:11434",
        client_kwargs={"trust_env": False},
    )
