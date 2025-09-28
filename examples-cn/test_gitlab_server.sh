#!/bin/bash

# 测试 GitLab 工作空间沙箱服务器的 curl 请求

echo "=== 测试 1: 创建新对话 ==="
curl -X 'POST' \
  'http://localhost:8000/conversation' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "把项目文件结构写入到目录下的tree.txt文件中",
    "git_repos": [
      "https://git.wchat.cc/ai/code-helper/exmpler-project/document-management-api.git",
      "https://git.wchat.cc/ai/code-helper/exmpler-project/document-management-web.git"
    ],
    "git_token": "$GITLAB_TOKEN"
  }'

echo -e "\n=== 测试 2: 恢复现有对话 ==="
curl -X 'POST' \
  'http://localhost:8000/conversation' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "分析项目生成README.md文件",
 "conversation_id":"abf70812-5b1c-440e-8971-b19422358b57","workspace_id":"1ba597143aba4b03bde7470d965b4d1c"
  }'

echo -e "\n=== 测试 3: 创建对话但不使用 Git 仓库 ==="
curl -X 'POST' \
  'http://localhost:8321/conversation' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "用python写一个冒泡排序算法",
    "git_repos": null,
    "git_token": null
  }'

echo -e "\n=== 测试 4: 使用自定义工作空间 ID 创建对话 ==="
curl -X 'POST' \
  'http://localhost:8321/conversation' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "克隆并分析这个 GitLab 仓库https://github.com/all-hands-ai/agent-sdk",
    "git_repos": null,
    "git_token": null
  }'
