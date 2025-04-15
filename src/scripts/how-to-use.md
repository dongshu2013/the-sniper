# Telegram 同步脚本使用指南

## 1. 简介

Telegram 同步脚本用于自动收集 Telegram 群组/频道的信息和消息，并将数据同步到 API 服务器。它支持多个 Telegram 账号，可以定时自动运行，适合部署在服务器上进行数据同步。

## 2. 配置文件说明

配置文件使用 YAML 格式，包含以下主要内容：

```yaml
# API 配置
api_base_url: https://www.curifi.xyz/api
api_key: sk-curifi-1488bd474e8649a9b59e04f905230293

# Telegram 账号配置
accounts:
  - telegram_api_id: 24304519
    telegram_api_hash: 7322ed52ffd5842b566e4aeb09b642a8
    telegram_phone: "+8801307763339" # 账号电话号码
    dialog_limit: 0 # 0表示无限制
    message_limit: 500 # 每个群组获取的消息数量
```

### 配置项说明：

- `api_base_url`: API 服务器基础 URL
- `api_key`: API 访问密钥
- `accounts`: Telegram 账号列表
  - `telegram_api_id`: Telegram API ID
  - `telegram_api_hash`: Telegram API Hash
  - `telegram_phone`: Telegram 账号电话号码
  - `dialog_limit`: 要同步的对话数量限制 (0 表示无限制)
  - `message_limit`: 每个对话要同步的消息数量限制 (0 表示无限制)

## 3. 本地运行

1. 手动测试运行:

```Shell
   # 单次运行
   python src/scripts/setup.py src/scripts/setup_env.yaml

   # 带调度的运行
   python src/scripts/setup.py src/scripts/setup_env.yaml --scheduled
```

2. 使用运行脚本:

```Shell
   # 确保脚本有执行权限
   chmod +x src/scripts/run_telegram_sync.sh

   # 运行脚本
   ./src/scripts/run_telegram_sync.sh
```

3. 使用 crontab 设置定时任务:

```Shell
   # 编辑crontab
   crontab -e

   # 添加定时任务，例如每5分钟运行一次
   */5 * * * * cd /Users/kevin/3-work/36-MIZU/366-projects/the-sniper && ./src/scripts/run_telegram_sync.sh >> /Users/kevin/3-work/36-MIZU/366-projects/the-sniper/logs/cron.log 2>&1
```

### 4. 本地停止

1. 如果在当前终端运行:
   直接按 Ctrl+C 中断执行

2. 如果在后台或其他终端运行:

找到进程 ID 并终止:

```Shell
     # 查找Python进程
     ps aux | grep "setup.py"

     # 终止进程 (将PID替换为实际进程ID)
     kill <PID>

     # 如果进程没有响应，强制终止
     kill -9 <PID>
```

3. 如果使用 run_telegram_sync.sh 脚本启动:

```Shell
   # 查找运行脚本的进程
   ps aux | grep "run_telegram_sync.sh"

   # 或者直接找到所有相关Python进程
   ps aux | grep "python.*setup.py"

   # 终止找到的进程
   kill <PID>
```

## 4. AWS 服务器部署

### 前置准备

1. 安装必要的软件包：

   ```bash
   sudo yum update -y
   sudo yum install -y python3 python3-pip git tmux
   ```

2. 安装 Python 依赖：
   ```bash
   sudo pip3 install telethon pyyaml requests boto3
   ```

### 首次设置

1. 创建目录结构：

   ```bash
   mkdir -p /home/ec2-user/mysta_scripts/photos
   ```

2. 上传/创建必要文件：

   - `setup.py` - 主脚本文件
   - `setup_prod.yaml` - 生产环境配置文件

3. 手动运行以生成 Telegram 会话：
   ```bash
   cd /home/ec2-user/mysta_scripts
   tmux new -s telegram-setup
   python3 setup.py setup_prod.yaml
   ```
   当提示时输入 Telegram 验证码。

### tmux

使用 tmux 创建一个会话，以便在断开 SSH 连接后脚本仍能继续运行：

```Shell
# 使用 tmux 创建一个会话，以便在断开 SSH 连接后脚本仍能继续运行
tmux new -s telegram-setup
```

```Shell
# 在 tmux 会话中，运行脚本一次以生成 Telegram 会话文件
cd /home/ec2-user/mysta_scripts
source venv/bin/activate
python setup.py setup_prod.yaml
```

完成后，按 `Ctrl+B` 然后按 `D` 分离 tmux 会话（保持其运行

```Shell
# 重新连接到该会话
tmux attach -t telegram-setup
```

### 设置自动运行

1. 创建 systemd 服务文件：

   ```bash
   sudo tee /etc/systemd/system/telegram-sync.service > /dev/null << 'EOF'
   [Unit]
   Description=Telegram Sync Service
   After=network.target

   [Service]
   Type=simple
   User=ec2-user
   WorkingDirectory=/home/ec2-user/mysta_scripts
   ExecStart=/usr/bin/python3 /home/ec2-user/mysta_scripts/setup.py setup_prod.yaml --scheduled
   Environment="AUTOMATED_RUN=true"
   Environment="PYTHONPATH=/home/ec2-user/.local/lib/python3.7/site-packages:/usr/local/lib/python3.7/site-packages"
   Restart=on-failure
   RestartSec=30s
   StandardOutput=append:/home/ec2-user/telegram-sync.log
   StandardError=append:/home/ec2-user/telegram-sync-error.log

   [Install]
   WantedBy=multi-user.target
   EOF
   ```

2. 创建定时器文件：

   ```bash
   sudo tee /etc/systemd/system/telegram-sync.timer > /dev/null << 'EOF'
   [Unit]
   Description=Run Telegram Sync every 5 minutes

   [Timer]
   OnBootSec=1min
   OnUnitActiveSec=5min
   AccuracySec=1s

   [Install]
   WantedBy=timers.target
   EOF
   ```

3. 启用并启动服务：
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable telegram-sync.timer
   sudo systemctl start telegram-sync.timer
   ```

### 检查服务状态

```bash
# 检查定时器状态
sudo systemctl status telegram-sync.timer

# 检查服务状态
sudo systemctl status telegram-sync.service

# 查看日志
tail -f /home/ec2-user/telegram-sync.log
tail -f /home/ec2-user/telegram-sync-error.log
```

## 5. 故障排除

### 会话验证问题

如果 Telegram 会话失效，需要重新验证：

```bash
# 停止服务
sudo systemctl stop telegram-sync.timer
sudo systemctl stop telegram-sync.service

# 删除旧会话
rm -f /home/ec2-user/mysta_scripts/telegram_session_*

# 重新验证
cd /home/ec2-user/mysta_scripts
tmux attach -t telegram-setup

# 如果需要新会话
tmux kill-session -t telegram-setup
tmux new -s telegram-setup
python3 setup.py setup_prod.yaml

# 重启服务
sudo systemctl start telegram-sync.timer
```

### 依赖问题

如果遇到模块导入错误：

```bash
# 全局安装依赖
sudo pip3 install telethon pyyaml requests boto3
```

### 权限问题

确保脚本和目录有正确的权限：

```bash
sudo chown -R ec2-user:ec2-user /home/ec2-user/mysta_scripts
chmod +x /home/ec2-user/mysta_scripts/setup.py
```

## 6. 维护建议

1. 定期备份会话文件

   ```bash
   mkdir -p /home/ec2-user/backups
   cp /home/ec2-user/mysta_scripts/telegram_session_* /home/ec2-user/backups/
   ```

2. 设置日志轮转

   ```bash
   sudo tee /etc/logrotate.d/telegram-sync > /dev/null << 'EOF'
   /home/ec2-user/telegram-sync.log /home/ec2-user/telegram-sync-error.log {
       daily
       rotate 7
       compress
       missingok
       notifempty
   }
   EOF
   ```

3. 创建自动恢复脚本

   ```bash
   # 创建监控脚本
   tee /home/ec2-user/monitor-telegram.sh > /dev/null << 'EOF'
   #!/bin/bash
   if ! systemctl is-active --quiet telegram-sync.service; then
     sudo systemctl restart telegram-sync.service
     echo "Telegram sync service restarted at $(date)" >> /home/ec2-user/monitor.log
   fi
   EOF

   # 使脚本可执行
   chmod +x /home/ec2-user/monitor-telegram.sh

   # 添加到 crontab
   (crontab -l 2>/dev/null; echo "*/15 * * * * /home/ec2-user/monitor-telegram.sh") | crontab -
   ```
