"""
自定agent义异常
"""
#设计哲学——每个异常内设状态和默认消息
#子类通过显示调用 __init__()方法，通过message把错误消息传递给基类的args属性
#args异常消息传递给基类—基类的args的属性，这样str(e)只负责“说什么”
#每个子异常内内设业务字段，负责写入日志，方便排障


class AgentError(Exception):
    code = "AGENT_ERROR"
    default_message = "服务器开小差了，请稍后再试"
    def __init__(self,message:None|str=None):
        self.message = message if message is not None else self.default_message
        #用super()语法糖初始化父类的__int__()方法，初始化继承链上的属性
        super().__init__(self.message)

class MissingRequiredToolError(AgentError):
    code = "MISSING_REQUIRED_TOOL"
    default_message = "缺少必要工具："
    def __init__(self,missing_tools:list[str]|str,message:None|str=None):
        self.missing_tools = missing_tools
        if isinstance(missing_tools,list):
            self.message = [f"{self.default_message}：{tools}"
                            for tools in missing_tools]
            super().__init__(" ".join(self.message))
        else:
            self.message = [f"{self.default_message}：{missing_tools}"]
            super().__init__("".join(self.message))

class InvalidToolError(AgentError):
    code = "INVALID_TOOL"
    default_message = "大模型幻觉工具："
    def __init__(self,invalid_tools:list[str]|str,message:None|str=None):
        self.invalid_tools = invalid_tools
        if isinstance(invalid_tools,list):
            self.message = [f"{self.default_message}：{tools}"
                            for tools in invalid_tools]
            super().__init__(" ".join(self.message))
        else:
            self.message = [f"{self.default_message}：{invalid_tools}"]
            super().__init__("".join(self.message))

class MissingRequiredArgumentError(AgentError):
    code = "MISSING_REQUIRED_ARGUMENT"
    default_message = "缺失必要参数："
    def __init__(self,missing_args:list[str]|str,
                 missing_args_tools:list[str]|str,
                 message:None|str=None
                 ):
        self.missing_args = missing_args
        self.missing_args_tools = missing_args_tools
        if isinstance(missing_args,list)and isinstance(missing_args_tools,list) :
            self.message = [f"{self.default_message}：{tool}：缺少：{args}"
                            for tool,args in zip(missing_args_tools,missing_args)
                            ]
            super().__init__(" ".join(self.message))
        else:
            self.message = [f"{self.default_message}：{missing_args_tools}：缺少：{missing_args}"]

class InvalidArgumentError(AgentError):
    code = "INVALID_ARGUMENT"
    default_message = "大模型幻觉参数："
    "用集合处理大模型的幻觉参数"
    "求输入参数集合和合法参数集合的差集"
    "为空则无幻觉，不为空则把元素遍历出添加到异常消息"
    def __init__(self,invalid_args:list[str]|str,
                 invalid_args_tools:list[str]|str,
                 message:None|str=None):
        self.invalid_args = invalid_args
        self.invalid_args_tools = invalid_args_tools
        if isinstance(invalid_args,list):
            self.message = [f"{self.default_message}：{tool}：出现幻觉参数：{args}"
                            for tool, args in zip(invalid_args_tools, invalid_args)
                            ]
            super().__init__(" ".join(self.message))
        else:
            self.message = [f"{self.default_message}：{invalid_args_tools}：缺少：{invalid_args}"]

