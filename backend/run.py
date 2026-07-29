"""
用于启动服务
"""
import logging
import uvicorn
if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    logger.info("成功启动服务")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000,reload=True)

import traceback
import sys
def global_exception_handler(exc_type, exc_value, exc_tb):
    traceback.print_exception(exc_type, exc_value, exc_tb)
sys.excepthook = global_exception_handler