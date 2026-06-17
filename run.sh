#!/bin/bash
# K38 足球监控网站 — 一键启动脚本
set -e

cd "$(dirname "$0")"

echo "📦 安装依赖..."
pip3 install -q Flask 2>/dev/null || pip install -q Flask

echo "🗄️  初始化数据库..."
python3 -c "from models import init_db; init_db(); print('✅ OK')"

echo "🌱 加载种子数据..."
python3 -c "
from collector import load_seed_data
n = load_seed_data()
print(f'✅ 已加载 {n} 场比赛')
"

echo ""
echo "============================================"
echo "  🚀 K38 足球监控已就绪！"
echo "  访问: http://127.0.0.1:6789"
echo "  按 Ctrl+C 停止"
echo "============================================"
echo ""

python3 app.py
