"""PyInstaller 打包入口（不是产品代码）。

`furina_desktop.main:run` 才是真正的入口；这里只是把包级入口变成一个
可执行脚本文件，因为 PyInstaller 需要的是一个 .py 路径，而不是模块名。

⚠️ 打包相关说明见 scripts/build_backend.py。改这里之前先读那份文档头。
"""

from furina_desktop.main import run

if __name__ == "__main__":
    run()
