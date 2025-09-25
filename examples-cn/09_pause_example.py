import os
import threading
import time

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
)
from openhands.sdk.conversation.state import AgentExecutionStatus
from openhands.sdk.tool import ToolSpec, register_tool
from openhands.tools.execute_bash import BashTool
from openhands.tools.str_replace_editor import FileEditorTool


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
register_tool("BashTool", BashTool)
register_tool("FileEditorTool", FileEditorTool)
tools = [
    ToolSpec(name="BashTool", params={"working_dir": os.getcwd()}),
    ToolSpec(name="FileEditorTool"),
]

# Agent
agent = Agent(llm=llm, tools=tools)
conversation = Conversation(agent)


print("简单的暂停示例 —— 按 Ctrl+C 进行暂停")

# 发送一条消息以启动对话
conversation.send_message("不断地说 hello world，永远不要停止")

# 在后台线程中启动 Agent
thread = threading.Thread(target=conversation.run)
thread.start()

try:
    # 主循环 —— 类似用户提供的样例脚本
    while (
        conversation.state.agent_status != AgentExecutionStatus.FINISHED
        and conversation.state.agent_status != AgentExecutionStatus.PAUSED
    ):
        # 定期发送鼓励消息
        conversation.send_message("继续加油！你可以做到的！")
        time.sleep(1)
except KeyboardInterrupt:
    conversation.pause()

thread.join()

print(f"Agent 状态：{conversation.state.agent_status}")
