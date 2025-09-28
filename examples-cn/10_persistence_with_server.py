import os
import uuid

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
    EventBase,
    LLMConvertibleEvent,
    LocalFileStore,
    get_logger,
)
from openhands.sdk.tool import ToolSpec, register_tool
from openhands.tools.execute_bash import BashTool
from openhands.tools.str_replace_editor import FileEditorTool


logger = get_logger(__name__)

# 配置 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"
llm = LLM(
    service_id="main-llm",
    model="openai/qwen3-next-80b-a3b-instruct",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=SecretStr(api_key),
)

# 工具
cwd = os.getcwd()
register_tool("BashTool", BashTool)
register_tool("FileEditorTool", FileEditorTool)
tool_specs = [
    ToolSpec(name="BashTool", params={"working_dir": cwd}),
    ToolSpec(name="FileEditorTool"),
]

# 添加 MCP 工具
mcp_config = {
    "mcpServers": {
        "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
    }
}
# Agent
agent = Agent(llm=llm, tools=tool_specs)

llm_messages = []  # 收集原始 LLM 消息


def conversation_callback(event: EventBase):
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


conversation_id = None
# file_store = LocalFileStore(f"./.conversations/{conversation_id}")

conversation = Conversation(
    agent=agent,
    callbacks=[conversation_callback],
    host="http://localhost:8000",
)
conversation_id = conversation.state.id
conversation.send_message(
    "阅读 https://github.com/All-Hands-AI/OpenHands-Server，"
    "然后将关于该项目的 3 个事实写入 FACTS.txt。"
)
conversation.run()

conversation.send_message("干得好！现在删除那个文件。")
conversation.run()

print("=" * 100)
print("对话结束。以下是获取的 LLM 消息：")
for i, message in enumerate(llm_messages):
    print(f"消息 {i}: {str(message)[:200]}")

# 对话持久化
print("正在序列化对话…")

del conversation
# TODO 等待用户键入确认
input("按回车键继续…")

# 反序列化对话
print("正在反序列化对话…")
conversation = Conversation(
    agent=agent,
    callbacks=[conversation_callback],
    host="http://localhost:8000",
    conversation_id=conversation_id,
)

print("向反序列化后的对话发送消息…")
conversation.send_message("嗨，你创建了什么？返回一个 agent finish action")
conversation.run()
