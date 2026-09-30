# 本机本地 LLM 部署配置手册(Strix Halo + WSL2 ROCm)

> 生成日期:2026-09-05 | 机器:Windows 11 + WSL2 Ubuntu-24.04 (user `furina-agent`)
> 目标:全本地跑 langgraph agent lab(不碰 OpenAI / 外网),GPU 吃满。

---

## 0. 最终架构一览

| 角色 | 引擎 | 模型 | 端口 | 状态 |
|---|---|---|---|---|
| Chat / 推理 | llama.cpp (HIP/GPU) | deepseek-coder:6.7b (Q4) | `127.0.0.1:11435` | ✅ 常驻 |
| Embedding | llama.cpp (HIP/GPU) | bge-m3 (Q8_0) | `127.0.0.1:11436` | ✅ 常驻 |
| (备用) Embedding/Chat | Ollama (CPU, systemd) | bge-m3 / deepseek-coder | `127.0.0.1:11434` | ⚠️ 仅 CPU |

OpenAI 兼容入口:
- Chat: `http://127.0.0.1:11435/v1/chat/completions` → langchain 用 `ChatOpenAI(base_url=..., api_key="sk-no")`
- Embedding: `http://127.0.0.1:11436/v1/embeddings` → langchain 用 `OpenAIEmbeddings(base_url=..., api_key="sk-no")`

Windows 侧 Python 通过 WSL2 localhost 转发直接访问上述地址。

---

## 1. 硬件 / 系统关键事实

- GPU:**Radeon 8060S (gfx1151, RDNA 3.5)** —— WSL2 里走 **DXG** 接口(`/dev/dxg`,无 `/dev/dri`,这是正常的)
- WSL 内可见内存 23G(宿主 48G 被 WSL2 默认截半)、24 线程、磁盘余量充足
- **有两套 ROCm 并存(重要,别混)**
  - `/opt/rocm-7.2.0` —— 有能用的 **HSA 运行库** `libhsa-runtime64.so.1.18.70200`
  - `/opt/rocm-7.2.1` —— `/opt/rocm` 符号链接指向它;hipcc / librocdxg / hip-dev / hipblas / rocblas 都在这
- `/opt/rocm -> /etc/alternatives/rocm`(Debian alternatives 机制)

---

## 2. 核心环境配方(所有 ROCm 程序启动前必带)

```bash
export PATH=/opt/rocm-7.2.1/bin:$PATH
export HSA_ENABLE_DXG_DETECTION=1            # 关键:开启 DXG 探测,否则 GPU 不可见
export LD_LIBRARY_PATH=/opt/rocm-7.2.1/lib:$HOME/.rocm-dxg:/opt/rocm-7.2.0/lib
```

验证 GPU 可见:

```bash
HSA_ENABLE_DXG_DETECTION=1 /opt/rocm-7.2.1/bin/rocminfo 2>&1 | grep -i gfx1151
# 期望:Name: gfx1151 / amdgcn-amd-amdhsa--gfx1151
```

### 符号链接(手工补的,别删)

```bash
ls ~/.rocm-dxg/            # libhsa-runtime64.so.1 -> torch venv 里的同名库
# /opt/rocm-7.2.1/lib/ 下(需 sudo 创建,指向 7.2.0):
#   libhsa-runtime64.so -> /opt/rocm-7.2.0/lib/libhsa-runtime64.so
#   libhsa-runtime64.so.1 -> .../.so.1
#   libhsa-runtime64.so.1.18.70200 -> .../.so.1.18.70200
#   libhsa-runtime64.so.1.18.70201 -> .../.so.1.18.70200   ← cmake 硬编码要这个名字
```

> 为什么 torch venv 里有 libhsa:ComfyUI/机器学习用的是 **torch ROCm 轮子自带完整运行时**(`~/ml/.venv/lib/python3.12/site-packages/torch/lib/`),不依赖系统 ROCm。

---

## 3. 模型文件位置

| 模型 | 路径 | 说明 |
|---|---|---|
| deepseek-coder:6.7b (Q4, chat) | `/usr/share/ollama/.ollama/models/blobs/sha256-59bb50d8...ecb` | 从 Ollama 借来的 GGUF,llama.cpp 直接读 |
| bge-m3 (Q8_0, embedding) | `~/ml/models/bge-m3-q8_0.gguf` | 从 hf-mirror 下载(ggml-org 官方转换) |

bge-m3 下载源(网络通):
```
https://hf-mirror.com/ggml-org/bge-m3-Q8_0-GGUF/resolve/main/bge-m3-q8_0.gguf   (≈605MB)
```

---

## 4. llama.cpp(HIP 编译版)

位置:`~/ml/llama.cpp/`,服务端二进制 `~/ml/llama.cpp/build/bin/llama-server`,HIP 后端 `libggml-hip.so.0`

### 启动 Chat 服务(GPU,端口 11435)

```bash
export PATH=/opt/rocm-7.2.1/bin:$PATH
export HSA_ENABLE_DXG_DETECTION=1
export LD_LIBRARY_PATH=/opt/rocm-7.2.1/lib:$HOME/.rocm-dxg:/opt/rocm-7.2.0/lib
cd ~/ml/llama.cpp/build/bin
nohup ./llama-server \
  -m /usr/share/ollama/.ollama/models/blobs/sha256-59bb50d8116b6a1f9bfbb940d6bb946a05554e591e30c8c2429ed6c854867ecb \
  -ngl 99 --ctx-size 4096 --host 127.0.0.1 --port 11435 --alias deepseek-coder \
  > ~/ml/llama-server.log 2>&1 &
```

### 启动 Embedding 服务(GPU,端口 11436)

```bash
cd ~/ml/llama.cpp/build/bin
nohup ./llama-server \
  -m ~/ml/models/bge-m3-q8_0.gguf \
  --embedding --host 127.0.0.1 --port 11436 \
  > ~/ml/llama-embed.log 2>&1 &
```

### 性能基线(实测)

- deepseek-coder:6.7b on GPU:生成 **~38-47 tok/s**,prompt **300-900 tok/s**
- 对比 Ollama CPU 兜底:~9 tok/s → GPU 约 4-5 倍

### 启动日志里的"成功信号"

```
Load librocdxg.so successully!   ← DXG 桥接层加载(最关键一行)
Load all DTIF APIs OK!
listening on http://127.0.0.1:11435
```

`LoadLib(libhsa-amd-aqlprofile64.so) failed` 是缺 profiling 库,无害,忽略。

---

## 5. Ollama(留作 CPU 兜底,可选)

- systemd 服务:`sudo systemctl restart ollama`;日志 `journalctl -u ollama --no-pager -n 40`
- 服务以 `User=ollama` 跑,模型存 `/usr/share/ollama/.ollama/models/`
- **Ollama 无法吃这块 GPU**:通用构建不带 ROCm 后端;WSL2 DXG 下 Vulkan 路也死了(只有软渲染 llvmpipe)。结论:GPU 推理一律走 llama.cpp。

---

## 6. 排障时间线(复盘用,别重复踩)

1. **教程 import 报错** = langchain 0.x → 1.4 大重构,`langchain.tools.retriever` → `langchain_core.tools.retriever`
2. **Ollama 100% CPU**:装的是通用版,`/usr/local/lib/ollama/` 只有 cuda_v12/13 + vulkan,**无 rocm 后端** → DXG 变量灌不进
3. **Vulkan 备胎死**:`vulkaninfo` 只有 `llvmpipe`(软渲染),WSL 无 dzn(D3D12→Vulkan)驱动
4. **rocminfo 静默失败** = 缺 `LD_LIBRARY_PATH`,加载不了 `libhsa-runtime64.so.1`(最初第 0 步打不出 gfx1151 的原因)
5. **/opt/rocm 是阉割版**:缺 `hip-dev`/`hip-lang-config.cmake` → `sudo apt-get install -y hip-dev hip-runtime-amd hipblas-dev rocblas-dev` 补全
6. **版本分裂**:hsa 运行库只在 7.2.0,7.2.1 的 cmake 却要找 `.so.1.18.70201` → 三条 sudo 软链补上(见第 2 节)
7. **Ollama 拉模型 EOF**(registry.ollama.ai 被重置)= 国内网络问题,换 hf-mirror

---

## 7. 网络镜像备忘(国内生存)

- GitHub:`git config --global url."https://gh-proxy.com/https://github.com/".insteadOf "https://github.com/"`
- HF 模型:`HF_ENDPOINT=https://hf-mirror.com`
- Ubuntu/ROCm apt 源:清华 mirrors + repo.radeon.com(7.2.1)

---

## 8. 下一步(接线 example1.py)

1. ✅ bge-m3 embed 服务已在 11436 常驻(2026-09-05 完成)
2. Windows venv 装:`pip install langchain-ollama`(若要走 Ollama)或直接用 langchain-openai 改 `base_url`
3. example1.py 改动要点:
   - `OpenAIEmbeddings(model="bge-m3", base_url="http://127.0.0.1:11436/v1", api_key="sk-no")`
   - chat model(教程后续):`ChatOpenAI(base_url="http://127.0.0.1:11435/v1", api_key="sk-no")`
   - 网络加载不了博客 → 用本地文件替代或确认代理

---

*本文件是"环境考古"换来的经验,改环境前先读一遍。*
