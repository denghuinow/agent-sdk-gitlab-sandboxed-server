"""OpenHands Agent SDK —— LLM 安全分析器示例（简化版）

本示例展示如何使用 LLMSecurityAnalyzer 在执行操作前自动评估
安全风险。
"""

import os
import signal
import uuid
from collections.abc import Callable

from pydantic import SecretStr

from openhands.sdk import LLM, Agent, BaseConversation, Conversation, LocalFileStore
from openhands.sdk.conversation.state import AgentExecutionStatus
from openhands.sdk.event.utils import get_unmatched_actions
from openhands.sdk.security.confirmation_policy import ConfirmRisky
from openhands.sdk.security.llm_analyzer import LLMSecurityAnalyzer
from openhands.sdk.tool import ToolSpec, register_tool
from openhands.tools.execute_bash import BashTool
from openhands.tools.str_replace_editor import FileEditorTool


# 保持 Ctrl+C 时干净退出，无额外堆栈跟踪噪声
signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))


def _print_blocked_actions(pending_actions) -> None:
    print(f"\n🔒 安全分析器拦截了 {len(pending_actions)} 个高风险操作：")
    for i, action in enumerate(pending_actions, start=1):
        snippet = str(action.action)[:100].replace("\n", " ")
        print(f"  {i}. {action.tool_name}: {snippet}...")


def confirm_high_risk_in_console(pending_actions) -> bool:
    """
    返回 True 代表批准，False 代表拒绝。
    行为与原示例一致：遇到 EOF/KeyboardInterrupt 时默认拒绝。
    """
    _print_blocked_actions(pending_actions)
    while True:
        try:
            ans = (
                input(
                    "\n这些操作被标记为高风险。仍要执行它们吗？(yes/no): "
                )
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            print("\n❌ 未收到输入；默认拒绝。")
            return False

        if ans in ("yes", "y"):
            print("✅ 已批准 —— 正在执行高风险操作…")
            return True
        if ans in ("no", "n"):
            print("❌ 已拒绝 —— 跳过高风险操作…")
            return False
        print("请输入 'yes' 或 'no'。")


def run_until_finished_with_security(
    conversation: BaseConversation, confirmer: Callable[[list], bool]
) -> None:
    """
    驱动对话直到状态变为 FINISHED。
    - 如果状态为 WAITING_FOR_CONFIRMATION：调用 confirmer。
        * 当确认通过时：保持原示例行为，将 agent_status 设为 IDLE。
        * 当被拒绝时：调用 conversation.reject_pending_actions(... )。
    - 如果处于等待状态但没有待确认的操作：抛出警告并设为 IDLE（与原示例一致）。
    """
    while conversation.state.agent_status != AgentExecutionStatus.FINISHED:
        if (
            conversation.state.agent_status
            == AgentExecutionStatus.WAITING_FOR_CONFIRMATION
        ):
            pending = get_unmatched_actions(conversation.state.events)
            if not pending:
                raise RuntimeError(
                    "⚠️ Agent 正在等待确认，但未找到任何待处理操作。这不应该发生。"
                )
            if not confirmer(pending):
                conversation.reject_pending_actions("用户拒绝了高风险操作")
                continue

        print("▶️  正在运行 conversation.run()…")
        conversation.run()


# 配置 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"
llm = LLM(
    service_id="security-analyzer",
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

# 带安全分析器的 Agent
security_analyzer = LLMSecurityAnalyzer()
agent = Agent(llm=llm, tools=tools, security_analyzer=security_analyzer)

# 带持久化文件存储的对话
conversation_id = uuid.uuid4()
file_store = LocalFileStore(f"./.conversations/{conversation_id}")
conversation = Conversation(
    agent=agent, conversation_id=conversation_id, persist_filestore=file_store
)
conversation.set_confirmation_policy(ConfirmRisky())

print("\n1) 安全命令（低风险 —— 应自动执行）…")
conversation.send_message("列出当前目录下的文件")
conversation.run()

print("\n2) 可能存在风险的命令（可能需要确认）…")
conversation.send_message(
    "请执行 echo 'hello world' —— 请将此标记为高风险操作"
)
run_until_finished_with_security(conversation, confirm_high_risk_in_console)
