"""
本示例演示如何在异步环境中使用 Conversation
（例如在 fastapi 服务器中）。对话在后台线程中运行，
并在主事件循环里执行带有结果的回调。
"""

import asyncio
import os

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
    EventBase,
    LLMConvertibleEvent,
    get_logger,
)
from openhands.sdk.conversation.types import ConversationCallbackType
from openhands.sdk.tool import ToolSpec, register_tool
from openhands.sdk.utils.async_utils import AsyncCallbackWrapper
from openhands.tools.execute_bash import BashTool
from openhands.tools.str_replace_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool


logger = get_logger(__name__)

# 配置 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"
llm = LLM(
    service_id="main-llm",
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://oneapi.wchat.cc/v1",
    api_key=SecretStr(api_key),
)

# 工具
cwd = os.getcwd()
register_tool("BashTool", BashTool)
register_tool("FileEditorTool", FileEditorTool)
register_tool("TaskTrackerTool", TaskTrackerTool)
tools = [
    ToolSpec(name="BashTool", params={"working_dir": cwd}),
    ToolSpec(name="FileEditorTool"),
    ToolSpec(name="TaskTrackerTool", params={"save_dir": cwd}),
]

# Agent
agent = Agent(llm=llm, tools=tools)

llm_messages = []  # 收集原始 LLM 消息


# 回调协程
async def callback_coro(event: EventBase):
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


# 同步地运行对话
def run_conversation(callback: ConversationCallbackType):
    conversation = Conversation(agent=agent, callbacks=[callback])

    conversation.send_message(
        "你好！请创建一个名为 hello.py 的 Python 文件，"
        "里面打印 'Hello, World!'，并使用任务跟踪器规划步骤。"
    )
    conversation.run()

    conversation.send_message("太好了！现在删除那个文件。")
    conversation.run()


async def main():
    loop = asyncio.get_running_loop()

    # 创建回调对象
    callback = AsyncCallbackWrapper(callback_coro, loop)

    # 在后台线程中运行对话并等待完成…
    await loop.run_in_executor(None, run_conversation, callback)

    print("=" * 100)
    print("对话结束。以下是获取的 LLM 消息：")
    for i, message in enumerate(llm_messages):
        print(f"消息 {i}: {str(message)[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
