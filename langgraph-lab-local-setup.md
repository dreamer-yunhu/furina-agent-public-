# langgraph-lab 本地化接线配置(Windows 侧)

> 生成日期:2026-09-05 | 关联项目:`C:\PythonProject\langgraph-lab\`
> 配套文档:本机 GPU/LLM 部署手册见 `/home/furina-agent/local-gpu-llm-setup.md`(WSL)
> 目的:跑通参照 langgraph 官方示例写的 agent,全本地(不碰 OpenAI / 外网)。

---

## 1. 项目与 venv

- 项目根:`C:\PythonProject\langgraph-lab\`(`example1.py`、`lab1.py`)
- venv:**`.venv`**(Windows 原生 Python 3.12.9,不是 WSL)
- 执行用绝对路径:
  ```
  C:\PythonProject\langgraph-lab\.venv\Scripts\python.exe
  ```
  装包示例:
  ```
  C:\PythonProject\langgraph-lab\.venv\Scripts\python.exe -m pip install <包名>
  ```

## 2. 版本现状(2026-09-05 实测)

| 包 | 版本 | 备注 |
|---|---|---|
| langchain | 1.4.0 | 1.0 大重构版,教程按 0.x 写,是报错根源 |
| langchain-core | 1.6.2 | 大量符号从 langchain 搬到这里 |
| langchain-community | 0.4.2 | 已 sunset(仅警告,能用) |
| langchain-openai | 1.6.0 | 保留,改 base_url 指向本地即可 |
| langchain-text-splitters | 1.1.2 | OK |
| langgraph | 1.2.11 | OK |
| (未装) langchain-ollama | — | **不需要装**,本地服务是 OpenAI 兼容的,直接用 langchain-openai |

### 踩过的坑:import 路径搬家

`example1.py:34` 原教程写法在 langchain 1.4.0 里不存在(编辑器报 "找不到引用 retriever" 是真报错,不是误报):

```python
# ❌ 0.x 写法(已失效)
from langchain.tools.retriever import create_retriever_tool
# ✅ 1.x 写法(已验证可导入,签名兼容)
from langchain_core.tools.retriever import create_retriever_tool
```

---

## 3. 本机 GPU 服务(从 Windows Python 直接可访问)

WSL2 默认开启 **localhost 转发**,所以 Windows 侧直接访问 `127.0.0.1` 即可,无需配 IP。

| 服务 | 地址 | 模型 | 状态 |
|---|---|---|---|
| Chat (llama.cpp GPU) | `http://127.0.0.1:11435/v1` | deepseek-coder:6.7b | ✅ 常驻 |
| Embedding (llama.cpp GPU) | `http://127.0.0.1:11436/v1` | bge-m3 | 🚧 |
| Ollama (CPU 兜底,可选) | `http://127.0.0.1:11434` | — | ⚠️ |

均 OpenAI 兼容 → **langchain 里 `api_key` 随便填一个如 `"sk-no"`**,改 `base_url` 即可。

---

## 4. 接线计划(example1.py 改动要点)

### 4.1 Embedding(第 30 行附近)

```python
vectorstore = InMemoryVectorStore.from_documents(
    documents=doc_splits,
    embedding=OpenAIEmbeddings(
        model="bge-m3",
        base_url="http://127.0.0.1:11436/v1",
        api_key="sk-no",
    ),
)
```

> 提示:先起 embed 服务、curl 测 `/v1/embeddings` 通,再跑建库。

### 4.2 Chat model(教程后续 graph 部分会用到)

```python
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(
    model="deepseek-coder",
    base_url="http://127.0.0.1:11435/v1",
    api_key="sk-no",
)
```

### 4.3 数据源(WebBaseLoader 抓 Lilian Weng 博客,外网不稳)

- 有代理:给进程设 `HTTP_PROXY`/`HTTPS_PROXY`
- 想专心学 langgraph(推荐):把网页抓取换成**本地文本文件**,用 `TextLoader`/`DirectoryLoader` 读——内容不重要,学的是链路

---

## 5. 运行顺序备忘

1. (WSL)确认 llama-server chat 在 11435:`curl http://127.0.0.1:11435/v1/models`
2. (WSL)确认 embed 服务在 11436(见 WSL 部署手册第 4 节)
3. (Windows)改完 example1.py → 运行 `.venv\Scripts\python.exe example1.py`
4. 遇到报错先看:是不是又是 langchain 1.x 的"符号搬家"?→ 去 `.venv\Lib\site-packages\` 里 grep 定义文件确认新位置

---

## 6. 学习复盘(为什么这么搭)

- **版本对齐 > 逐个修 import**:官方示例是某一历史版本写的,文档首页永远显示最新 → 要么锁版本,要么接受 langchain_core 前缀这类迁移规则
- **本地模型两条腿**:GPU 推理走 llama.cpp(WSL,HIP),embedding 走 llama.cpp embed;Ollama 在 WSL2 DXG 下吃不到这块 GPU
- **OpenAI 兼容是万能接口**:本地起的服务都用这个协议,langchain/任何 OpenAI 客户端零适配

---

*改环境/换机器前先读 WSL 那本部署手册 + 本文。*
