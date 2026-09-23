#!/bin/sh
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1
export PYTHONDONTWRITEBYTECODE=1
if [ -n "$PYTHON_EXE" ]; then
  exec "$PYTHON_EXE" scripts/runtime_support.py "$@"
elif [ -n "$SKILL_SYNC_PYTHON" ]; then
  exec "$SKILL_SYNC_PYTHON" scripts/runtime_support.py "$@"
elif command -v python3 >/dev/null 2>&1; then
  exec python3 scripts/runtime_support.py "$@"
elif command -v python >/dev/null 2>&1; then
  exec python scripts/runtime_support.py "$@"
else
  echo '未发现 Python 命令。请接入智能体用实际 sys.executable 运行 bootstrap.py，并使用生成的环境快捷方式。'
  exit 1
fi
