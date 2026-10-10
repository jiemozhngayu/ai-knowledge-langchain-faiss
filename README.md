# 企业知识库助手：LangChain + FAISS

使用本地 Ollama、LangChain、FAISS、FastAPI 和 Streamlit 的中文知识库学习项目。
支持 PDF、Word、Excel、TXT 入库、访问范围过滤、RAG 问答、资料来源展示，以及本地 LLM Reranker 重排。

本仓库是独立脱敏发布副本。企业原文、飞书同步快照与文档标识、数据库、索引、日志、备份、模型权重和本机虚拟环境均未上传。仓库自带资料全部为虚构示例。

## 本地运行

建议使用 Python 3.12 和已安装的 Ollama。先把仓库放到自己选择的目录，再在项目根目录打开 PowerShell。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull qwen3-embedding:0.6b
ollama pull qwen2.5:3b
.\.venv\Scripts\python.exe .\开发工具\00_prepare_demo.py
.\.venv\Scripts\python.exe .\开发工具\02_build_faiss_index.py
```

两个模型分别负责向量化与问答/重排；名称在 `faiss_config.py` 中设置。
Ollama 默认地址为 `http://127.0.0.1:11434`。已有索引时，只在确认需要重建后添加 `--rebuild` 参数。

双击 `start_new_solution.cmd` 启动后端与网页，或在两个终端中分别运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn 10_api:app --host 127.0.0.1 --port 8001
```

```powershell
.\.venv\Scripts\python.exe -m streamlit run 09_app.py --server.address 127.0.0.1 --server.port 8503
```

网页：[本地知识库助手](http://127.0.0.1:8503)；接口文档：[本地接口说明](http://127.0.0.1:8001/docs)。
双击启动器在后台运行服务，日志位于 `data`。启动前确保端口未被其他项目占用；需要直接观察运行过程时使用上述终端方式。

## 演示问题

```powershell
.\.venv\Scripts\python.exe .\开发工具\03_search_faiss.py "普通员工出差住宿最多可以报销多少钱？" --department 普通员工
.\.venv\Scripts\python.exe .\开发工具\04_rag_chat.py "普通员工出差住宿最多可以报销多少钱？" --department 普通员工
.\.venv\Scripts\python.exe .\开发工具\03_search_faiss.py "超过 50000 元的付款需要谁审批？" --department 财务部
```

虚构示例设定：住宿上限为每晚 500 元；财务部资料设定超过 50000 元的付款由财务负责人复核并提交总经理审批。
普通员工无权查看财务部资料。上述内容是演示预期，具体检索结果受模型和阈值影响。

## 资料与检索

`examples/knowledge` 保存仓库可分发的虚构资料；`documents` 保存本机资料，默认不参与 Git 提交。
`documents/全员` 对所有演示身份可见；其他第一层目录决定部门访问范围，例如 `财务部`、`管理层`。根目录文件默认属于全员。

检索过程为：FAISS 召回 → 权限过滤 → 本地 LLM 重排 → 基于已授权片段回答。
结果展示来源、页码、FAISS 距离和 Reranker 匹配参考分。距离越低代表向量越接近；重排分只用于排序，不代表答案正确率。
相关度阈值沿用学习阶段配置，新增资料或更换模型后需要重新校准。

网页管理员后台支持资料上传、重建索引、查看 SQLite 目录和仅检索验证。
SQLite、FAISS 索引和运行日志在本机 `data` 目录生成；它们可能包含正文或文档标识，均被忽略。
可选飞书同步入口为 `/api/internal/feishu-documents/sync`，只允许本机调用；仓库不包含飞书应用凭据。

## 学习版权限边界

网页身份选择与 `X-Demo-Role` 是演示机制，客户端传入的部门和角色不能作为正式认证。
真实部署需要服务端登录鉴权，并从已验证的会话或令牌读取身份。当前服务按本机地址启动。
只能加载自己在本机生成并信任的 FAISS 索引，避免加载来源不明的 `index.pkl`。

## 其他工具

`开发工具/01_verify_faiss.py` 可用虚构片段验证嵌入与索引。
`开发工具/build_prd_*.py` 为历史设计文档生成脚本，其中计划项与旧测试描述不代表当前功能或本次验证结果。
`开发工具/历史模型配置` 保留历史实验配置，不是默认模型设置。

本次发布的排除范围与检查结果见 `发布脱敏说明.md`。
