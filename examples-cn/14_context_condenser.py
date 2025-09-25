"""
为了在长时间运行的对话中管理上下文，Agent 可以使用上下文压缩器，
使对话历史保持在指定的大小限制内。本示例演示如何使用
`LLMSummarizingCondenser`，当历史记录超过设定阈值时，它会自动对较旧的
对话部分进行总结。
"""

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
from openhands.sdk.context.condenser import LLMSummarizingCondenser
from openhands.sdk.io.local import LocalFileStore
from openhands.sdk.tool import ToolSpec, register_tool
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
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
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

# 创建一个用于管理上下文的压缩器。当历史记录超过 max_size 时，它会自动截断
# 对话历史，并用 LLM 生成的摘要替换被移除的事件。该压缩器在对话历史超过
# 十个事件时触发，同时始终保留最开始的两个事件（系统提示、初始用户消息），
# 以确保关键信息不会丢失。
condenser = LLMSummarizingCondenser(
    llm=llm.model_copy(update={"service_id": "condenser"}), max_size=10, keep_first=2
)

# 带压缩器的 Agent
agent = Agent(llm=llm, tools=tools, condenser=condenser)

llm_messages = []  # 收集原始 LLM 消息


def conversation_callback(event: EventBase):
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


file_store = LocalFileStore("./.conversations")

conversation = Conversation(
    agent=agent, callbacks=[conversation_callback], persist_filestore=file_store
)

# 发送多条消息以演示压缩效果
print("发送多条消息以演示 LLM Summarizing Condenser…")

conversation.send_message(
    "你好！请创建一个名为 math_utils.py 的 Python 文件，"
    "其中包含加、减、乘、除这些基础算术函数。"
)
conversation.run()

conversation.send_message("很好！现在添加一个计算阶乘的函数。")
conversation.run()

conversation.send_message("再添加一个用于判断数字是否为质数的函数。")
conversation.run()

conversation.send_message("再写一个计算两个数最大公约数（GCD）的函数。")
conversation.run()

conversation.send_message("现在创建一个测试文件，验证这些函数都能正常工作。")
conversation.run()


print("=" * 100)
print("对话结束。以下是获取的 LLM 消息：")
for i, message in enumerate(llm_messages):
    print(f"消息 {i}: {str(message)[:200]}")

# 对话持久化
print("正在序列化对话…")

del conversation

# 反序列化对话
print("正在反序列化对话…")
conversation = Conversation(
    agent=agent, callbacks=[conversation_callback], persist_filestore=file_store
)

print("向反序列化后的对话发送消息…")
conversation.send_message("最后，把这两个文件都删除。")
conversation.run()


print("=" * 100)
print("带有 LLM Summarizing Condenser 的对话已结束。")
print(f"共收集到 {len(llm_messages)} 条 LLM 消息")
print("\n当对话长度超过设定的 max_size 阈值时，压缩器会自动总结较早的历史。")
print("这样既能管理上下文长度，也能保留重要信息。")
