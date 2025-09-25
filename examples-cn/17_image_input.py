"""OpenHands Agent SDK —— 图像输入示例。

本脚本与 ``examples/01_hello_world.py`` 的基础设置相同，
但通过向 Agent 发送图像以及文本指令来添加视觉能力。
"""

import os

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
    EventBase,
    ImageContent,
    LLMConvertibleEvent,
    Message,
    TextContent,
    get_logger,
)
from openhands.sdk.tool.registry import register_tool
from openhands.sdk.tool.spec import ToolSpec
from openhands.tools.execute_bash import BashTool
from openhands.tools.str_replace_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool


logger = get_logger(__name__)

# 配置具备视觉能力的 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"
llm = LLM(
    service_id="vision-llm",
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://oneapi.wchat.cc/v1",
    api_key=SecretStr(api_key),
)

cwd = os.getcwd()

register_tool("BashTool", BashTool)
register_tool("FileEditorTool", FileEditorTool)
register_tool("TaskTrackerTool", TaskTrackerTool)

agent = Agent(
    llm=llm,
    tools=[
        ToolSpec(name="BashTool", params={"working_dir": cwd}),
        ToolSpec(name="FileEditorTool"),
        ToolSpec(name="TaskTrackerTool", params={"save_dir": cwd}),
    ],
)

llm_messages = []  # 收集原始 LLM 消息以便查看


def conversation_callback(event: EventBase) -> None:
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


conversation = Conversation(agent=agent, callbacks=[conversation_callback])

IMAGE_URL = (
    "https://github.com/All-Hands-AI/OpenHands/raw/main/docs/static/img/logo.png"
)

conversation.send_message(
    Message(
        role="user",
        vision_enabled=True,
        content=[
            TextContent(
                text=(
                    "请观察这张图片并描述你看到的关键元素。"
                    "用一段简短的文字总结，并给出一句醒目的标题。"
                )
            ),
            ImageContent(image_urls=[IMAGE_URL]),
        ],
    )
)
conversation.run()

conversation.send_message(
    "太好了！请将你的描述和标题保存到 image_report.md。"
)
conversation.run()


print("=" * 100)
print("对话结束。以下是获取的 LLM 消息：")
for i, message in enumerate(llm_messages):
    print(f"消息 {i}: {str(message)[:200]}")
