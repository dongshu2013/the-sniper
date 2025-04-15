#!/bin/bash

# 创建日志目录
mkdir -p /Users/kevin/3-work/36-MIZU/366-projects/the-sniper/logs

# 激活 conda 环境
source /Users/kevin/miniconda3/etc/profile.d/conda.sh
conda activate realchar-env

# 切换到项目目录
cd /Users/kevin/3-work/36-MIZU/366-projects/the-sniper

# 运行 Python 脚本
python3 src/scripts/setup.py src/scripts/setup_local.yaml --scheduled