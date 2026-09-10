"""
提示词工厂基类
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class PromptLoader:
    prompt_dir : Path
    def __init__(self,prompt_dir : Path):
        self.prompt_dir = prompt_dir
        self._cache:dict[str,str] = {}
    def row_prompt(self,prompt_path:str)->str:
        try:
            with open(prompt_path,"r",encoding="utf-8") as f:
                text = f.read()
                return text
        except (FileNotFoundError, PermissionError, IsADirectoryError, UnicodeDecodeError) as e:
            logger.critical("读取提示词失败！失败原因=%s",e.args,exc_info=e)
