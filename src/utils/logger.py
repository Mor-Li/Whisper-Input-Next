import atexit
import logging
import os
import queue
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler

import colorlog


def setup_logger():
    """配置彩色日志（经队列异步写出）。

    日志必须异步：热键监听跑在 macOS 事件 tap 回调线程里，如果 logger 直接写
    stdout（常见跑法 `python main.py | tee ...` 是个管道），终端一卡输出就会阻塞
    回调；macOS 判定回调超时后会禁用整个事件 tap，热键从此失灵。QueueHandler
    入队是纯内存操作，真正的终端/文件写出由独立线程完成。
    """
    # 创建logs目录
    os.makedirs('logs', exist_ok=True)

    # 控制台处理器
    console_handler = colorlog.StreamHandler()
    console_handler.setFormatter(colorlog.ColoredFormatter(
        fmt='%(asctime)s - %(log_color)s%(levelname)-8s%(reset)s - %(message)s',
        datefmt='%H:%M:%S',
        log_colors={
            'DEBUG':    'cyan',
            'INFO':     'green',
            'WARNING': 'yellow',
            'ERROR':   'red',
            'CRITICAL': 'red,bg_white',
        },
        secondary_log_colors={},
        style='%'
    ))

    # 文件处理器
    file_handler = RotatingFileHandler(
        'logs/app.log',
        maxBytes=1024*1024,  # 1MB
        backupCount=5
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))

    log_queue = queue.SimpleQueue()
    queue_listener = QueueListener(
        log_queue, console_handler, file_handler,
        respect_handler_level=True,
    )
    queue_listener.start()
    atexit.register(queue_listener.stop)

    logger = colorlog.getLogger(__name__)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    logger.addHandler(QueueHandler(log_queue))
    logger.setLevel(logging.INFO)

    return logger

logger = setup_logger()
