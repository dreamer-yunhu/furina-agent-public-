"""
定义节点可能会用到的公共函数，多看，借助deepseek写的，学习思路和设计哲学
"""
import hashlib
from pathlib import Path
import difflib
from langchain_core.messages import ToolMessage
from langchain_protocol import ToolCall
from langgraph.types import Command
from app.agent.exception.error import InvalidToolError, InvalidArgumentError, \
    MissingRequiredArgumentError
from app.schemas.model import WritePreview, ReviewDecision, ReviewAction
from app.agent.registry import registry, ToolRegistry


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
    if target.is_file():
        old_content =await read_normalized(target)
        is_new = False
        old_hash =await sha256_text(old_content)
    else:
        old_content = ""
        is_new = True
        old_hash = None
    new_content = tool_call["args"]["text"]
    add,remove,diff = await make_diff(old_content,new_content,str(target))
    return WritePreview(
        tool_call_id= tool_call["id"],
        path= tool_call["args"]["file_path"],
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

async def classify_tool_calls(raw_tool_calls,
                              risky_tools:set[str],
                              safe_tools:set[str],
                              *,registry:set[str])->tuple[list,list]:
    """
    分离大模型的原始工具调用，以及判断是否编造工具
    :param registry: 工具注册表
    :param safe_tools: 安全工具注册表
    :param risky_tools: 危险工具注册表
    :param raw_tool_calls: 模型原始工具的调用
    :return: 危险和未知工具列表
    """
    _risky = []
    _unknown = []
    raw_tool_set = set(raw_tool_calls)
    fake_tool = raw_tool_set.difference(risky_tools)
    if fake_tool:
        raise InvalidToolError(
            invalid_tools= list(fake_tool),
        )
    for raw in raw_tool_calls:
        if raw.get("name") in risky_tools:
            _risky.append(raw)
        elif raw.get("name") not in safe_tools:
            _unknown.append(raw)
        else:
            continue
    return _risky,_unknown


#定义回复执行函数
async def handle_review_fn(*,payload:ReviewDecision,
                           raw_tool_calls:list[dict],
                           risky_tools:list,
                           raw_args_registry:set[str]
                           ):
    #验证载荷
    if  not isinstance(payload,ReviewDecision):
        raise
        return Command(
            update ={"coder_messages":[
                await build_tool_messages(tc) for tc in raw_tool_calls
            ]},
            goto="model_node")
    #验证工具数目
    tool_list = payload.decisions or []
    if len(tool_list) != len(risky_tools):
        raise
        return Command(
            update={"coder_messages": [
                await build_tool_messages(tc, content="接收的数据不全！") for tc in raw_tool_calls
            ]},
            goto="model_node"
        )
    #校验参数是否齐全
    if registry.coder_tools_args != raw_args_registry:
        raise
        return Command(
            update={"coder_messages":[
                await build_tool_messages(tc,content="缺少必要参数") for tc in raw_tool_calls
            ]},
            goto="model_node"
        )
    # 拒绝字典
    reject = {
        # 加or的原因是前端传null不是空！
        d["tool_call_id"]: d.get("reason") or "用户拒绝批准！"
        for d in tool_list
        if d.get("action") != ReviewAction.APPROVE.value
    }
    # 只要有拒绝的都要回填消息——openai格式要求，调用几个工具就要有几个ToolMessage
    msg = [
        await build_tool_messages(
            tc,
            content=f"用户拒绝，{reject[tc['id']]}"
            if tc["id"] in reject else "同批次有操作被拒绝，本次未执行"
        )
        for tc in raw_tool_calls]
    # 审批
    # 全批准
    if not reject:
        return Command(goto="tools_node")
    else:
        return Command(
            update={"coder_messages": msg},
            goto="model_node")



async def rollback_tool_messages(*,raw_tool_calls,tool_list)->list[ToolMessage]:
    pass





