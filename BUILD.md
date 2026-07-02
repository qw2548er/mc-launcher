# Minecraft Launcher 打包说明

## 环境准备

### 1. 安装依赖

```bash
pip install -r requirements.txt
pip install pyinstaller
pip install pillow       # 可选，用于自动生成图标
```

### 2. 准备图标（可选）

将自定义图标放置到 `assets/icons/icon.ico`（Windows 推荐 256x256 多尺寸 ICO 文件）。
如果没有提供图标，`build.py` 会自动生成一个简单的占位图标。

---

## 打包命令

### 快速打包（单文件，无控制台）

```bash
python build.py
```

输出文件：`dist/MCLauncher.exe`（Windows）或 `dist/MCLauncher`（Linux/macOS）

### 其他打包选项

```bash
# 目录模式（启动更快，不压缩为单文件）
python build.py --onedir

# 清理构建缓存后重新打包
python build.py --clean

# 不使用 UPX 压缩（兼容性更好）
python build.py --no-upx

# 调试模式（保留控制台窗口，可查看日志输出）
python build.py --debug

# 指定自定义图标
python build.py --icon path/to/icon.ico

# 自定义输出文件名
python build.py --name MyLauncher
```

### 使用 PyInstaller 直接调用 spec 文件

```bash
pyinstaller MCLauncher.spec --clean
```

---

## 平台支持

### Windows（推荐 Windows 10/11）

- 输出: `dist/MCLauncher.exe`
- 无需安装 Python，单文件直接运行
- 支持 Windows 7 SP1+（需安装 VC++ Redistributable）
- 建议使用 64 位 Python 3.12+ 打包

### Linux

```bash
# 安装依赖
sudo apt install python3-pip libgl1-mesa-glx libxkbcommon0 libdbus-1-3
pip install pyinstaller
python build.py
```

输出: `dist/MCLauncher`，可直接运行或创建 .desktop 快捷方式。

### macOS

```bash
pip install pyinstaller
python build.py
```

如需创建 .app bundle，使用 --onedir 模式后手动打包。

---

## 制作 Windows 安装包（Inno Setup）

1. 安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)
2. 先执行打包：`python build.py --clean`
3. 用 Inno Setup Compiler 打开 `setup.iss`
4. 点击 Build → Compile
5. 安装包输出到 `installer/MCLauncher-Setup-1.0.0.exe`

安装包特性：
- 自动创建桌面/开始菜单快捷方式
- 支持中文/英文界面
- 自动卸载程序
- 安装后可选启动
- 默认安装到用户目录（无需管理员权限）

---

## 减小体积优化

当前已排除的模块：
- tkinter, unittest, email, http.server, xmlrpc（标准库但不需要）
- IPython, jupyter, pytest 等开发工具
- matplotlib, numpy, pandas, PIL（如未使用）

如需进一步精简：
1. 使用虚拟环境（venv）只安装必需依赖
2. 考虑使用 UPX 压缩：`upx --best dist/MCLauncher.exe`（可能被杀毒软件误报）
3. 使用 `--exclude-module` 排除更多不需要的模块

## 常见问题

### Q: 打包后启动闪退？
A: 使用 `--debug` 参数打包，在控制台窗口查看错误信息。常见原因：
   - 缺少 hiddenimport（检查 build.py 中的 hidden_imports 列表）
   - 资源文件路径问题（PyInstaller 打包后使用 sys._MEIPASS 获取临时路径）

### Q: 杀毒软件误报？
A: PyInstaller 单文件启动时会解压临时文件，可能被误报。解决方法：
   - 对可执行文件进行代码签名
   - 使用 --onedir 模式（不产生临时文件解压）
   - 提交到杀毒软件白名单

### Q: 启动速度慢？
A: 单文件模式首次启动需解压，建议：
   - 使用 --onedir 模式（启动最快）
   - 使用 SSD 磁盘
   - 关闭实时杀毒扫描对安装目录的监控

### Q: Linux 上出现 "Could not load the Qt platform plugin"？
A: 安装 Qt 平台依赖：
```bash
sudo apt install libqt6gui6 libqt6widgets6 qt6-qpa-plugins
```
