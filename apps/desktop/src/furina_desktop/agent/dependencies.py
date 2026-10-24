"""
定义节点可能会用到的公共函数，多看，借助deepseek写的，学习思路和设计哲学
"""
import hashlib
from pathlib import Path
import difflib
from langchain_core.messages import ToolMessage
from langchain_protocol import ToolCall
from langgraph.types import Command
from furina_core.config import settings
from furina_core.errors import InvalidArgumentError, \
    MissingRequiredArgumentError
from furina_desktop.agent.contracts import ReviewAction, ReviewDecision, ReviewRequest, WritePreview
from furina_desktop.agent.tools.registry import registry, ToolRegistry


async def is_resolve_in_sandbox(*,sandbox_root: Path, rel_path: str)->Path:
    """
    判断模型给定路径是否越界
    :param sandbox_root: 沙箱绝对路径
    :param rel_path: 模型给的相对路径
    :return: 工具要执行的绝对路径，Path实例
    """
    root = sandbox_root.resolve()
    if not rel_path or rel_path.strip() == "":
        raise ValueError("path不能为空！")
    # 拒绝绝对路径（Unix 和 Windows 两种风格都挡）
    candidate_input = Path(rel_path)
    if candidate_input.is_absolute():
        raise ValueError(f"不允许绝对路径: {rel_path}")
    #拼接路径，方便后续判断
    target = (root / rel_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"path 逃逸出沙箱: {rel_path}")
    return target

async def is_legal_args(*,input_args:str|list[str],
                        registry_args_set:set[str],
                        raw_tool_call,
                        )->set[str]:
    """
    识别参数是否缺失必要参数，是否编造
    :param raw_tool_call: 经过校验（是否缺少，幻觉工具）的原始工具调用
    :param input_args: 模型输入参数
    :param registry_args_set: 注册表必填参数
    :return: 必填参数完备和无幻觉参数的集合
    """
    input_args_set = set(input_args)
    #判断是否有幻觉参数
    #既实现了集合的差集运算，也保留了顺序
    fake_args = [args for args in input_args_set if args not in registry_args_set]
    if fake_args:
        invalid_args_tools = [
            tools
            for invalid_args,tools in zip(fake_args,raw_tool_call)
            if invalid_args in tools["args"]
        ]
        raise InvalidArgumentError(
            invalid_args= fake_args,
            invalid_args_tools= invalid_args_tools,
        )
    #判断是否缺少参数
    pub = [args for args in input_args_set if args in registry_args_set] #相当于求有顺序的交集
    if set(pub)!= registry_args_set:
        missing_args_tools = [
            tools
            for missing_args,tools in zip(pub,raw_tool_call)
            if missing_args not in tools["args"]
        ]
        raise MissingRequiredArgumentError(
            missing_args=pub,
            missing_args_tools= missing_args_tools,
        )
    return input_args_set

async def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

async def read_normalized(path:Path)->str:
    text = path.read_text(encoding="utf-8")
    #返回统一格式的文本，因为Windows和类unix（Linux）的换行符和分割符不一样
    return text.replace("\r\n", "\n").replace("\r", "\n")


# noinspection SpellCheckingInspection
async def make_diff(old: str, new: str, path: str)->tuple[int,int,str]:
    """
    识别文件中改了几行（相较于原文件）,改了什么内容
    :return:增加，移除，修改内容
    """
    #将原先的字符串切割为行列表，difflib库只接受行列表
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    #keepends参数是重点，默认的切法会把\n切割掉，后续拼接时会全部粘在一起
    diff_lines=list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",  # 旧文件在 --- 行显示的标签
        tofile=f"b/{path}",  # 新文件在 +++ 行显示的标签
        #这么写的缘故是对齐git格式
        n=3,  # 上下文行数——即显示改动块前面和后面的代码行数
        #重点——这个函数返回的是一个生成器，只能遍历一次，之后为空，要多次使用转列表
    ))
    add = sum(1 for line in diff_lines if line.startswith("+")and not line.startswith("+++"))
    remove = sum(1 for line in diff_lines if line.startswith("-")and not line.startswith("---"))
    #注意，这里的1是每个满足条件的权重
    return add,remove,"".join(diff_lines)


async def build_write_review(*,tool_call, workspace_root)-> WritePreview:
    """
    构造interrupt载荷函数
    :param tool_call: 工具调用字典
    :param workspace_root: 沙箱目录
    :return: interrupt载荷
    """
    rel_path = tool_call["args"]["file_path"]

    target =await is_resolve_in_sandbox(
            sandbox_root=workspace_root,
            rel_path=rel_path
        )
    # <- AI 改动（T16）：目录不是"新文件"。原实现 target.is_file() 为 False
    #    就当成新建，diff 里会显示一个"空文件 → 文本"，审批人看到的信息是假的。
    #    复核重点：这里抛 ValueError 会被 prevalidate_node 的 except 接住并回填给模型。
    if target.exists() and not target.is_file():
        raise ValueError(f"目标是目录，不能作为文件写入: {rel_path}")
    if target.is_file():
        old_content =await read_normalized(target)
        is_new = False
        old_hash =await sha256_text(old_content)
    else:
        old_content = ""
        is_new = True
        old_hash = None
    new_content = tool_call["args"]["text"]
    # <- AI 改动（T15）：fromfile/tofile 原来传的是 `str(target)`（绝对路径），
    #    审批载荷会把这个人的用户名、目录结构一起送到前端。改用沙箱相对路径。
    #    复核重点：`as_posix()` 是为了 Windows 反斜杠不污染 diff 头。
    display_path = Path(rel_path).as_posix()
    # ── AI 新增（T34）：列出执行时会新建的目录，由浅到深 ──
    # 复核重点：只统计**尚不存在**的祖先目录；已存在的不列，避免审批人误以为会重建。
    # 边界：`target.parent` 一路向上走到沙箱根为止，越界路径在 is_resolve_in_sandbox 就被挡了。
    missing_dirs: list[str] = []
    root = Path(workspace_root).resolve()
    parent = target.parent
    while parent != root and parent.is_relative_to(root):
        if not parent.exists():
            missing_dirs.append(parent.relative_to(root).as_posix())
        parent = parent.parent
    missing_dirs.reverse()

    add,remove,diff = await make_diff(old_content,new_content,display_path)
    return WritePreview(
        tool_call_id= tool_call["id"],
        path= tool_call["args"]["file_path"],
        creates_dirs=missing_dirs,
        is_new_file=is_new,
        old_hash=old_hash,
        added=add,
        removed=remove,
        diff=diff
    )

async def build_tool_messages(tc:dict,
                        content:str="调用工具失败，请求工具数量和传入工具数量不符！"
                        )->ToolMessage:
    """
    构造回填ToolMessage的函数
    :param tc: 工具调用字典
    :param content: 回填文本
    :return: ToolMessage实例
    """
    tool_name = tc["name"]
    tool_call_id = tc["id"]
    content = f"{content}"
    return ToolMessage(
        content=content,
        name=tool_name,
        tool_call_id=tool_call_id,
        status= "error",
    )

# <- AI 改动：整个函数重写。
#   原实现有两个错误（阶段 1 报告 B2）：
#     ① set(raw_tool_calls) 对 list[dict] 做集合 → TypeError: unhashable type: 'dict'
#     ② difference(risky_tools) 把**所有安全工具**也算成"幻觉工具"
#   现改为按 name 分三堆，未知工具不抛异常、由调用方回填错误消息（fail-closed）。
#   复核重点：返回顺序从 (risky, unknown) 变成 (risky, safe, unknown)，
#   调用方必须同步改；registry 参数已删除（它原本就没被用到）。
async def classify_tool_calls(raw_tool_calls,
                              risky_tools:set[str],
                              safe_tools:set[str])->tuple[list,list,list]:
    """
    分离大模型的原始工具调用
    :param safe_tools: 安全工具名单
    :param risky_tools: 高风险工具名单
    :param raw_tool_calls: 模型原始工具的调用（list[dict]，不是 set）
    :return: (高风险, 安全, 未知)
    """
    _risky: list = []
    _safe: list = []
    _unknown: list = []
    for raw in raw_tool_calls:
        name = raw.get("name")
        if name in risky_tools:
            _risky.append(raw)
        elif name in safe_tools:
            _safe.append(raw)
        else:
            _unknown.append(raw)
    return _risky, _safe, _unknown


# ── AI 新增（T14）：审批期间目标文件被改动的检测 ──
# 背景：`WritePreview.old_hash` 之前只写不校验，用户批准时拿的是几分钟前的 diff，
# 期间文件可能已被编辑器/别的工具改过 —— 直接覆盖就是静默丢数据。
# 复核重点：
#   1. 这是**窄化**竞态窗口，不是消除它：校验通过到 ToolNode 真正落盘之间仍有间隙。
#      要彻底原子化，得把"重新读 + 比对 + 写"收进同一个执行器（T23）。
#   2. 新建文件用"是否已存在"判断；存在即冲突，不能悄悄覆盖别人刚创建的文件。
async def verify_preview_unchanged(*, preview: WritePreview, workspace_root) -> str | None:
    """返回 None 表示与送审时一致；否则返回冲突说明。"""
    target = await is_resolve_in_sandbox(
        sandbox_root=workspace_root,
        rel_path=preview.path,
    )
    if preview.is_new_file:
        if target.exists():
            return f"审批期间该文件已被创建：{preview.path}"
        return None
    if not target.is_file():
        return f"审批期间该文件已被删除：{preview.path}"
    current_hash = await sha256_text(await read_normalized(target))
    if current_hash != preview.old_hash:
        return f"审批期间该文件已被修改：{preview.path}"
    return None


#定义回复执行函数
# <- AI 改动：整函数重写。
#   原实现的问题（阶段 1 报告 B6/B9）：
#     ① 三处裸 `raise` → RuntimeError，后面的回填逻辑永远不可达
#     ② 用 payload/risky_tools 的"数量相等"判断完整性，而不是按 tool_call_id 对齐
#     ③ 拿 registry.coder_tools_args（所有工具参数名的并集）和单次调用比较
#   现改为：按 tool_call_id 对齐 + 未知 id 拦截 + 明确返回 Command。
#   复核重点：拒绝时仍然是"整批不执行"（与现状语义一致）；V1 是否要改成
#   逐条执行，等确认后再动（总案 Q4）。
async def handle_review_fn(*,decision:ReviewDecision,
                           snapshot:ReviewRequest,
                           raw_tool_calls:list[dict],
                           )->Command:
    decided = {d.tool_call_id: d for d in decision.decisions}
    sent_ids = {r.tool_call_id for r in snapshot.requests}

    # 完整性：每个送审项都必须有且只有一个决定
    missing = [tid for tid in sent_ids if tid not in decided]
    if missing:
        return Command(
            update={"coder_messages": [
                await build_tool_messages(tc, content="审批结果不完整，请重新审批！")
                for tc in raw_tool_calls
            ]},
            goto="model_node",
        )
    # 合法性：不能对没有送审的调用做决定（防伪造/串批）
    extra = [tid for tid in decided if tid not in sent_ids]
    if extra:
        return Command(
            update={"coder_messages": [
                await build_tool_messages(tc, content="审批结果包含未知的调用，已阻止执行！")
                for tc in raw_tool_calls
            ]},
            goto="model_node",
        )

    # 拒绝字典
    reject = {
        tid: (d.reason or "用户拒绝批准！")
        for tid, d in decided.items()
        if d.action != ReviewAction.APPROVE
    }
    # 只要有拒绝的都要回填消息——openai格式要求，调用几个工具就要有几个ToolMessage
    if reject:
        msg = [
            await build_tool_messages(
                tc,
                content=f"用户拒绝，{reject[tc['id']]}"
                if tc["id"] in reject else "同批次有操作被拒绝，本次未执行"
            )
            for tc in raw_tool_calls
        ]
        return Command(
            update={
                "coder_messages": msg,
                "pending_reviews": None,
                "decision_reviews": None,
            },
            goto="model_node",
        )
    # ── AI 新增（T14）：全批准后、真正执行前，回头核对文件是否还停在送审时的样子 ──
    #    任何一项冲突都整批作废：因为 ToolNode 是一次性执行整批 tool_calls，
    #    逐条放行会造出"一半写了、一半没写"的撕裂状态（逐条粒度见 TODO Q1）。
    #    复核重点：冲突时把 pending 清空并回 model_node，让模型重新发起审批，
    #    而不是直接抛错 —— 否则这条 thread 会永远停在脏的 interrupt 上。
    conflicts = []
    for preview in snapshot.requests:
        conflict = await verify_preview_unchanged(
            preview=preview,
            workspace_root=settings.sandbox_root,
        )
        if conflict:
            conflicts.append(conflict)
    if conflicts:
        content = "审批已失效，未执行任何写入：\n" + "\n".join(f"- {item}" for item in conflicts)
        return Command(
            update={
                "coder_messages": [
                    await build_tool_messages(tc, content=content)
                    for tc in raw_tool_calls
                ],
                "pending_reviews": None,
                "decision_reviews": None,
            },
            goto="model_node",
        )

    # 全批准：清除快照，避免下一次轮次复用旧审批
    return Command(
        update={"pending_reviews": None, "decision_reviews": None},
        goto="tools_node",
    )



async def rollback_tool_messages(*,raw_tool_calls,tool_list)->list[ToolMessage]:
    pass





