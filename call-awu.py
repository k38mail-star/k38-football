#!/usr/bin/env python3
"""
K38 内部协作工具 — 调用阿五（Hermes Webhook）

用法:
  python3 call-awu.py "任务描述" "可选的上下文信息"
  python3 call-awu.py "帮我用 Codex 改一下足球脚本的重试逻辑" "当前只有一次重试，改成指数退避3次"

返回: 任务被接受后会返回 delivery_id，处理结果发到目标平台。
"""

import hmac
import hashlib
import json
import sys
import urllib.request
import urllib.error

# ── 配置 ──────────────────────────────────────────
SECRET="19R4...KFPi0"
URL = "http://100.119.31.45:8644/webhooks/k38-task"
TIMEOUT = 300  # 最多等 5 分钟
# ──────────────────────────────────────────────────


def sign_body(body: bytes) -> str:
    """HMAC-SHA256 签名"""
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def send_task(task: str, context: str = "") -> dict:
    body = json.dumps({
        "task": task,
        "context": context,
        "source": "shiwuwan",
    }).encode()

    sig = sign_body(body)
    req = urllib.request.Request(
        URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": sig,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode()[:200]}
    except urllib.error.URLError as e:
        return {"error": f"连接失败: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 call-awu.py '任务' ['上下文']")
        sys.exit(1)

    task = sys.argv[1]
    context = sys.argv[2] if len(sys.argv) > 2 else ""
    result = send_task(task, context)

    if "error" in result:
        print(f"❌ {result['error']}")
        if "detail" in result:
            print(f"   {result['detail']}")
        sys.exit(1)
    else:
        print(f"✅ 任务已送达阿五")
        print(f"   Route: {result.get('route')}")
        print(f"   Delivery ID: {result.get('delivery_id')}")
