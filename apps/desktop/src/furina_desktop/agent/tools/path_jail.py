"""
统一agent工具的schemas
"""
from langchain_core.tools import BaseTool
from pathlib import Path
from furina_core.config import settings


class PathOutOfSandbox(Exception):
    """越界。内部携带真实路径供日志排查，但不要吐露给模型"""
    def __init__(self,root:Path,path:Path):
        self.root = root
        self.path = path
        super().__init__(f"超出可操作范围，请说明需求交由用户决定!")

class BaseFileTool(BaseTool):
    """
    统一规范agent调用涉及风险操作的权限和边界
    """
    root_dir: str = settings.sandbox_root
    def _resolve(self,path:str)->Path:
        root = Path(self.root_dir).resolve() #获取绝对路径
        target = (root/Path(path)).resolve()
        try:
            target.relative_to(root)
            return target
        except ValueError:
            raise PathOutOfSandbox(root=root,path=target)

