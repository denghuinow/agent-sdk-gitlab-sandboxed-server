import os

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Conversation,
    EventBase,
    LLMConvertibleEvent,
    get_logger,
)
from openhands.sdk.preset.default import get_default_agent


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

agent = get_default_agent(llm=llm, working_dir=os.getcwd())

llm_messages = []


def conversation_callback(event: EventBase):
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


# 创建带有内置卡死检测的对话
conversation = Conversation(
    agent=agent,
    callbacks=[conversation_callback],
    # 默认即为 True，这里显示出来以便示例更清晰
    stuck_detection=True,
)

# 发送会触发卡死检测的任务
conversation.send_message(
    "请执行 5 次 'ls' 命令，每次都使用独立的 action 且不要添加思考，"
    "在第 6 步时退出。"
)

# 运行对话 —— 卡死检测会自动进行
conversation.run()

assert conversation.stuck_detector is not None
final_stuck_check = conversation.stuck_detector.is_stuck()
print(f"最终卡死状态：{final_stuck_check}")

print("=" * 100)
print("对话结束。以下是获取的 LLM 消息：")
for i, message in enumerate(llm_messages):
    print(f"消息 {i}: {str(message)[:200]}")
