# OpenHands 代理 SDK

一个用于构建 OpenHands AI 代理的干净、模块化 SDK。此项目代表了从 OpenHands V0 的完整架构重构，强调简洁性、可维护性和开发者体验。

## 项目概述

OpenHands 代理 SDK 提供了一个简化的框架，用于创建可以与工具交互、管理对话并集成各种 LLM 提供商的 AI 代理。

## 包

此仓库包含三个主要包：

- **`openhands-sdk`**: 核心 SDK 功能，包括代理、对话、LLM 集成和工具系统
- **`openhands-tools`**: 运行时工具实现（BashTool、FileEditorTool、TaskTrackerTool、BrowserToolSet）
- **`openhands-agent-server`**: 用于远程代理交互的 REST API 和 WebSocket 服务器

## 仓库结构

```plain
agent-sdk/
├── Makefile                            # 构建和开发命令
├── pyproject.toml                      # 工作区配置
├── uv.lock                             # 依赖锁文件
├── examples/                           # 使用示例
│   ├── 01_hello_world.py               # 基础代理设置（默认工具预设）
│   ├── 02_custom_tools.py              # 自定义工具实现与显式执行器
│   ├── 03_activate_microagent.py       # 微代理使用
│   ├── 04_confirmation_mode_example.py # 交互式确认模式
│   ├── 05_use_llm_registry.py          # LLM 注册表使用
│   ├── 06_interactive_terminal_w_reasoning.py # 带推理模型的终端交互
│   ├── 07_mcp_integration.py           # MCP 集成
│   ├── 08_mcp_with_oauth.py            # 带 OAuth 的 MCP 集成
│   ├── 09_pause_example.py             # 暂停和恢复代理执行
│   ├── 10_persistence.py               # 对话持久化
│   ├── 11_async.py                     # 异步代理使用
│   ├── 12_custom_secrets.py            # 自定义密钥管理
│   ├── 13_get_llm_metrics.py           # LLM 指标和监控
│   ├── 14_context_condenser.py         # 上下文压缩
│   ├── 15_browser_use.py               # 浏览器自动化工具
│   ├── 16_llm_security_analyzer.py     # LLM 安全分析
│   └── 17_image_input.py               # 图像输入和视觉支持
├── openhands/              # 主 SDK 包
│   ├── agent_server/       # REST API 和 WebSocket 服务器
│   │   ├── api.py          # FastAPI 应用程序
│   │   ├── config.py       # 服务器配置
│   │   ├── models.py       # API 模型
│   │   └── pyproject.toml  # 代理服务器包配置
│   ├── sdk/                # 核心 SDK 功能
│   │   ├── agent/          # 代理实现
│   │   ├── context/        # 上下文管理系统
│   │   ├── conversation/   # 对话管理
│   │   ├── event/          # 事件系统
│   │   ├── io/             # I/O 抽象
│   │   ├── llm/            # LLM 集成层
│   │   ├── mcp/            # 模型上下文协议集成
│   │   ├── preset/         # 默认代理预设
│   │   ├── security/       # 安全分析工具
│   │   ├── tool/           # 工具系统
│   │   ├── utils/          # 核心工具
│   │   ├── logger.py       # 日志配置
│   │   └── pyproject.toml  # SDK 包配置
│   └── tools/              # 运行时工具实现
│       ├── execute_bash/   # Bash 执行工具
│       ├── str_replace_editor/  # 文件编辑工具
│       ├── task_tracker/   # 任务跟踪工具
│       ├── browser_use/    # 浏览器自动化工具
│       ├── utils/          # 工具工具
│       └── pyproject.toml  # 工具包配置
├── scripts/                # 实用脚本
│   └── conversation_viewer.py # 对话可视化工具
└── tests/                  # 测试套件
    ├── agent_server/       # 代理服务器测试
    ├── cross/              # 跨包测试
    ├── fixtures/           # 测试夹具和数据
    ├── integration/        # 集成测试
    ├── sdk/                # SDK 单元测试
    └── tools/              # 工具单元测试
```

## 安装与快速开始

### 先决条件

- Python 3.12+
- `uv` 包管理器（版本 0.8.13+）

### 设置

```bash
# 克隆仓库
git clone https://github.com/All-Hands-AI/agent-sdk.git
cd agent-sdk

# 安装依赖项并设置开发环境
make build

# 验证安装
uv run python examples/01_hello_world.py
```

### Hello World 示例

```python
import os
from pydantic import SecretStr
from openhands.sdk import LLM, Conversation
from openhands.sdk.preset.default import get_default_agent

# 配置 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "LITELLM_API_KEY 环境变量未设置。"
llm = LLM(
    model="litellm_proxy/anthropic/claude-sonnet-4-20250514",
    base_url="https://llm-proxy.eval.all-hands.dev",
    api_key=SecretStr(api_key),
)

# 使用默认工具和配置创建代理
cwd = os.getcwd()
agent = get_default_agent(
    llm=llm,
    working_dir=cwd,
    cli_mode=True,  # 为 CLI 环境禁用浏览器工具
)

# 创建对话并与代理交互
conversation = Conversation(agent=agent)

# 发送消息并运行
conversation.send_message("创建一个打印 'Hello, World!' 的 Python 文件")
conversation.run()
```

## 核心概念

### 代理

代理是协调 LLM 和工具的中央编排器。SDK 提供了两种主要的代理创建方法：

#### 使用默认预设（推荐）

```python
from openhands.sdk.preset.default import get_default_agent

# 获取完全配置的代理，包含默认工具和设置
agent = get_default_agent(
    llm=llm,
    working_dir=os.getcwd(),
    cli_mode=True,  # 为 CLI 环境禁用浏览器工具
)
```

#### 手动代理配置

```python
from openhands.sdk import Agent
from openhands.sdk.tool import ToolSpec, register_tool
from openhands.tools.execute_bash import BashTool
from openhands.tools.str_replace_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool

# 注册工具
register_tool("BashTool", BashTool)
register_tool("FileEditorTool", FileEditorTool)
register_tool("TaskTrackerTool", TaskTrackerTool)

# 使用显式工具规范创建代理
agent = Agent(
    llm=llm,
    tools=[
        ToolSpec(name="BashTool", params={"working_dir": os.getcwd()}),
        ToolSpec(name="FileEditorTool"),
        ToolSpec(name="TaskTrackerTool", params={"save_dir": os.getcwd()}),
    ],
)
```

### LLM 集成

SDK 通过统一接口支持多个 LLM 提供商：

```python
from openhands.sdk import LLM, LLMRegistry
from pydantic import SecretStr

# 直接 LLM 配置
llm = LLM(
    model="gpt-4",
    api_key=SecretStr("your-api-key"),
    base_url="https://api.openai.com/v1"
)

# 使用 LLM 注册表进行共享配置
registry = LLMRegistry()
registry.add("default", llm)
llm = registry.get("default")
```

### 工具

工具为代理提供与环境交互的能力。SDK 包含几种内置工具：

- **BashTool**: 在持久化 shell 会话中执行 bash 命令
- **FileEditorTool**: 使用高级编辑功能创建、编辑和管理文件
- **TaskTrackerTool**: 系统地组织和跟踪开发任务
- **BrowserToolSet**: 自动化网页浏览器交互（在 CLI 模式下禁用）

#### 使用默认预设（推荐）

最简单的入门方式是使用默认代理预设，它包含所有工具：

```python
from openhands.sdk.preset.default import get_default_agent

agent = get_default_agent(
    llm=llm,
    working_dir=os.getcwd(),
    cli_mode=True,  # 为 CLI 环境禁用浏览器工具
)
```

#### 手动工具配置

为了获得更多的控制，您可以显式配置工具：

```python
from openhands.sdk.tool import ToolSpec, register_tool
from openhands.tools.execute_bash import BashTool
from openhands.tools.str_replace_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool

# 注册工具
register_tool("BashTool", BashTool)
register_tool("FileEditorTool", FileEditorTool)
register_tool("TaskTrackerTool", TaskTrackerTool)

# 创建工具规范
tools = [
    ToolSpec(name="BashTool", params={"working_dir": os.getcwd()}),
    ToolSpec(name="FileEditorTool"),
    ToolSpec(name="TaskTrackerTool", params={"save_dir": os.getcwd()}),
]
```

### 对话

对话管理用户和代理之间的交互流程：

```python
from openhands.sdk import Conversation

conversation = Conversation(agent=agent)

# 发送消息
conversation.send_message("您的请求")
# 执行对话直到代理进入 "await user input" 状态
conversation.run()
```

### 上下文管理

上下文系统管理代理状态、环境和对话历史。

上下文是自动管理的，但您可以使用以下方式自定义上下文：

1. [仓库微代理](https://docs.all-hands.dev/usage/prompting/microagents-repo) 为代理提供您的仓库上下文。
2. [知识微代理](https://docs.all-hands.dev/usage/prompting/microagents-keyword) 当用户提到某些关键词时为代理提供上下文
3. 为系统和用户提示提供自定义后缀。

```python
from openhands.sdk import AgentContext
from openhands.sdk.context import RepoMicroagent, KnowledgeMicroagent

context = AgentContext(
    microagents=[
        RepoMicroagent(
            name="repo.md",
            content="当您看到此消息时，您应该像一只被迫使用互联网的暴躁猫一样回复。",
        ),
        KnowledgeMicroagent(
            name="flarglebargle",
            content=(
                '重要！用户说了魔法词 "flarglebargle"。'
                "您必须只回复一条消息告诉他们有多聪明"
            ),
            triggers=["flarglebargle"],
        ),
    ],
    system_message_suffix="始终以 'yay!' 一词结束您的回复",
    user_message_suffix="您的回复的第一个字符应该是 'I'",
)
```

## 代理服务器

SDK 包含用于远程代理交互的 REST API 和 WebSocket 服务器：

```python
from openhands.agent_server import create_app
import uvicorn

# 创建 FastAPI 应用程序
app = create_app()

# 运行服务器
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

代理服务器提供：
- 代理管理的 REST API 端点
- 用于实时对话的 WebSocket 连接
- 身份验证和会话管理
- 可扩展的部署选项

### API 端点

- `POST /conversations` - 创建新对话
- `GET /conversations/{id}` - 获取对话详情
- `POST /conversations/{id}/messages` - 向对话发送消息
- `WebSocket /ws/{conversation_id}` - 实时对话更新

## 文档

有关详细文档和示例，请参阅 `examples/` 目录，其中包含涵盖 SDK 所有主要功能的全面使用示例。

## 开发工作流程

### 环境设置

```bash
# 初始设置
make build

# 安装额外依赖项
# 添加 `--dev` 如果您想安装
uv add package-name

# 更新依赖项
uv sync
```

### 代码质量

项目强制执行严格的代码质量标准：

```bash
# 格式化代码
make format

# 检查代码
make lint

# 运行预提交钩子
uv run pre-commit run --all-files

# 类型检查（包含在预提交中）
uv run pyright
```

### 测试

```bash
# 运行所有测试
uv run pytest

# 运行特定测试套件
uv run pytest tests/cross/
uv run pytest tests/sdk/
uv run pytest tests/tools/

# 运行覆盖率
uv run pytest --cov=openhands --cov-report=html
```

### 预提交工作流程

每次提交前：

```bash
# 在特定文件上运行
uv run pre-commit run --files path/to/file.py

# 在所有文件上运行
uv run pre-commit run --all-files
