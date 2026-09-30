"""
coder子智能体专用工具
"""
import logging
from furina_desktop.agent.tools.path_jail import BaseFileTool, PathOutOfSandbox
from pydantic import BaseModel,Field
logger = logging.getLogger(__name__)

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
             with open(safe_path,mode="r",encoding="utf-8") as f:
                 return f.read()
        except PathOutOfSandbox as e:
            logger.critical("模型出现越界读取沙箱外文件企图！目标文件=%s",e.path,exc_info=e)
            return str(e)
        except (FileNotFoundError, PermissionError, IsADirectoryError, UnicodeDecodeError) as e:
            return str(e)





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
            with open(safe_path,mode="w",encoding="utf-8") as f:
                f.write(text)
                return f"执行成功"
        except  PathOutOfSandbox as e:
            logger.critical("模型出现越界写入沙箱外文件企图！目标=%s",e.path,exc_info=e)
            return str(e)
        except (FileNotFoundError, PermissionError, IsADirectoryError, UnicodeDecodeError) as e:
            return str(e)


