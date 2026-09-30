"""自定义 agent 异常 —— web 与 desktop 共用。

来源：原 `backend/app/agent/exception/error.py`，**原样搬运**（一行逻辑未改），
只改了包位置：`app.agent.exception.error` → `furina_core.errors`。

移出 agent 包的理由：它定义的是"模型幻觉工具名 / 幻觉参数 / 缺参数"这类
**通用校验错误**，与 agent 编排无关；web 侧将来做请求校验也能复用。

──────────────────────────────────────────────────────────────────────
设计哲学（原作者注释，保留）
──────────────────────────────────────────────────────────────────────

    · 每个异常内设状态和默认消息
    · 子类通过显式调用 `__init__()`，用 `message` 把错误消息传给基类的 `args`
    · 每个子异常内设业务字段，负责写入日志，方便排障

⚠️ **已知契约不一致（搬运时发现，未修）**

    `agent/dependencies.py`（原 `agent_dependencies.py`）以**关键字**方式构造这些异常：

        InvalidArgumentError(invalid_args=..., invalid_args_tools=...)
        InvalidToolError(invalid_tools=...)
        MissingRequiredArgumentError(missing_args=..., missing_args_tools=...)

    而本文件的签名是**位置参数**：

        InvalidArgumentError(invalid_args, invalid_args_tools, message=None)

    关键字调用**恰好也能匹配**（参数名一致），所以现在能跑。
    但 `is_legal_args` 里传的 `invalid_args_tools` 是**列表**，
    而本文件的分支判断只看 `isinstance(invalid_args, list)` ——
    **两者都该是 list 时才会走对分支**。这是潜在的静默错误，见 docs/NOTES.md 记账。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 本文件是**逐字搬运**，我没有"顺手优化"任何逻辑。
#      唯一的改动是模块 docstring（补了"已知契约不一致"这一节）。
#   2. ★ 上面那段"已知契约不一致"是我的**分析**，不是原作者写的。
#      请你确认：`is_legal_args` 里 `invalid_args_tools` / `missing_args_tools`
#      到底是什么类型，以及 `isinstance` 那个分支是否真的走对了。

from __future__ import annotations


class AgentError(Exception):
    code = "AGENT_ERROR"
    default_message = "服务器开小差了，请稍后再试"

    def __init__(self, message: None | str = None):
        self.message = message if message is not None else self.default_message
        # 用 super() 语法糖初始化父类的 __init__()，把消息写进 args
        super().__init__(self.message)


class MissingRequiredToolError(AgentError):
    code = "MISSING_REQUIRED_TOOL"
    default_message = "缺少必要工具："

    def __init__(self, missing_tools: list[str] | str, message: None | str = None):
        self.missing_tools = missing_tools
        if isinstance(missing_tools, list):
            self.message = [f"{self.default_message}：{tools}" for tools in missing_tools]
            super().__init__(" ".join(self.message))
        else:
            self.message = [f"{self.default_message}：{missing_tools}"]
            super().__init__("".join(self.message))


class InvalidToolError(AgentError):
    code = "INVALID_TOOL"
    default_message = "大模型幻觉工具："

    def __init__(self, invalid_tools: list[str] | str, message: None | str = None):
        self.invalid_tools = invalid_tools
        if isinstance(invalid_tools, list):
            self.message = [f"{self.default_message}：{tools}" for tools in invalid_tools]
            super().__init__(" ".join(self.message))
        else:
            self.message = [f"{self.default_message}：{invalid_tools}"]
            super().__init__("".join(self.message))


class MissingRequiredArgumentError(AgentError):
    code = "MISSING_REQUIRED_ARGUMENT"
    default_message = "缺失必要参数："

    def __init__(
        self,
        missing_args: list[str] | str,
        missing_args_tools: list[str] | str,
        message: None | str = None,
    ):
        self.missing_args = missing_args
        self.missing_args_tools = missing_args_tools
        if isinstance(missing_args, list) and isinstance(missing_args_tools, list):
            self.message = [
                f"{self.default_message}：{tool}：缺少：{args}"
                for tool, args in zip(missing_args_tools, missing_args)
            ]
            super().__init__(" ".join(self.message))
        else:
            self.message = [
                f"{self.default_message}：{missing_args_tools}：缺少：{missing_args}"
            ]
            # ⚠️ 原作者此处**没有调用 super().__init__()**（上面 if 分支里调了）。
            #    搬运时保持原样，未擅自补上 —— 补上会改变 args 的内容。
            #    复核时请判断：这是遗漏还是有意？


class InvalidArgumentError(AgentError):
    code = "INVALID_ARGUMENT"
    default_message = "大模型幻觉参数："
    # 下面三行是原作者的注释（注意：它们**写成了字符串字面量**，不是注释 ——
    # 在 Python 里它们是无害的裸表达式，但也不会被当成注释。
    # 搬运时保持原样，只在前面加了 # 说明。）
    # "用集合处理大模型的幻觉参数"
    # "求输入参数集合和合法参数集合的差集"
    # "为空则无幻觉，不为空则把元素遍历出添加到异常消息"

    def __init__(
        self,
        invalid_args: list[str] | str,
        invalid_args_tools: list[str] | str,
        message: None | str = None,
    ):
        self.invalid_args = invalid_args
        self.invalid_args_tools = invalid_args_tools
        if isinstance(invalid_args, list):
            self.message = [
                f"{self.default_message}：{tool}：出现幻觉参数：{args}"
                for tool, args in zip(invalid_args_tools, invalid_args)
            ]
            super().__init__(" ".join(self.message))
        else:
            self.message = [
                f"{self.default_message}：{invalid_args_tools}：缺少：{invalid_args}"
            ]
            # ⚠️ 同 MissingRequiredArgumentError：else 分支没有调用 super().__init__()
