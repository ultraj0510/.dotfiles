#!/bin/bash
input=$(cat)
model=$(echo "$input" | jq -r '.model.display_name // "Unknown"')
context_pct=$(echo "$input" | jq -r '.context_window.used_percentage // 0')
workspace=$(echo "$input" | jq -r '.workspace.current_dir // ""')
cost_usd=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
in_tok=$(echo "$input" | jq -r '.context_window.total_input_tokens // 0')
out_tok=$(echo "$input" | jq -r '.context_window.total_output_tokens // 0')

ws_name="--"
[[ -n "$workspace" ]] && ws_name=$(basename "$workspace")
branch=$(git -C "$workspace" branch --show-current 2>/dev/null || echo "--")
branch="${branch:-"--"}"

color_for_pct() {
  local pct="$1"
  [[ -z "$pct" || "$pct" == "null" ]] && { echo "\033[0m"; return; }
  local int_pct="${pct%.*}"
  if (( int_pct >= 90 )); then echo "\033[31m"
  elif (( int_pct >= 70 )); then echo "\033[33m"
  else echo "\033[32m"; fi
}
RESET="\033[0m"

context_int="${context_pct%.*}"
filled=$(( context_int / 10 )); empty=$(( 10 - filled ))
bar=""
for (( i=0; i<filled; i++ )); do bar+="●"; done
for (( i=0; i<empty; i++ )); do bar+="○"; done
context_color=$(color_for_pct "$context_int")

# Manual cost calculation for non-Anthropic APIs
base_url="${ANTHROPIC_BASE_URL:-}"
if [[ "$base_url" == *"deepseek"* ]]; then
  if [[ "$model" == *"flash"* ]]; then
    cost=$(python3 -c "print((${in_tok}/1000000)*0.14 + (${out_tok}/1000000)*0.28)")
  else
    cost=$(python3 -c "print((${in_tok}/1000000)*0.435 + (${out_tok}/1000000)*0.87)")
  fi
  cost_display=$(printf '~$%.4f (DeepSeek)' "$cost")
elif [[ "$base_url" == *"mimo"* ]]; then
  cost=$(python3 -c "print((${in_tok}/1000000)*1 + (${out_tok}/1000000)*3)")
  cost_display=$(printf '~$%.4f (MiMo)' "$cost")
else
  cost_display=$(printf '$%.4f' "$cost_usd")
fi

echo -e "${model} ▸ ${ws_name} ⎇ ${branch}"
echo -e "${context_color}${bar}${RESET} ${context_int}% ▸ ${cost_display} ▸ in:${in_tok} out:${out_tok}"
