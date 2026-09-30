# 2026-09-05 会话总结:把 langgraph lab 推到全本地 GPU

> 类型:复盘笔记 | 关联文档:`../local-gpu-llm-setup.md`(部署手册)、`../langgraph-lab-local-setup.md`(接线手册)

---

## 一、起点(一个编辑器报错)

`example1.py` 报"在 `langchain.tools` 中找不到引用 `retriever`"。最初以为是误报/环境问题,查下去才发现是**版本断层**:

- 教程按 langchain 0.x 写,实际装了 **langchain 1.4.0**
- `langchain.tools.retriever` → `langchain_core.tools.retriever`(1.0 把工具基座全部下沉到 core)
- 修法一行:改 `langchain_core.tools.retriever`

**教训:报错是真的,编辑器比你想的更诚实。先查版本,再怀疑环境。**

## 二、从"要本地模型"到"GPU 吃满"——踩坑地图

用户决策:不用 OpenAI、要走本地,还坚持要 GPU。于是按坑的顺序一个个趟:

| # | 尝试 | 结果 | 根因 |
|---|---|---|---|
| 1 | Ollama 装 deepseek-coder:6.7b | ✅ 能跑但 **100% CPU** | 官方通用构建只带 cuda+vulkan,**无 ROCm 后端**;WSL2 DXG 下不认 |
| 2 | Ollama + 注入 DXG 环境变量 | ❌ | 没有 rocm 后端,灌多少都没用 |
| 3 | Ollama Vulkan 后端 | ❌ | `vulkaninfo` 只有 `llvmpipe`(软渲染),WSL 里没有 dzn 驱动 |
| 4 | llama.cpp 编 HIP(gfx1151) | ❌×N | `/opt/rocm-7.2.1` 是**阉割版**:缺 `hip-dev`(无 `hip-lang-config.cmake`) |
| 5 | apt 补全 hip-dev/runtime | ⚠️ | 发现**两套 ROCm 分裂**:7.2.0 有 rocr 运行库,7.2.1 只有工具链 |
| 6 | 软链调和两套 ROCm | ✅ | `libhsa-runtime64.so.1.18.70201` 等 4 条软链,cmake/运行时全通 |
| 7 | llama.cpp HIP 编译成功 | ✅ | 47 tok/s,比 CPU 兜底的 9 tok/s 快 5 倍 |

### 三个决定性洞察

1. **ComfyUI 能跑 GPU ≠ 系统有完整 ROCm**。torch 的 ROCm 轮子自带整套运行时(`torch/lib/`),这是障眼法——原生程序(llama.cpp)根本借不到,得自己拼 `/opt/rocm` + torch 里的 libhsa + librocdxg。
2. **WSL2 里 AMD GPU 的"官方正统"是 DXG**(`/dev/dxg`),不是 `/dev/dri`。一切 ROCm 程序都要 `HSA_ENABLE_DXG_DETECTION=1` + DXG 版 rocr + `librocdxg`。
3. **版本考古是常态**:llama.cpp 找 hip-lang cmake、cmake 找 `.so.1.18.70201`、软链文件名差一个号就翻车——这种 5 分钟的链式排错,耐心比聪明重要。

## 三、最终成果

```
Windows (Python venv)
  │  http://127.0.0.1:11435/v1  Chat:    deepseek-coder:6.7b  (GPU, 47 tok/s)
  │  http://127.0.0.1:11436/v1  Embed:   bge-m3 Q8 dim1024     (GPU)
  └── WSL2 localhost 转发
        llama.cpp build (HIP/gfx1151), 模型 GGUF 本地文件
```

- 服务:两个 `llama-server`(nohup 常驻),模型 GGUF 一个借 Ollama、一个 hf-mirror 下的
- 配置手册落 `C:\furina-agent\`,WSL 里留了份副本

## 四、给 Agent 工程师路径的复盘(不只是技术)

- **OpenAI 兼容协议是万能胶**:llama.cpp/Ollama 全讲 `/v1`,langchain/客户端零适配。搭 Agent 系统时,自建服务对外永远暴露标准协议,比自造协议省一个宇宙的适配。
- **排障要"证据链"思维**:每次下结论前先拿到决定性证据(ldd 报缺哪个 soname、`ls` 看后端目录、`rocminfo` 出不出 gfx1151),而不是"再换个变量试试"。
- **环境配置文档化 = 复利**:今天 7 个坑,若没沉淀,下次重搭又是半天;写下来 10 分钟复现。源码驱动学习者的环境也一样值得版本管理。

## 五、未完成 / 下一步

- [ ] 把 `example1.py` 接上本地服务(改 base_url:chat→11435、embed→11436,数据源换本地文件)
- [ ] (可选)给两个 llama-server 做 systemd/自启脚本,免手工 nohup
- [ ] (可选)后续 agent 若需 tool calling,注意 deepseek-coder 的 function-call 格式未必最稳,必要时换 qwen2.5:7b 对比
- [ ] Ollama 的 bge-m3 下载残留 partial 可清理(已用 hf-mirror GGUF 替代)
