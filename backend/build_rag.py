"""构建芙宁娜语音台词 RAG 知识库 —— 按 ## 标题分割版本"""
import os
import chromadb
from pathlib import Path

# 必须在导入 embedding_functions 之前设置
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from chromadb.utils import embedding_functions

# ===== 配置路径 =====
DB_PATH = Path(__file__).parent.parent / "chroma_db"
VOICE_FILE = Path(__file__).parent / "knowledge" / "furina_dialogue.txt"

# ===== 连接 ChromaDB =====
chroma_client = chromadb.PersistentClient(path=str(DB_PATH))

# ===== 彻底删除旧集合（绕过 embedding 锁定） =====
try:
    chroma_client.delete_collection("furina_voice")
    print("已删除旧的 furina_voice 集合")
except Exception as e:
    print(f"删除旧集合时忽略: {e}")

# ===== 创建中文嵌入函数 =====
embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="D:\\models\\bge-small-zh-v1.5"
)


# ===== 创建新集合（必须一次性同时指定 name 和 embedding_function） =====
collection = chroma_client.create_collection(
    name="furina_voice",
    embedding_function=embedding_func
)
print("已创建新的 furina_voice 集合（中文嵌入）")

# ===== 读取文本 =====
text = VOICE_FILE.read_text(encoding="utf-8")

# ===== 核心分割：只依赖 ## 标题，不依赖空行 =====
parts = text.split("##")
chunks = []

for part in parts:
    part = part.strip()
    if not part:
        continue
    chunk = "##" + part
    chunks.append(chunk)

print(f"共分割出 {len(chunks)} 个语音片段")

# 打印前 3 个片段的前 50 个字符，确认效果
for i, chunk in enumerate(chunks[:3]):
    preview = chunk[:50].replace("\n", "\\n")
    print(f"  片段{i}: {preview}...")

# ===== 存入向量库 =====
collection.upsert(
    documents=chunks,
    ids=[f"voice_{i}" for i in range(len(chunks))]
)

print("✅ 芙宁娜语音台词知识库构建完成！")
# 该代码块作用：彻底删除旧集合后，用中文嵌入模型重建，避免 embedding 函数冲突