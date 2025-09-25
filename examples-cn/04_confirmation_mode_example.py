"""OpenHands Agent SDK —— 确认模式示例"""

import os
import signal
from collections.abc import Callable

from pydantic import SecretStr

from openhands.sdk import LLM, BaseConversation, Conversation
from openhands.sdk.conversation.state import AgentExecutionStatus
from openhands.sdk.event.utils import get_unmatched_actions
from openhands.sdk.preset.default import get_default_agent
from openhands.sdk.security.confirmation_policy import AlwaysConfirm, NeverConfirm


# 让 Ctrl+C 干净退出，而不是输出堆栈跟踪
signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))


def _print_action_preview(pending_actions) -> None:
    print(f"\n🔍 Agent 创建了 {len(pending_actions)} 个待确认的操作：")
    for i, action in enumerate(pending_actions, start=1):
        snippet = str(action.action)[:100].replace("\n", " ")
        print(f"  {i}. {action.tool_name}: {snippet}...")


def confirm_in_console(pending_actions) -> bool:
    """
    返回 True 则批准执行，返回 False 则拒绝。
    遇到 EOF/KeyboardInterrupt 时默认拒绝（与原始行为一致）。
    """
    _print_action_preview(pending_actions)
    while True:
        try:
            ans = (
                input("\n是否执行这些操作？(yes/no): ")
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            print("\n❌ 没有收到输入；默认拒绝。")
            return False

        if ans in ("yes", "y"):
            print("✅ 已批准 —— 正在执行操作…")
            return True
        if ans in ("no", "n"):
            print("❌ 已拒绝 —— 跳过这些操作…")
            return False
        print("请输入 'yes' 或 'no'。")


def run_until_finished(conversation: BaseConversation, confirmer: Callable) -> None:
    """
    驱动对话直到状态变为 FINISHED。
    若状态为 WAITING_FOR_CONFIRMATION，则调用 confirmer；
    如果被拒绝，则执行 reject_pending_actions()。
    若 Agent 处于等待状态但没有待确认操作，将保留原错误。
    """
    while conversation.state.agent_status != AgentExecutionStatus.FINISHED:
        if (
            conversation.state.agent_status
            == AgentExecutionStatus.WAITING_FOR_CONFIRMATION
        ):
            pending = get_unmatched_actions(conversation.state.events)
            if not pending:
                raise RuntimeError(
                    "⚠️ Agent 正在等待确认，但未找到任何待确认操作。这不应该发生。"
                )
            if not confirmer(pending):
                conversation.reject_pending_actions("用户拒绝了这些操作")
                # 让 Agent 生成新的步骤或结束
                continue

        print("▶️  正在调用 conversation.run()…")
        conversation.run()


# 配置 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"
llm = LLM(
    service_id="main-llm",
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://oneapi.wchat.cc/v1",
    api_key=SecretStr(api_key),
)

agent = get_default_agent(llm=llm, working_dir=os.getcwd())
conversation = Conversation(agent=agent)

# 1) 开启确认模式
conversation.set_confirmation_policy(AlwaysConfirm())
print("\n1) 可能会创建操作的命令…")
conversation.send_message("请使用 ls -la 列出当前目录下的文件")
run_until_finished(conversation, confirm_in_console)

# 2) 用户可能选择拒绝的命令
print("\n2) 用户可能拒绝的命令…")
conversation.send_message("请创建一个名为 'dangerous_file.txt' 的文件")
run_until_finished(conversation, confirm_in_console)

# 3) 简单问候（预计不会产生操作）
print("\n3) 简单问候（不期待产生操作）…")
conversation.send_message("只需要向我问好即可")
run_until_finished(conversation, confirm_in_console)

# 4) 关闭确认模式，直接执行命令
print("\n4) 关闭确认模式并执行命令…")
conversation.set_confirmation_policy(NeverConfirm())
conversation.send_message("请输出 'Hello from confirmation mode example!'")
conversation.run()

conversation.send_message(
    "请删除在本次对话中创建的任何文件。"
)
conversation.run()

print("\n=== 示例完成 ===")
print("要点：")
print(
    "- conversation.run() 会创建操作；确认模式会让 agent_status=WAITING_FOR_CONFIRMATION"
)
print("- 用户确认通过一个可复用的函数处理")
print("- 拒绝将调用 conversation.reject_pending_actions()，循环会继续")
print("- 简单回复在没有操作时照常工作")
print("- 通过 conversation.set_confirmation_policy() 切换确认策略")
