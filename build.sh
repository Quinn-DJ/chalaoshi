#!/bin/bash
# ============================================================
# 查老师 - chalaoshi 离线网站构建脚本
# 优先使用 uv 管理环境，未安装时自动降级为 venv + pip
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🎓 查老师 - 浙江大学教师评价查询系统"
echo "========================================"

# ================================================================
# 辅助函数：从 pyproject.toml 提取依赖并写入 requirements.txt
# ================================================================
generate_requirements() {
    echo "📝 从 pyproject.toml 生成 requirements.txt ..."
    python3 -c "
deps = []
in_deps = False
with open('pyproject.toml') as f:
    for line in f:
        stripped = line.strip()
        if stripped == 'dependencies = [':
            in_deps = True
            continue
        if in_deps:
            if stripped == ']':
                break
            dep = stripped.rstrip(',').strip().strip('\"')
            if dep:
                deps.append(dep)
with open('requirements.txt', 'w') as f:
    f.write('\n'.join(deps) + '\n')
print(f'  生成 {len(deps)} 条依赖')
"
}

# ================================================================
# 路径 A：使用 uv（优先）
# ================================================================
if command -v uv &>/dev/null; then
    echo "✅ uv $(uv --version | cut -d' ' -f2)"

    echo ""
    echo "📦 同步依赖..."
    uv sync

    echo ""
    exec uv run python main.py "$@"
fi

# ================================================================
# 路径 B：降级为 venv + pip
# ================================================================
echo "⚠️  未检测到 uv，降级使用 venv + pip"
echo "   提示: 安装 uv 可获得更快的依赖管理和可复现构建"
echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
echo ""

# --- 检查 Python3 ------------------------------------------------
if ! command -v python3 &>/dev/null; then
    echo "❌ 未找到 python3，请先安装 Python >= 3.14"
    exit 1
fi
echo "✅ python3 $(python3 --version)"

# --- 生成 requirements.txt ---------------------------------------
generate_requirements

# --- 创建/激活 venv（使用独立目录避免与 uv 冲突）--------------
VENV_DIR=".venv-fallback"

if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "🔧 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

echo "📦 安装依赖..."
"$VENV_DIR/bin/pip" install -r requirements.txt -q

# --- 执行构建 ---------------------------------------------------
echo ""
exec "$VENV_DIR/bin/python" main.py "$@"
