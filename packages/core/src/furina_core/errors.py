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

⚠️ **已知契约不一致（搬运时发现；2026 本轮已修一半）**

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

──────────────────────────────────────────────────────────────────────
对外契约（黑盒使用者只看这一段）
──────────────────────────────────────────────────────────────────────

    · 四个子类都暴露业务字段（`invalid_tools` / `missing_args` …），除 `message` 外都是
      **原样存下你传进去的值**，不做校验、不做拷贝。
    · `self.message` 与 `str(e)` **统一是 str**（本轮修复前，两个类的 else 分支会退化成
      list 且 `str(e) == ""`）。多条目之间用单个空格连接。
    · 参数"列表 / 单个字符串"两种写法都支持，但**分支只看第一个参数的类型**：
      传 list 走"每条一句"；传字符串走"合成一句"。
    · `code` 是类属性（如 `INVALID_TOOL`），用于日志分类，不参与 `args`。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 本文件最初是**逐字搬运**（只补了 docstring）。
#   2. ★ 本轮修了一个真 bug：`MissingRequiredArgumentError` / `InvalidArgumentError`
#      的 else 分支**漏调 `super().__init__()`** → `e.args == ()`、`str(e) == ""`、
#      `e.message` 退化成 list。修法是在 else 分支补上与 if 分支相同的调用。
#      实测影响的输入：两个参数里只要有一个**不是 list**（例如都传字符串）。
#      现有调用点（desktop `is_legal_args`）传的都是 list，所以**改前也没暴露**。
#   3. ★ 上面那段"已知契约不一致"是**我的分析**，不是原作者写的。
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
        # ── AI 改动 ── 复核重点：`message` 这个参数原来**被静默忽略**（签名里有、函数体从不读）。
        #    现按签名承诺使用它；不传时行为与改前完全一致（走下面的默认文案分支）。
        if message is not None:  # <- AI 改动
            super().__init__(message)
            return
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
        if message is not None:  # <- AI 改动：原来被静默忽略（理由同 MissingRequiredToolError）
            super().__init__(message)
            return
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
        if message is not None:  # <- AI 改动：原来被静默忽略（理由同 MissingRequiredToolError）
            super().__init__(message)
            return
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
            # ── AI 改动 ── 复核重点：这里原来**没有**调用 `super().__init__()`，
            #    后果是 else 分支（两个参数只要有一个不是 list）下 `e.args == ()`、
            #    `str(e) == ""` —— 异常对象带不出任何消息，而 `e.message` 又是个
            #    **list**（其它分支被 super() 覆盖成字符串，类型不一致）。
            #    现在补上，与 if 分支写法完全一致：`message` 统一为 str，args 非空。
            super().__init__(" ".join(self.message))  # <- AI 改动


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
        if message is not None:  # <- AI 改动：原来被静默忽略（理由同 MissingRequiredToolError）
            super().__init__(message)
            return
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
            # ── AI 改动 ── 复核重点：同 MissingRequiredArgumentError，原 else 分支漏掉了
            #    `super().__init__()`（args 为空、message 退化成 list）。已补齐。
            super().__init__(" ".join(self.message))  # <- AI 改动
