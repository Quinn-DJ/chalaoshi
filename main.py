#!/usr/bin/env python3
"""
查老师 - chalaoshi 离线网站构建工具（统一入口）

配置文件:
    config/update.json  — 外部发放的更新通知（放置此文件后运行主程序即可自动更新）
    config/config.yaml  — 本地缓存（版本号 + 密码，由程序自动维护，无需手动编辑）

用法:
    uv run main.py                      # 完整构建（自动检查 config/update.json 更新）
    uv run main.py download             # 仅下载数据压缩包
    uv run main.py extract              # 仅解压数据文件
    uv run main.py build                # 仅构建 HTML
    uv run main.py build --main-only    # 仅构建主页（不含教师单页）
    uv run main.py info                 # 查看压缩包信息
    uv run main.py update               # 手动触发更新检查（读取 config/update.json）
"""

import sys
import time
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def step_header(title: str) -> None:
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")


def check_requirements() -> None:
    """检查运行环境"""
    step_header("检查运行环境")

    # 确保必要目录存在
    dirs = ["logs", "comment/extracted"]
    for d in dirs:
        p = PROJECT_ROOT / d
        p.mkdir(parents=True, exist_ok=True)
        print(f"  ✅ 目录就绪: {d}")


def do_download() -> bool:
    """下载数据压缩包"""
    step_header("下载数据压缩包")

    from src.file_downloader import FileDownloader

    downloader = FileDownloader()
    results = downloader.download_from_config()
    success = sum(results.values())
    total = len(results)
    print(f"  下载完成: {success}/{total} 个文件成功")
    return success == total


def do_extract() -> bool:
    """解压数据文件"""
    step_header("解压数据文件")

    extract_dir = PROJECT_ROOT / "comment" / "extracted"
    if extract_dir.exists() and any(extract_dir.iterdir()):
        print("  ✅ 数据文件已解压，跳过")
        return True

    from src.file_extractor import FileExtractor

    extractor = FileExtractor()
    results = extractor.extract_from_config()
    success = sum(results.values())
    total = len(results)
    print(f"  解压完成: {success}/{total} 个文件成功")

    # 检查结果
    csv_count = len(list(extract_dir.glob("*.csv"))) if extract_dir.exists() else 0
    print(f"  📊 解压文件数量: {csv_count}")
    return success == total and csv_count > 0


def do_build(main_only: bool = False) -> bool:
    """构建 HTML 网站"""
    if main_only:
        step_header("构建 HTML（仅主页）")
    else:
        step_header("构建 HTML（主页 + 教师单页）")

    from src.build_html import SingleHTMLBuilder

    builder = SingleHTMLBuilder(
        generate_individual_pages=not main_only
    )

    if not builder.source_dir.exists():
        print(f"  ❌ 源数据目录不存在: {builder.source_dir}")
        return False

    builder.build_all()

    index_file = PROJECT_ROOT / "web" / "complete.html"
    if index_file.exists():
        print(f"  ✅ HTML 构建完成: web/complete.html")
        return True
    else:
        print("  ❌ HTML 文件生成失败")
        return False


def do_info() -> None:
    """显示压缩包信息"""
    step_header("压缩包信息")

    info_file = PROJECT_ROOT / "logs" / "archive_info.json"
    if not info_file.exists():
        print("  ⚠️  暂无压缩包信息（尚未下载解压）")
        return

    import json
    with open(info_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        print("  ⚠️  暂无压缩包信息")
        return

    print(f"  共 {len(data)} 个压缩包记录:\n")
    for i, info in enumerate(data, 1):
        print(f"  {i}. {info.get('filename', 'N/A')}")
        print(f"     日期: {info.get('date_formatted', 'N/A')}")
        print(f"     解压状态: {'已解压' if info.get('extracted') else '未解压'}")
        print()


def do_update() -> bool:
    """检查 config/update.json 并应用数据集更新"""
    step_header("检查数据集更新")

    from src.update_manager import UpdateManager

    mgr = UpdateManager()
    return mgr.check_and_apply()


def do_full(main_only: bool = False) -> bool:
    """执行完整构建流程"""
    print("🎓 查老师 - 浙江大学教师评价查询系统")
    print("=" * 50)
    print("开始完整构建流程...")

    start = time.time()

    check_requirements()

    # 检查更新（对比 config/update.json 与 config/config.yaml）
    if not do_update():
        print("\n❌ 更新失败，构建中止")
        return False

    # 下载（基于 download_config.yaml 中的任务列表）
    if not do_download():
        print("\n❌ 下载失败，构建中止")
        return False

    # 解压
    if not do_extract():
        print("\n❌ 解压失败，构建中止")
        return False

    # 构建 HTML
    if not do_build(main_only=main_only):
        print("\n❌ HTML 构建失败")
        return False

    # 完成
    elapsed = int(time.time() - start)
    web_dir = PROJECT_ROOT / "web"
    index = web_dir / "index.html"

    print(f"\n{'='*50}")
    print("  🎉 构建成功完成！")
    print(f"  ⏱️  总用时: {elapsed} 秒")
    print(f"  📁 网站目录: {web_dir}")
    print(f"  🌐 主页文件: {index}")
    print(f"{'='*50}")
    print(f"\n  启动方式:")
    print(f"    open '{index}'")
    print(f"    cd web && python3 -m http.server 8000")
    return True


def print_help() -> None:
    print(__doc__)


def main() -> None:
    args = sys.argv[1:]

    # 解析 --main-only / -m 参数
    main_only = "--main-only" in args or "-m" in args
    # 过滤掉 flag 参数得到子命令
    cmds = [a for a in args if a not in ("--main-only", "-m")]

    if not cmds:
        # 默认：完整构建
        success = do_full(main_only=main_only)
        sys.exit(0 if success else 1)
    elif cmds[0] in ("-h", "--help", "help"):
        print_help()
    elif cmds[0] == "download":
        success = do_download()
        sys.exit(0 if success else 1)
    elif cmds[0] == "extract":
        success = do_extract()
        sys.exit(0 if success else 1)
    elif cmds[0] == "build":
        success = do_build(main_only=main_only)
        sys.exit(0 if success else 1)
    elif cmds[0] == "info":
        do_info()
    elif cmds[0] == "update":
        success = do_update()
        sys.exit(0 if success else 1)
    else:
        print(f"未知命令: {cmds[0]}")
        print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
