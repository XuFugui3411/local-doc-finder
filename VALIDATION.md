# 第一版验收记录

日期：2026-10-29。测试环境：Windows x64 / Python 3.11.9 / pypdf 6.21.4。

## 自动化测试

执行 `.venv\Scripts\python -m unittest discover -s tests -v`：**22 项通过，无跳过**。

覆盖 Markdown/TXT/PDF 提取、递归子目录、中文路径、四种文本编码、跨文件名和正文的多词 AND、英文大小写、字面特殊字符、原文高亮分段、PDF 页码和跨页匹配、真实图片扫描 PDF、空白页混合 PDF、加密和损坏 PDF。

索引覆盖新增、修改、删除、保持文件大小和修改时间的内容变化、未变文件复用、重启持久性、不同根目录隔离、权限失败时禁用旧正文、根目录丢失时保留快照、取消事务回滚。

Windows 上使用真实独占文件句柄验证占用文件失败后继续；用真实目录联接验证不越界递归。接口测试覆盖会话令牌、外站 Origin、伪造 Host、原文路径越界、文本原文 MIME 和静态文件路由范围。

## 浏览器验收

使用独立 Playwright Chrome 会话，在本机 `127.0.0.1:8766` 验证：

- 网页中粘贴演示目录、点击建立索引，成功显示 6 份文档、5 份有正文、1 项扫描页提示。
- 搜索 `alpha budget`，AND 匹配仅返回 PDF；正文和原文链接均指向物理第 2 页。
- 切换 PDF / TXT 筛选，结果数分别为 1 / 0。
- 搜索 `<script>`，以原文显示，未生成 script 元素或弹出脚本对话框。
- 搜索 `alpha` 返回 4 份文档，保留原文大小写和高亮，扫描页的 OCR 限制提示可展开。
- 390 px 窄屏无横向溢出；桌面与窄屏截图均已目视检查。
- 本次验收的页面请求均指向本机服务；浏览器控制台为 0 错误、0 警告。

截图：[桌面](docs/images/search-desktop.png)、[窄屏](docs/images/search-mobile.png)。截图只包含生成的演示资料。

复现：先运行 `tools/create_demo.py`，启动隔离测试服务 `app.py --data-dir .data --no-browser`，在网页中选择输出的演示目录并建立索引，再通过 Playwright CLI 执行 `run-code --filename tools/browser_acceptance.js`。

## 已知边界

本版不做 OCR、语义检索、自动文件监视或相关性排序。PDF 原文链接已验证页码参数；浏览器若配置为下载 PDF，需要用户在自己的 PDF 阅读器中跳页。桌面原生目录对话框提供快捷选择，当前验收主要通过粘贴路径完成目录指定。资源上限、缓存、索引位置及更新语义见 README。

## 2026-10-30：DOCX 扩展验收

更新后自动化测试为 **29 项通过，无跳过**，原有格式的回归测试一并通过。

新增测试覆盖：DOCX 连续文本运行拼接、中文、制表符和换行、正文与表格顺序、跨段落 / 表格多词 AND、DOCX 筛选、段落和表格行定位、修改 / 删除 / 提取缓存、旧 SQLite 索引迁移、损坏文件、加密 Office 格式提示、空正文、XML 大小 / 字符上限和 DTD 拒绝。HTTP 验证提取文本视图中的 HTML 转义、文本块锚点、原文件下载的字节一致性和阅读样式路由。

浏览器使用独立测试数据目录和 8871 端口，通过页面建立含 DOCX 的索引，搜索 `wordcheck 三万元`，确认跨正文和表格匹配；切换 DOCX 筛选后只保留 Word 文档。点击“表格 1 · 第 1 行”可打开本机提取文本视图并跳到 `#block-2`，其中显示原来的“三万元”。原文件下载入口存在；HTTP 测试已验证下载字节完整。

DOCX 不显示 PDF 页码，页面说明它是提取文本视图而非 Word 完整排版。390 px 窄屏无横向溢出，搜索页和阅读页截图已目视检查。

截图：[DOCX 搜索](docs/images/docx-search.png)、[提取文本阅读](docs/images/docx-reader.png)、[窄屏](docs/images/docx-mobile.png)。自动化脚本为 `tools/browser_docx_acceptance.js`；演示数据可用 `tools/create_demo.py` 创建。

## 2026-10-30：Windows 桌面版

Python 3.11.9 / PyInstaller 6.22.3 构建 Windows x64 目录式软件和 1.1.0 便携 ZIP。自动化测试 **32 项通过，无跳过**。

构建脚本使用真实打包 EXE 执行自检，将 PATH 限制为 Windows System32 并移除 PYTHONHOME / PYTHONPATH，确认四种格式建索引、PDF / DOCX 冻结子进程、PDF 第 2 页、DOCX 表格位置与文本视图、随包网页资源、HTTP 搜索以及修改 / 删除更新均正常。ZIP CRC 和 LICENSE 字节校验通过。报告见 `build/frozen-check.json`。

实际运行 EXE：运行管理窗口布局及两个按钮完整可见；同一数据目录再次启动返回 0，保留原服务 PID，HTTP 仍为 200；点击“退出软件”后进程退出、会话文件清理。冻结版独立目录选择对话框已实际显示。测试使用隔离的 `.data-desktop-qa` 数据目录。

桌面快捷方式指向完整程序目录中的 EXE，程序与 `_internal` 必须保持在一起。该版本采用本地网页界面和运行管理窗口，无需另行安装 Python；未声称提供系统托盘功能。
