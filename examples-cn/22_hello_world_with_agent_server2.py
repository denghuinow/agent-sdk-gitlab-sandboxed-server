import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from pydantic import SecretStr

from openhands.sdk import LLM, Conversation, get_logger
from openhands.sdk.conversation.impl.remote_conversation import RemoteConversation
from openhands.sdk.preset.default import get_default_agent


logger = get_logger(__name__)

api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"

llm = LLM(
    service_id="main-llm",
    model="openai/Qwen3-Next-80B-A3B-Instruct-FP8",
    base_url="https://oneapi.wchat.cc/v1",
    api_key=SecretStr(api_key),
)

# 使用托管的 API 服务器

# 创建 Agent
agent = get_default_agent(
    llm=llm,
    working_dir=str(Path.cwd()),
    cli_mode=True,  # 为简洁起见禁用浏览器工具
)
agent = agent.model_copy(update={"mcp_config": {}, "security_analyzer": None})
# 定义回调以测试 WebSocket 功能
received_events = []
event_tracker = {"last_event_time": time.time()}


def event_callback(event):
    """捕获事件以便测试。"""
    event_type = type(event).__name__
    logger.info(f"🔔 回调收到事件：{event_type}\n{event}")
    received_events.append(event)
    event_tracker["last_event_time"] = time.time()


# 创建带回调的 RemoteConversation
conversation = Conversation(
    agent=agent,
    host="http://localhost:8000",
    callbacks=[event_callback],
    visualize=True,
)
assert isinstance(conversation, RemoteConversation)

try:
    logger.info(f"\n📋 对话 ID：{conversation.state.id}")

    # 发送第一条消息并运行
    logger.info("📝 正在发送第一条消息…")
    conversation.send_message(
        "阅读当前仓库，并将关于该项目的 3 个事实写入 FACTS.txt。"
    )

    logger.info("🚀 正在运行对话…")
    conversation.run()

    logger.info("✅ 第一个任务完成！")
    logger.info(f"Agent 状态：{conversation.state.agent_status}")

    # 等待事件停止（2 秒内无事件）
    logger.info("⏳ 正在等待事件停止…")
    while time.time() - event_tracker["last_event_time"] < 2.0:
        time.sleep(0.1)
    logger.info("✅ 事件已停止")

    logger.info("🚀 再次运行对话…")
    conversation.send_message("太好了！现在删除那个文件。")
    conversation.run()
    logger.info("✅ 第二个任务完成！")

    # 演示 state.events 功能
    logger.info("\n" + "=" * 50)
    logger.info("📊 展示状态事件 API")
    logger.info("=" * 50)

    # 统计事件总数
    total_events = len(conversation.state.events)
    logger.info(f"📈 对话中的事件总数：{total_events}")

    # 获取最近 5 个事件
    logger.info("\n🔍 获取最近 5 个事件…")
    all_events = conversation.state.events
    recent_events = all_events[-5:] if len(all_events) >= 5 else all_events

    for i, event in enumerate(recent_events, 1):
        event_type = type(event).__name__
        timestamp = getattr(event, "timestamp", "Unknown")
        logger.info(f"  {i}. {event_type} at {timestamp}")

    # 查看事件类型
    logger.info("\n🔍 事件类型如下：")
    event_types = set()
    for event in recent_events:
        event_type = type(event).__name__
        event_types.add(event_type)
    for event_type in sorted(event_types):
        logger.info(f"  - {event_type}")
finally:
    # 清理
    print("\n🧹 正在清理对话…")
    conversation.close()
