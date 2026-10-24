"""
coder子智能体专用工具
"""
import logging
from furina_desktop.agent.tools.path_jail import BaseFileTool, PathOutOfSandbox
from pydantic import BaseModel,Field
logger = logging.getLogger(__name__)

# ── AI 新增（问题 3）：IO 异常的对外措辞白名单 ──
# 背景：原来直接 return str(e)，而 OSError 的 str 里带**绝对路径**
# （实测模型把 `C:\furina-agent\sandbox\...` 原样复述给了用户）。
# 复核重点：新增异常类型时**必须**在这里加分支；兜底分支只回类型名，不回消息体。
def _safe_error_message(*, exc: Exception, rel_path: str) -> str:
    if isinstance(exc, FileNotFoundError):
        return f"文件或目录不存在：{rel_path}"
    if isinstance(exc, PermissionError):
        return f"没有权限访问：{rel_path}"
    if isinstance(exc, IsADirectoryError):
        return f"目标是目录，不是文件：{rel_path}"
    if isinstance(exc, UnicodeDecodeError):
        return f"文件不是 UTF-8 编码的文本：{rel_path}"
    return f"操作失败：{rel_path}（{type(exc).__name__}）"


class ReadFileInput(BaseModel):
    """
    写给大模型看调用读取文件方法时的说明书
    """
    file_path:str = Field(max_length=256,description="要读取文件的路径")

class WriteFileInput(BaseModel):
    """
    调用写入文件操作函数的说明书
    """
    file_path:str = Field(max_length=256,description="要进行写入的文件路径")
    text:str = Field(description="执行写入操作的完整内容")

class ReadFileTool(BaseFileTool):
    """
    读取文件工具
    """
    name:str = "read_file_tool"
    args_schema : type[ReadFileInput] = ReadFileInput
    description : str = "当你试图读取一个文件时调用这个工具"
    def _run(self,file_path:str)->str:
        #判断是否越界
        try:
             safe_path= self._resolve(file_path)
             # <- AI 改动（问题 3）：Windows 上 open(目录) 抛的是 PermissionError，
             #    先显式判断，免得把"目标是目录"误报成"没有权限"。
             if safe_path.is_dir():
                 return f"目标是目录，不是文件：{file_path}"
             with open(safe_path,mode="r",encoding="utf-8") as f:
                 return f.read()
        except PathOutOfSandbox as e:
            logger.critical("模型出现越界读取沙箱外文件企图！目标文件=%s",e.path,exc_info=e)
            return str(e)
        except (FileNotFoundError, PermissionError, IsADirectoryError, UnicodeDecodeError) as e:
            # <- AI 改动：绝对路径只进日志，不进模型上下文
            logger.warning("读取失败 path=%s", file_path, exc_info=e)
            return _safe_error_message(exc=e, rel_path=file_path)





class WriteFileTool(BaseFileTool):
    """
    写入文件工具
    """
    name:str = "write_file_tool"
    args_schema : type[WriteFileInput] = WriteFileInput
    description :str = "当你试图写入文件时调用这个工具"
    def _run(self,file_path:str,text:str)->str:
        try:
            safe_path= self._resolve(file_path)
            if safe_path.is_dir():
                return f"目标是目录，不是文件：{file_path}"
            # <- AI 改动（问题 2）：沙箱内允许自动建父目录。
            #    理由：当前没有 mkdir 工具，模型写 `sub/x.txt` 只能失败；
            #    而审批载荷里已展示完整相对路径，用户看得到要创建的结构。
            #    复核重点：`mkdir` 发生在 `_resolve` 之后，越界路径到不了这里。
            #    代价：创建目录这个副作用没有单独出现在 diff 里（待加 creates_dirs）。
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            with open(safe_path,mode="w",encoding="utf-8") as f:
                f.write(text)
                return f"执行成功"
        except  PathOutOfSandbox as e:
            logger.critical("模型出现越界写入沙箱外文件企图！目标=%s",e.path,exc_info=e)
            return str(e)
        except (FileNotFoundError, PermissionError, IsADirectoryError, UnicodeDecodeError) as e:
            logger.warning("写入失败 path=%s", file_path, exc_info=e)
            return _safe_error_message(exc=e, rel_path=file_path)


