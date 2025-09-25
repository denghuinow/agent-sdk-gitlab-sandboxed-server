"""
演示如何让 Agent Server 与另一个服务器配合使用，
后者作为示例来接收 webhook 回调。

可在此处发起对话：
http://localhost:8000/docs#/default/start_conversation_api_conversations__post

当前的 webhook 请求可在此查看：
http://localhost:8001/requests
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


webhook_example_client_api = FastAPI(title="示例日志 Webhook 客户端")
requests = []


@webhook_example_client_api.get("/requests")
async def display_requests():
    """展示已发送到示例 webhook 客户端的请求"""
    return JSONResponse(requests)


@webhook_example_client_api.delete("/requests")
async def clear_logs() -> bool:
    """清空已发送到示例 webhook 客户端的请求"""
    global requests
    requests = []
    return True


@webhook_example_client_api.post("/{full_path:path}")
async def invoke_webhook(full_path: str, request: Request):
    """调用 webhook"""
    body = await request.json()
    requests.append(
        {
            "path": full_path,
            "body": body,
        }
    )


def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # 启动 Agent Server
    port = args.port
    env = {**os.environ}
    env["OPENHANDS_AGENT_SERVER_CONFIG_PATH"] = "config.json"
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "openhands.agent_server.api:api",
            "--host",
            args.host,
            "--port",
            str(port),
        ],
        cwd=str(Path(__file__).parent),
        env=env,
    )

    # 启动 webhook 客户端
    uvicorn.run(webhook_example_client_api, host=args.host, port=port + 1)


if __name__ == "__main__":
    main()
