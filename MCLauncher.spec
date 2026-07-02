# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格文件 - Minecraft Launcher"""

import os
import sys
from pathlib import Path

block_cipher = None

project_root = Path(os.getcwd())
src_path = project_root / "src"
main_script = project_root / "main.py"
icon_path = project_root / "assets" / "icons" / "icon.ico"

if not icon_path.exists():
    icon_path = None

excludes = [
    "tkinter",
    "unittest",
    "email",
    "html",
    "http.server",
    "xmlrpc",
    "pydoc",
    "doctest",
    "argparse",
    "difflib",
    "pdb",
    "profile",
    "pstats",
    "cProfile",
    "curses",
    "pyexpat",
    "multiprocessing",
    "concurrent",
    "lib2to3",
    "distutils",
    "setuptools",
    "pip",
    "wheel",
    "IPython",
    "jupyter",
    "notebook",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "PIL",
    "cv2",
    "pytest",
    "black",
    "flake8",
    "mypy",
    "coverage",
    "tox",
]

hiddenimports = [
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
    "src.utils.network",
    "src.utils.crash_handler",
    "src.utils.updater",
    "src.utils.backup",
    "src.version",
    "src.version.api",
    "src.version.downloader",
    "src.version.asset_manager",
    "src.version.version_manager",
    "src.version.manager",
    "src.version.metadata",
    "src.modloader",
    "src.modloader.base",
    "src.modloader.forge",
    "src.modloader.fabric",
    "src.modloader.quilt",
    "src.modloader.mod_manager",
    "src.account",
    "src.ui",
    "src.ui.main_window",
    "src.ui.settings_dialog",
    "src.ui.download_dialog",
    "src.ui.account_dialog",
    "src.ui.first_run_wizard",
    "src.ui.styles",
    "src.ui.styles.theme_manager",
    "src.ui.widgets",
    "src.ui.widgets.title_bar",
    "src.ui.widgets.dialog_title_bar",
    "src.ui.widgets.card_widget",
    "src.ui.widgets.toast",
    "src.ui.widgets.loading_spinner",
    "src.ui.widgets.download_item",
    "src.ui.widgets.version_list_item",
    "requests",
    "urllib3",
    "certifi",
    "charset_normalizer",
    "idna",
    "tomllib",
]

a = Analysis(
    [str(main_script)],
    pathex=[str(src_path), str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MCLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        "vcruntime140.dll",
        "python3*.dll",
        "Qt6*.dll",
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path else None,
    version="assets/version_info.txt" if (project_root / "assets" / "version_info.txt").exists() else None,
)
