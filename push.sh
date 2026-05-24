#!/bin/bash

REMOTE_URL="${1:-}"

if ! git remote get-url origin &>/dev/null; then
    if [ -z "$REMOTE_URL" ]; then
        echo "未配置远程仓库，请提供地址："
        echo "  ./push.sh <远程仓库URL>"
        echo "  例: ./push.sh git@github.com:user/five-api.git"
        exit 1
    fi
    git remote add origin "$REMOTE_URL"
    echo "已添加远程仓库: $REMOTE_URL"
fi

BRANCH=$(git branch --show-current)

git add -A
git status --short

read -p "提交信息: " MSG
[ -z "$MSG" ] && { echo "提交信息不能为空"; exit 1; }

git commit -m "$MSG"
git push -u origin "$BRANCH"

echo "已推送到 origin/$BRANCH"
