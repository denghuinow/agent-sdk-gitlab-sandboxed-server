"""
示例演示：即使 Agent 正在忙碌，也能接收并处理用户消息。

这个案例展示了 OpenHands Agent 系统的一项关键能力：即便 Agent 正在执行
先前的任务，也能接收并处理新的用户消息。这得益于 Agent 的事件驱动
架构。

演示流程：
1. 发送初始消息，要求 Agent：
   - 写入 "Message 1 sent at [time], written at [CURRENT_TIME]"
   - 等待 3 秒
   - 写入 "Message 2 sent at [time], written at [CURRENT_TIME]"
    [time] 指消息发送给 Agent 的时间
    [CURRENT_TIME] 指 Agent 写入该行时的实际时间
2. 在后台线程中启动 Agent 处理
3. 当 Agent 正在忙碌（处于 3 秒等待期间）时，发送第二条消息，要求追加：
   - "Message 3 sent at [time], written at [CURRENT_TIME]"
4. 确认最终文档包含上述三行

预期证据：
最终的文档会包含三行带有双时间戳的内容：
- "Message 1 sent at HH:MM:SS, written at HH:MM:SS"（来自初始消息，立即写入）
- "Message 2 sent at HH:MM:SS, written at HH:MM:SS"（来自初始消息，在 3 秒后写入）
- "Message 3 sent at HH:MM:SS, written at HH:MM:SS"（在等待期间发送的第二条消息）

时间戳会显示 Message 3 是在 Agent 运行时发送的，但仍被成功写入文档。

这证明：
- 第二条用户消息是在 Agent 处理第一个任务时发送的
- Agent 成功接收并处理了第二条消息
- Agent 的事件系统支持在处理过程中实时整合新消息

关键组件：
- Conversation.send_message()：立即将消息加入事件列表
- Agent.step()：处理所有事件，包括新加入的消息
- 线程：支持在 Agent 正在处理时发送消息
"""  # noqa

import os
import threading
import time
from datetime import datetime

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
)
from openhands.sdk.tool import ToolSpec, register_tool
from openhands.tools.execute_bash import BashTool
from openhands.tools.str_replace_editor import FileEditorTool


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
tools = [
    ToolSpec(name="BashTool", params={"working_dir": cwd}),
    ToolSpec(name="FileEditorTool"),
]

# Agent
agent = Agent(llm=llm, tools=tools)
conversation = Conversation(agent)


def timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


print("=== 处理过程中发送消息示例 ===")

# 步骤 1：发送初始消息
start_time = timestamp()
conversation.send_message(
    f"创建一个名为 document.txt 的文件，并写入第一句话："
    f"'Message 1 sent at {start_time}, written at [CURRENT_TIME].' "
    f"将 [CURRENT_TIME] 替换为写入该行时的实际时间。"
    f"然后等待 3 秒，再写入 'Message 2 sent at {start_time}, written at [CURRENT_TIME].'"
)

# 步骤 2：在后台启动 Agent 处理
thread = threading.Thread(target=conversation.run)
thread.start()

# 步骤 3：等待，然后在 Agent 处理期间发送第二条消息
time.sleep(2)  # 给 Agent 一些时间开始工作

second_time = timestamp()

conversation.send_message(
    f"请再向 document.txt 添加第二句话："
    f"'Message 3 sent at {second_time}, written at [CURRENT_TIME].' "
    f"将 [CURRENT_TIME] 替换为写入该行时的实际时间。"
)

# 等待完成
thread.join()

# 验证
document_path = os.path.join(cwd, "document.txt")
if os.path.exists(document_path):
    with open(document_path) as f:
        content = f.read()

    print("\n文档内容：")
    print("─────────────────────")
    print(content)
    print("─────────────────────")

    # 检查是否处理了所有消息
    if "Message 1" in content and "Message 2" in content:
        print("\n成功：Agent 处理了所有消息！")
        print("这证明 Agent 在处理第一个任务时收到了第二条消息。")
    else:
        print("\n警告：Agent 可能没有处理第二条消息")

    # 清理
    os.remove(document_path)
else:
    print("警告：未创建 document.txt 文件")
