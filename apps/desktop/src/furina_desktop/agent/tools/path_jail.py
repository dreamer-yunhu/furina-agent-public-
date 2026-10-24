"""
统一agent工具的schemas
"""
from langchain_core.tools import BaseTool
from pathlib import Path
from furina_core.config import settings


# ── AI 新增（问题 1）：保证沙箱根存在 ──
# 背景：`.env` 里 SANDBOX_ROOT 指向的目录可能不存在（全新 clone 就是），
# 首次写入会 Errno 2，而审批预览照样生成 —— 用户批准了一个必然失败的操作。
# 复核重点：这是"修结构"：让"配置了沙箱"蕴含"沙箱存在"，而不是每次调用前判空。
def ensure_sandbox_root(root: str | Path | None = None) -> Path:
    """创建并返回沙箱根（幂等）。默认取 `settings.sandbox_root`。"""
    path = Path(root if root is not None else settings.sandbox_root).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


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

