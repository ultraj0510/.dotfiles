# Claude Code API switching aliases

# GitHub MCP plugin 用トークン（gh CLI から動的取得）
export GITHUB_PERSONAL_ACCESS_TOKEN=$(gh auth token 2>/dev/null)

# DeepSeek API で claude を起動（公式 OAuth トークンをクリア）
