#!/bin/bash

# 检查虚拟环境是否存在
if [ ! -d "venv" ]; then
  echo "首次运行需要先设置环境，请运行 ./start.sh"
  exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 开启代理（如需访问外网）
proxy_on

# 运行程序
python main.py 