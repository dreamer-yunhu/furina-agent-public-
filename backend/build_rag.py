"""构建芙宁娜语音台词 RAG 知识库 —— 按 ## 标题分割版本"""
import chromadb
from pathlib import Path

# ===== 配置路径 =====
DB_PATH = Path(__file__).parent.parent / "chroma_db"
VOICE_FILE = Path(__file__).parent / "knowledge" / "furina_dialogue.txt"

# ===== 连接 ChromaDB =====
chroma_client = chromadb.PersistentClient(path=str(DB_PATH))

# 如果旧集合数据错误，先删除再重建
try:
    chroma_client.delete_collection("furina_voice")
    print("已删除旧的 furina_voice 集合")
except Exception:
    pass

collection = chroma_client.get_or_create_collection("furina_voice")

# ===== 读取文本 =====
text = VOICE_FILE.read_text(encoding="utf-8")

# ===== 核心分割：只依赖 ## 标题，不依赖空行 =====
# 按 "##" 切分，第一个片段前的空内容会被 strip 掉
parts = text.split("##")
chunks = []

for part in parts:
    part = part.strip()
    if not part:
        continue
    # 把 ## 补回去，因为 split 会吃掉它
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
# 该代码块作用：按 ## 标题分割语音台词文本，不依赖空行格式，将每个场景片段存入 ChromaDB