#!/bin/bash
# K38 Football Auto Deploy
# 用法: bash deploy.sh
set -e

echo "🚀 部署 K38 Football..."

# 同步到 ECS
rsync -avz --exclude='.git' --exclude='*.db' --exclude='__pycache__' \
  . root@47.86.98.87:/opt/k38-football/

# 清理缓存 + 重启
ssh root@47.86.98.87 "
  rm -rf /opt/k38-football/__pycache__
  systemctl restart k38-football
  sleep 2
  echo '✅ 部署完成'
  curl -s --max-time 3 http://127.0.0.1:6789/ | head -c 50
"
