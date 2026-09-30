"""路径越界守卫 —— 把模型给出的路径钳在沙箱目录内。

═══════════════════════════════════════════════════════════════════════
一、先纠正一个容易误解的定位
═══════════════════════════════════════════════════════════════════════

**这不是进程级沙箱，是"路径边界"。**

    它能挡：模型给出一个跑到沙箱外的**路径**（"../etc/passwd"）
    它挡不住：模型让工具执行**任意代码**（那需要进程/容器隔离）

文档 `docs/PLAN.md` §十三 已经明确纠正过这个认知。定位清楚了才知道
该在哪里加别的防线 —— 不要指望这一个类解决安全问题。

═══════════════════════════════════════════════════════════════════════
二、⭐ 为什么必须"两道门"（这是本文件最值得学的部分）
═══════════════════════════════════════════════════════════════════════

直觉做法是"判断路径是不是绝对路径，不是就放行"：

    if Path(path).is_absolute():
        raise ...          # 第一道门
    return root / path     # 放行

**这个写法能被绕过，而且绕过方式很反直觉。** 看一个具体的漏网输入：

    path = "/etc/passwd"

    Windows 上：PureWindowsPath("/etc/passwd").is_absolute()  ->  False  ！
        （因为 Windows 的"绝对路径"需要盘符，如 C:\\ ；只有根斜杠不算）
        -> 第一道门放行了

    然后：root / "/etc/passwd"
        Python 的 pathlib 规则：**右侧如果是绝对路径，会替换掉左侧**！
        于是 (C:\\sandbox) / "/etc/passwd"  ==  /etc/passwd
        -> 跑出沙箱了

这个坑叫"根相对路径"（root-relative）。所以真正的防线不在第一道门。

【第二道门（真正兜住的那个）】

    target = (root / path).resolve()        # 拼完再解析成"真实路径"
    if not target.is_relative_to(root):     # 比对真实路径
        raise ...

为什么它挡得住：
    · 不管第一道门怎么被绕过，拼出来的结果都会被拿来检查
    · `.resolve()` 会**展开符号链接**：沙箱里放一个 link -> /etc/passwd，
      解析后露出的真身是 /etc/passwd，`is_relative_to` 立刻拦下
    · 比对的是"解析后的真实路径"，不是"输入的字符串" —— 这是关键差别

【为什么不能用 startswith】

    "/sandbox-evil/x".startswith("/sandbox")   ->   True   ❌ 错误放行！

字符串前缀匹配会把"名字恰好以沙箱名为前缀"的兄弟目录当成沙箱内。
`is_relative_to()` 是按**路径分量**比较的，不会犯这个错。

═══════════════════════════════════════════════════════════════════════
三、顺序不能改
═══════════════════════════════════════════════════════════════════════

    ① 空值检查
    ② is_absolute()  —— 意图检查（挡不全，但报错信息更清楚）
    ③ resolve()      —— 展开符号链接与 ".."，是第二步成立的前提
    ④ is_relative_to() —— 结果校验（唯一不可绕过的）

②④ 的定位不同，别把安全押在②上。
`PathJail.__init__` 里对 root 做 `.resolve()` 同样不能省 ——
少了它，`is_relative_to` 比对的是未解析路径，符号链接能绕过去。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点（安全代码，请务必自己验一遍）：
#   1. 空值判断从 `and` 改成了 `or`。原版 `not rel_path and rel_path.strip() == ""`：
#        输入 ""      -> 左边 True  -> 抛错 ✅
#        输入 "   "   -> 左边 False -> **短路漏过** ❌
#        输入 None    -> None.strip() -> AttributeError ❌
#      请自己构造这三种输入各验一次。
#   2. `is_absolute()` 那道门**挡不住根相对路径**（见上面第二节）。
#      请确认你没有依赖第一道门做安全判断。
#   3. `PathJail.__init__` 和 `resolve()` 里的 `.resolve()` 都不能省。

from __future__ import annotations

from pathlib import Path


class PathOutOfSandbox(Exception):
    """路径逃出沙箱。

    ⚠️ 一个刻意的设计：**异常消息里不含真实路径**。

    为什么：这个异常最终会被工具转成字符串返回给**模型**。如果把真实路径
    放进消息里（比如 "C:\\sandbox\\..\\..\\etc\\passwd 越界了"），等于把服务器的
    目录结构告诉模型 —— 那反而成了信息泄漏。

    真实路径存在 `self.target` 属性里，供**日志**排查用（人看，模型看不到）。
    """

    def __init__(self, root: Path, target: Path) -> None:
        self.root = root      # 沙箱根，给人看
        self.target = target  # 被拒的真实路径，给人看
        super().__init__("超出可操作范围，请说明需求交由用户决定！")  # 这句会给模型看


class PathJail:
    """把相对路径解析为沙箱内的绝对路径，越界即抛 `PathOutOfSandbox`。

    名字里的 Jail（监狱）是刻意的比喻：路径进来可以，但出不去。

    用法：

        jail = PathJail(settings.sandbox_root)
        target = jail.resolve("notes/memo.txt")     # -> 沙箱内绝对路径
        jail.resolve("../../etc/passwd")            # -> 抛 PathOutOfSandbox

        # 只问"在不在里面"、不抛异常的版本（用于审批前预检）：
        if jail.is_inside(user_supplied_path):
            ...
    """

    def __init__(self, root: str | Path) -> None:
        # ⚠️ `.resolve()` 必须在这里做，而且只做一次。
        # 理由：后面每次比对都要拿 root 当基准，而符号链接只有在解析后
        # 才会露出真身。如果 root 本身没解析（比如 root 是个符号链接），
        # 那么 `is_relative_to` 的比对基准就是假的，整道防线失效。
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        """解析后的沙箱根。只读暴露，方便日志与其他模块复用同一基准。"""
        return self._root

    def resolve(self, rel_path: str) -> Path:
        """解析并校验。`rel_path` 必须是沙箱内的**相对**路径。

        校验顺序见模块 docstring 第三节，不要调换。
        """
        # ---- ① 空值检查 ----
        if not rel_path or not rel_path.strip():
            # 两个条件用 or 连接（原版写成了 and，见文件头的复核重点 1）：
            #   not rel_path            -> 挡 None 和 ""
            #   not rel_path.strip()    -> 挡 "   " 这类纯空白
            # 缺任何一个都有漏网输入。
            raise ValueError("path 不能为空！")

        # ---- ② 第一道门：意图检查（挡不全，但报错信息更清楚）----
        if Path(rel_path).is_absolute():
            raise ValueError(f"不允许绝对路径: {rel_path}")

        # ---- ③ 拼接 + 解析 ----
        # 这一步同时做两件事，都很重要：
        #   · 拼接：(root / rel_path)
        #   · 解析：.resolve() 展开 ".." 和符号链接，得到"真实路径"
        # 注意 `.resolve()` 默认 strict=False，路径不存在也不报错 ——
        # 这正是我们要的：写新文件时目标还不存在，不能因此拒绝。
        target = (self._root / rel_path).resolve()

        # ---- ④ 第二道门：结果校验（唯一不可绕过的）----
        # 比对的是 resolve 之后的真实路径，所以前面所有花招在这里都会现形。
        if not target.is_relative_to(self._root):
            raise PathOutOfSandbox(root=self._root, target=target)
        return target

    def is_inside(self, rel_path: str) -> bool:
        """只问"在不在沙箱里"，不抛异常。

        用途：审批前预检（例如判断模型给的路径是否值得弹给用户看），
        这种场景"不在里面"是正常业务分支，不该用异常表达。

        实现上是把 `resolve()` 的两种拒绝都吃掉 —— 注意 `ValueError`
        （空路径/绝对路径）也要一起捕获，否则预检会漏掉那两类输入。
        """
        try:
            self.resolve(rel_path)
        except (ValueError, PathOutOfSandbox):
            return False
        return True
