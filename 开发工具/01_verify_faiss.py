"""验证本机 Ollama 嵌入模型与 FAISS 是否能共同工作。"""

from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings


PROJECT_DIR = Path(__file__).resolve().parent.parent
INDEX_DIR = PROJECT_DIR / "data" / "faiss_demo"
EMBEDDING_MODEL = "qwen3-embedding:0.6b"


def main() -> None:
    # 以下内容均为虚构测试资料，仅用于验证模型与索引。
    documents = [
        Document(
            page_content="普通员工因公出差，住宿费用报销标准最高为每晚 500 元，超出部分原则上由个人承担。",
            metadata={"source": "员工报销制度.pdf", "page": 1, "access_scope": "全员"},
        ),
        Document(
            page_content="采购申请应由申请人提交部门负责人审批，金额超过 5 万元时还需要总经理审批。",
            metadata={"source": "采购管理制度.pdf", "page": 2, "access_scope": "管理层"},
        ),
        Document(
            page_content="员工年假按照在公司累计工作年限计算，具体天数以员工手册规定为准。",
            metadata={"source": "员工手册.pdf", "page": 3, "access_scope": "全员"},
        ),
    ]

    # 该电脑配置了网络代理。对于 127.0.0.1 本机模型，必须绕过代理，
    # 否则 Python 客户端可能收到代理返回的 502 错误。
    embeddings = OllamaEmbeddings(
        model=EMBEDDING_MODEL,
        base_url="http://127.0.0.1:11434",
        client_kwargs={"trust_env": False},
    )
    vector_store = FAISS.from_documents(documents, embeddings)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    vector_store.save_local(str(INDEX_DIR))

    question = "普通员工出差住宿最多可以报销多少钱？"
    results = vector_store.similarity_search(question, k=2)

    print("本机嵌入模型：", EMBEDDING_MODEL)
    print("FAISS 索引位置：", INDEX_DIR)
    print("测试问题：", question)
    print("检索结果：")
    for index, item in enumerate(results, start=1):
        print(f"{index}. {item.page_content}")
        print(f"   来源：{item.metadata['source']}（第 {item.metadata['page']} 页）")


if __name__ == "__main__":
    main()
