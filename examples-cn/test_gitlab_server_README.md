# GitLab 工作空间沙箱服务器测试

这个脚本包含用于测试 `examples-cn/25_gitlab_workspace_sandboxed_server.py` 的 curl 请求。

## 测试脚本

`test_gitlab_server.sh` 包含以下测试用例：

### 测试 1: 创建新对话
- 创建一个新对话并克隆指定的 GitLab 仓库
- 使用 Git token 进行身份验证
- 在工作空间中执行指定的任务

### 测试 2: 恢复现有对话  
- 恢复具有特定 conversation_id 的现有对话
- 使用现有的工作空间继续之前的任务

### 测试 3: 创建对话但不使用 Git 仓库
- 创建一个不涉及 Git 仓库的简单对话
- 用于测试基本的对话功能

### 测试 4: 使用自定义工作空间 ID
- 创建对话时指定自定义的工作空间 ID
- 用于测试工作空间持久化功能

## 使用方法

1. 确保服务器正在运行：
```bash
cd examples-cn
python 25_gitlab_workspace_sandboxed_server.py
```

2. 运行测试脚本：
```bash
chmod +x test_gitlab_server.sh
./test_gitlab_server.sh
```

## 注意事项

- 确保设置了 `LITELLM_API_KEY` 环境变量
- 根据实际需要修改 GitLab token 和仓库 URL
- 服务器默认运行在 `http://localhost:8000`
