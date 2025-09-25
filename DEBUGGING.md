# VSCode 调试 OpenHands Agent Server

## 调试配置

VSCode调试配置已创建在 `.vscode/launch.json` 文件中，包含以下配置：

### 1. Debug OpenHands Agent Server
- 启动服务器，启用自动重载模式
- 参数：`--host localhost --port 8000 --reload`
- 环境变量：`DEBUG=true`, `LOG_LEVEL=DEBUG`
- 适合开发时的实时调试

### 2. Debug OpenHands Agent Server (No Reload)
- 启动服务器，不启用自动重载
- 参数：`--host localhost --port 8000`
- 适合需要稳定调试会话的场景

### 3. Debug OpenHands Agent Server with Config File
- 启动服务器并指定配置文件
- 参数：`--host localhost --port 8000`
- 从 `workspace/openhands_agent_server_config.json` 加载配置

### 4. Run OpenHands Agent Server Tests
- 运行agent server的测试套件
- 包含详细的测试输出

## 如何使用

### 启动调试
1. 打开VSCode
2. 按 `Ctrl+Shift+P` 打开命令面板
3. 输入 "Debug: Select and Start Debugging" 或按 `F5`
4. 选择所需的调试配置

或者：
1. 点击左侧调试图标（虫子图标）
2. 在下拉菜单中选择调试配置
3. 点击绿色播放按钮开始调试

### 设置断点
1. 在代码行号左侧点击设置断点
2. 运行调试配置时，程序会在断点处暂停
3. 可以查看变量值、调用栈等调试信息

### 调试技巧
- 使用 `F10` 单步跳过
- 使用 `F11` 单步进入
- 使用 `Shift+F11` 单步跳出
- 使用 `F9` 继续执行到下一个断点

## 调试环境变量

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `DEBUG` | 启用调试模式，显示堆栈跟踪 | `false` |
| `LOG_LEVEL` | 设置日志级别 | `INFO` |
| `LOG_TO_FILE` | 将日志写入文件 | `false` |
| `LOG_JSON` | JSON格式日志输出 | `false` |
| `OPENHANDS_AGENT_SERVER_CONFIG_PATH` | 配置文件路径 | `workspace/openhands_agent_server_config.json` |

## 常用调试路径

### 服务器启动
- 入口文件：`openhands/agent_server/__main__.py`
- 主应用：`openhands/agent_server/api.py`

### 核心服务
- 配置：`openhands/agent_server/config.py`
- 对话服务：`openhands/agent_server/conversation_service.py`
- 事件服务：`openhands/agent_server/event_service.py`

### 路由器
- 对话路由：`openhands/agent_server/conversation_router.py`
- 事件路由：`openhands/agent_server/event_router.py`
- 工具路由：`openhands/agent_server/tool_router.py`

## 调试示例

### 调试对话创建
在 `conversation_router.py` 中设置断点，观察新对话的创建过程。

### 调试事件处理
在 `event_service.py` 中设置断点，跟踪事件的处理流程。

### 调试WebSocket连接
在 `event_router.py` 中的WebSocket端点设置断点，调试实时通信。

## 日志调试

除了断点调试，还可以通过日志进行调试：

```bash
# 设置环境变量启动
DEBUG=true LOG_LEVEL=DEBUG uv run python -m openhands.agent_server
```

## 测试调试

运行特定测试进行调试：
```bash
# 调试特定测试文件
uv run pytest tests/agent_server/test_conversation_service.py -v -s
```

## 故障排除

### 断点不生效
- 确保 `justMyCode` 设置为 `false`
- 检查PYTHONPATH是否正确设置

### 服务器启动失败
- 检查端口是否被占用
- 验证配置文件路径和格式

### 环境变量未生效
- 确保在launch.json中正确设置了env变量
- 检查变量名拼写
