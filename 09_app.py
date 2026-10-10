"""LangChain + FAISS 新方案的本机学习页面。"""

import requests
import streamlit as st


API_URL = "http://127.0.0.1:8001"
DEMO_IDENTITIES = {
    "普通员工（仅查公开资料）": {"department": "普通员工", "role": "employee"},
    "财务员工（可查财务资料）": {"department": "财务部", "role": "employee"},
    "系统管理员（可查全部资料）": {"department": "管理层", "role": "admin"},
}


st.set_page_config(page_title="企业知识库助手", page_icon="📚", layout="wide")
st.title("📚 企业知识库助手")
st.caption("LangChain + FAISS 学习版｜本地 Ollama｜资料不会上传到云端")

with st.sidebar:
    st.subheader("学习演示身份")
    identity_name = st.selectbox("当前身份", list(DEMO_IDENTITIES))
    identity = DEMO_IDENTITIES[identity_name]
    st.info("当前为本机学习演示，身份切换不等同于正式登录。正式部署必须从登录令牌读取身份。")

    pages = ["问答首页"]
    if identity["role"] == "admin":
        pages.append("管理员后台")
    page = st.radio("功能导航", pages)

    try:
        health = requests.get(f"{API_URL}/api/health", timeout=3).json()
        if health.get("status") == "ok":
            reranker_text = "，本地 Reranker 已就绪" if health.get("reranker_ready") else "，本地 Reranker 未就绪"
            st.success(f"后端、FAISS 索引和 Ollama 均在线{reranker_text}")
        else:
            st.warning("服务未完全就绪，请检查后端、索引和 Ollama")
    except requests.RequestException:
        st.error("后端未启动：请先运行 10_api.py")

    if st.button("重新检测后端", use_container_width=True):
        st.rerun()

ADMIN_HEADERS = {"X-Demo-Role": identity["role"]}


def request_admin(method: str, path: str, **kwargs):
    """调用学习版管理员接口，正式版必须替换为服务端验证的登录令牌。"""
    return requests.request(method, f"{API_URL}{path}", headers=ADMIN_HEADERS, timeout=300, **kwargs)


def show_admin_page() -> None:
    st.subheader("管理员后台")
    st.warning("这是本机学习版管理员接口：页面仅用演示身份传递管理员标识，不能替代正式登录、JWT 和服务端鉴权。")
    try:
        summary_response = request_admin("GET", "/api/admin/summary")
        summary_response.raise_for_status()
        summary = summary_response.json()
    except requests.RequestException:
        st.error("无法读取管理数据，请确认后端已启动。")
        return

    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("资料文件", summary["document_count"])
    metric_b.metric("已入库片段", summary["chunk_count"])
    metric_c.metric("FAISS 索引", "已就绪" if summary["faiss_index_ready"] else "未建立")

    with st.expander("上传资料并自动向量化", expanded=True):
        st.caption("支持 PDF、DOCX、XLSX、TXT；每个文件最大 20 MB。同名文件会被拒绝，避免静默覆盖。")
        scope = st.selectbox("资料访问范围", ["全员", "财务部", "管理层"])
        uploads = st.file_uploader("选择企业资料", type=["pdf", "docx", "xlsx", "txt"], accept_multiple_files=True)
        if st.button("上传并建立索引", type="primary", disabled=not uploads):
            files = [("files", (item.name, item.getvalue(), item.type or "application/octet-stream")) for item in uploads]
            try:
                response = request_admin("POST", "/api/admin/documents/upload", data={"access_scope": scope}, files=files)
                response.raise_for_status()
                result = response.json()
                st.success(f"{result['message']}：{result['chunk_count']} 个知识片段")
                st.rerun()
            except requests.RequestException as error:
                detail = getattr(error.response, "text", "") if getattr(error, "response", None) else ""
                st.error(f"上传或入库失败：{detail or error}")

    left, right = st.columns([1, 2])
    with left:
        st.subheader("索引维护")
        st.caption("重建会生成新索引后再切换，构建失败时保留当前可用索引。")
        if st.button("根据现有资料重建索引"):
            try:
                response = request_admin("POST", "/api/admin/reindex")
                response.raise_for_status()
                result = response.json()
                st.success(f"{result['message']}：{result['chunk_count']} 个知识片段")
                st.rerun()
            except requests.RequestException as error:
                st.error(f"重建失败：{getattr(error.response, 'text', '') or error}")
    with right:
        st.subheader("FAISS 检索验证")
        st.caption("本地 LLM Reranker 匹配参考分为 0～100，数值越高表示该片段与问题更贴近；它是排序参考，不等于答案正确率。FAISS 距离越低越接近。")
        check_question = st.text_input("输入关键词或问题", placeholder="例如：超过50000元的付款审批")
        if st.button("仅检索，不调用模型") and check_question.strip():
            try:
                response = request_admin("GET", "/api/admin/search", params={"question": check_question.strip()})
                response.raise_for_status()
                results = response.json()
                if results:
                    st.dataframe(results, width="stretch", hide_index=True)
                else:
                    st.info("没有达到当前相关度阈值的资料。")
            except requests.RequestException as error:
                st.error(f"检索失败：{getattr(error.response, 'text', '') or error}")

    st.subheader("资料目录（SQLite 元数据）")
    try:
        documents_response = request_admin("GET", "/api/admin/documents")
        documents_response.raise_for_status()
        documents = documents_response.json()
        if documents:
            st.dataframe(documents, width="stretch", hide_index=True)
        else:
            st.info("暂无已登记资料。")
    except requests.RequestException:
        st.error("资料目录读取失败。")

    with st.expander("最近操作日志"):
        if summary["recent_logs"]:
            st.dataframe(summary["recent_logs"], width="stretch", hide_index=True)
        else:
            st.caption("暂无操作日志。")


if page == "管理员后台":
    show_admin_page()
    st.stop()

st.info("可询问公司制度、报销流程、产品资料等。系统仅依据当前身份允许访问的资料作答。")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("query_optimized"):
            st.caption(f"检索理解：{message['retrieval_query']}")
        if message.get("sources"):
            with st.expander("查看资料来源"):
                st.caption("本地 LLM Reranker 匹配参考分用于比较候选资料的相关程度，不代表回答正确率；FAISS 距离越低越接近。")
                for source in message["sources"]:
                    st.write(source)

question = st.chat_input("例如：普通员工出差住宿最多可以报销多少钱？")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("正在检索已授权资料并生成回答..."):
            try:
                response = requests.post(
                    f"{API_URL}/api/chat",
                    json={
                        "question": question,
                        "history": [
                            {"role": item["role"], "content": item["content"]}
                            for item in st.session_state.messages[:-1][-6:]
                        ],
                        **identity,
                    },
                    timeout=300,
                )
                response.raise_for_status()
                result = response.json()
                st.markdown(result["answer"])
                if result.get("query_optimized"):
                    st.caption(f"检索理解：{result['retrieval_query']}")
                if result["sources"]:
                    with st.expander("查看资料来源"):
                        st.caption("本地 LLM Reranker 匹配参考分用于比较候选资料的相关程度，不代表回答正确率；FAISS 距离越低越接近。")
                        for source in result["sources"]:
                            st.write(source)
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": result["answer"],
                        "sources": result["sources"],
                        "retrieval_query": result["retrieval_query"],
                        "query_optimized": result["query_optimized"],
                    }
                )
            except requests.RequestException as error:
                detail = ""
                if getattr(error, "response", None) is not None:
                    try:
                        detail = error.response.json().get("detail", "")
                    except ValueError:
                        detail = error.response.text
                message = detail or "后端暂时不可用，请确认 FastAPI、Ollama 和本地模型均已启动。"
                st.error(message)
                st.session_state.messages.append({"role": "assistant", "content": message})
