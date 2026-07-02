#!/usr/bin/env python3
"""Minecraft Launcher 打包脚本。

使用 PyInstaller 将启动器打包为单个可执行文件。
支持 Windows / Linux / macOS 平台。

用法:
    python build.py              # 打包单文件版本
    python build.py --onedir     # 打包为目录模式
    python build.py --clean      # 清理构建目录后打包
    python build.py --no-upx     # 不使用 UPX 压缩
    python build.py --debug      # 调试模式（保留控制台输出）
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
SPEC_FILE = PROJECT_ROOT / "MCLauncher.spec"

APP_NAME = "MCLauncher"
APP_VERSION = "1.0.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minecraft Launcher 打包脚本")
    parser.add_argument("--onedir", action="store_true",
                        help="打包为目录模式（默认单文件）")
    parser.add_argument("--clean", action="store_true",
                        help="打包前清理构建目录")
    parser.add_argument("--no-upx", action="store_true",
                        help="不使用 UPX 压缩")
    parser.add_argument("--debug", action="store_true",
                        help="调试模式（显示控制台窗口）")
    parser.add_argument("--icon", type=str, default=None,
                        help="指定图标文件路径")
    parser.add_argument("--name", type=str, default=APP_NAME,
                        help="输出文件名")
    return parser.parse_args()


def clean_build() -> None:
    print("清理构建目录...")
    for d in (DIST_DIR, BUILD_DIR):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            print(f"  已删除: {d}")


def check_pyinstaller() -> None:
    try:
        import PyInstaller
        print(f"PyInstaller 版本: {PyInstaller.__version__}")
    except ImportError:
        print("错误: PyInstaller 未安装，请运行: pip install pyinstaller")
        sys.exit(1)


def generate_icon() -> Path | None:
    """生成简单的占位图标文件（如不存在）。"""
    icon_path = PROJECT_ROOT / "assets" / "icons"
    icon_path.mkdir(parents=True, exist_ok=True)

    ico_file = icon_path / "icon.ico"
    if ico_file.exists():
        return ico_file

    try:
        from PIL import Image, ImageDraw

        size = 256
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rounded_rectangle([20, 20, size - 20, size - 20], radius=40,
                               fill=(124, 58, 237, 255))

        block_size = size // 6
        green = (34, 197, 94, 255)
        brown = (120, 80, 40, 255)
        for row in range(3):
            for col in range(3):
                x = size // 2 - block_size * 1.5 + col * block_size
                y = size // 2 - block_size * 1.5 + row * block_size
                if row < 2:
                    draw.rectangle([x + 4, y + 4, x + block_size - 4, y + block_size - 4], fill=green)
                else:
                    draw.rectangle([x + 4, y + 4, x + block_size - 4, y + block_size - 4], fill=brown)

        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        img.save(str(ico_file), format="ICO", sizes=sizes)
        print(f"已生成应用图标: {ico_file}")
        return ico_file

    except ImportError:
        print("警告: Pillow 未安装，无法自动生成图标。将使用默认图标。")
        print("  安装 Pillow: pip install Pillow")
        return None


def build(args: argparse.Namespace) -> bool:
    cmd = [sys.executable, "-m", "PyInstaller"]

    if not args.onedir:
        cmd.append("--onefile")

    if not args.debug:
        cmd.append("--windowed")
        cmd.append("--noconsole")

    if args.no_upx:
        cmd.append("--noupx")

    cmd.append("--clean")

    cmd.extend(["--name", args.name])

    icon_file = args.icon
    if icon_file is None:
        icon_file = generate_icon()
    if icon_file and Path(icon_file).exists():
        cmd.extend(["--icon", str(icon_file)])

    cmd.extend(["--distpath", str(DIST_DIR)])
    cmd.extend(["--workpath", str(BUILD_DIR)])
    cmd.extend(["--specpath", str(PROJECT_ROOT)])

    hidden_imports = [
        "src",
        "src.core",
        "src.core.launcher",
        "src.core.java_detector",
        "src.core.account",
        "src.utils",
        "src.utils.logger",
        "src.utils.config",
        "src.utils.file_utils",
        "src.utils.http_utils",
        "src.utils.crash_handler",
        "src.utils.updater",
        "src.utils.backup",
        "src.version",
        "src.version.api",
        "src.version.downloader",
        "src.version.asset_manager",
        "src.version.version_manager",
        "src.version.metadata",
        "src.modloader",
        "src.modloader.base",
        "src.modloader.forge",
        "src.modloader.fabric",
        "src.modloader.quilt",
        "src.modloader.mod_manager",
        "src.ui",
        "src.ui.main_window",
        "src.ui.settings_dialog",
        "src.ui.download_dialog",
        "src.ui.account_dialog",
        "src.ui.first_run_wizard",
        "src.ui.styles.theme_manager",
        "src.ui.widgets",
        "src.ui.widgets.title_bar",
        "src.ui.widgets.dialog_title_bar",
        "src.ui.widgets.card_widget",
        "src.ui.widgets.toast",
        "src.ui.widgets.loading_spinner",
        "src.ui.widgets.download_item",
        "src.ui.widgets.version_list_item",
    ]
    for mod in hidden_imports:
        cmd.extend(["--hidden-import", mod])

    excludes = [
        "tkinter", "unittest", "email", "http.server", "xmlrpc",
        "pydoc", "doctest", "pdb", "profile", "pstats", "cProfile",
        "curses", "pyexpat", "lib2to3", "distutils", "setuptools",
        "pip", "wheel", "IPython", "jupyter", "matplotlib", "numpy",
        "pandas", "scipy", "PIL", "cv2", "pytest",
    ]
    for exc in excludes:
        cmd.extend(["--exclude-module", exc])

    cmd.extend(["--version-file", str(PROJECT_ROOT / "assets" / "version_info.txt")])

    cmd.append(str(PROJECT_ROOT / "main.py"))

    print("\n" + "=" * 60)
    print(f"开始打包 {APP_NAME} v{APP_VERSION}")
    print(f"平台: {platform.system()} {platform.machine()}")
    print(f"模式: {'目录模式' if args.onedir else '单文件模式'}")
    print(f"调试: {'是' if args.debug else '否'}")
    print("=" * 60 + "\n")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)

    if result.returncode != 0:
        print(f"\n❌ 打包失败 (退出码: {result.returncode})")
        return False

    exe_name = args.name
    if platform.system() == "Windows":
        exe_name += ".exe"

    output_path = DIST_DIR / exe_name
    if args.onedir:
        output_path = DIST_DIR / args.name / exe_name

    if output_path.exists():
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"\n✅ 打包成功!")
        print(f"输出文件: {output_path}")
        print(f"文件大小: {size_mb:.1f} MB")
    else:
        print(f"\n⚠️  打包完成，但未找到输出文件: {output_path}")

    return True


def main() -> int:
    args = parse_args()

    if args.clean:
        clean_build()

    check_pyinstaller()

    success = build(args)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
