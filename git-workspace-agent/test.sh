#!/bin/bash

# 测试 GitLab 工作区沙箱服务器的 curl 请求

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
    "message": "总结你的工作内容，写入到summary.txt文件中",
 "conversation_id":"2d05dd9d-891a-4bd7-9c12-94ed9a565148","workspace_id":"4c3f228b60c143ac9e08c352a9967ef2"
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
