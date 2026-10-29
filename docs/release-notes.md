# v1.1.0 · 本地文档检索台 Windows 桌面版

离线检索 Markdown、TXT、DOCX 和有文本层的 PDF，显示命中原文、PDF 页码与 DOCX 段落 / 表格位置。

## Windows 用户下载

下载附件 **LocalDocFinder-1.1.0-windows-x64.zip**，完整解压后双击 **LocalDocFinder.exe**。无需安装 Python 或 Word。

选择资料目录 → 建立 / 更新索引 → 输入关键词搜索。多个词要求全部匹配，英文不区分大小写。

如需桌面图标，右键 EXE → 显示更多选项 → 发送到 → 桌面快捷方式。EXE 与 _internal 文件夹需要保持在一起。退出时在运行管理窗口点击“退出软件”。

## 功能与验证

- 递归扫描；新增、修改、删除文件后可更新索引。
- PDF 物理页码定位；DOCX 正文和表格提取文本视图。
- 文档和索引留在本机，正常使用无需联网，不修改原文件。
- 32 项自动化测试通过，并通过真实 Windows EXE 自检。

扫描 PDF 不提供 OCR，旧 .doc 不支持；DOCX 文本视图不还原 Word 排版。

**自动生成的 Source code 是源码，不是可直接运行的软件包。** 开发者请参阅仓库 README。

SHA256SUMS.txt 可用于校验 Windows ZIP。代码采用 MIT 许可证，软件包附第三方组件许可说明。

