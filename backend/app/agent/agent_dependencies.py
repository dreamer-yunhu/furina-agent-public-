"""
定义节点可能会用到的公共函数，多看，借助deepseek写的，学习思路和设计哲学
"""
import hashlib
from pathlib import Path
import difflib
from app.schemas.model import WritePreview

def is_resolve_in_sandbox(*,sandbox_root: Path, rel_path: str)->Path:
    root = sandbox_root.resolve()
    if not rel_path and  rel_path.strip() == "":
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

def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def read_normalized(path:Path)->str:
    text = path.read_text(encoding="utf-8")
    #返回统一格式的文本，因为Windows和类unix（Linux）的换行符和分割符不一样
    return text.replace("\r\n", "\n").replace("\r", "\n")


# noinspection SpellCheckingInspection
def make_diff(old: str, new: str, path: str)->tuple[int,int,str]:
    """
    识别文件中改了几行（相较于原文件）,改了什么内容
    :return:
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


def build_write_review(*,tool_call, workspace_root):
    rel_path = tool_call["args"]["file_path"]
    target = is_resolve_in_sandbox(
        sandbox_root=workspace_root,
        rel_path=rel_path
    )
    if target.is_file():
        old_content = read_normalized(target)
        is_new = False
        old_hash = sha256_text(old_content)
    else:
        old_content = ""
        is_new = True
        old_hash = None
    new_content = tool_call["args"]["text"]
    add,remove,diff = make_diff(old_content,new_content,str(target))
    return WritePreview(
        tool_call_id= tool_call["id"],
        path= tool_call["args"]["file_path"],
        is_new_file=is_new,
        old_hash=old_hash,
        added=add,
        removed=remove,
        diff=diff
    )




