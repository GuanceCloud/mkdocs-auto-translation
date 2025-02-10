# MkDocs Translator

MkDocs Translator 是一个自动化工具，用于将 MkDocs 文档库从一种语言翻译为另一种语言。它使用 Dify AI API 进行翻译，并保持文档的目录结构和 Markdown 格式。

## 特性

- 使用 Dify AI API 进行高质量的文档翻译
- 保持原始文档的目录结构和 Markdown 格式
- 支持增量翻译，避免重复处理未更改的文件
- 自动复制非翻译文件（如图片、CSS等）到目标目录
- 提供详细的翻译进度和结果报告
- 支持流式翻译响应，实时显示翻译进度

## 安装

1. 克隆仓库： 

```bash
git clone https://github.com/GuanceCloud/mkdocs-translator.git
cd mkdocs-translator
```

2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 设置环境变量：

```bash
export DIFY_API_KEY="your-dify-api-key"
```

4. 运行翻译：

```bash
python -m mkdocs_translator.cli \
--source /path/to/source \
--target /path/to/target \
--target-language "英语" \
--api-key "your-dify-api-key" \
--user "your-username"
```

5. 添加黑名单文件：

在源目录中创建一个 .translate-blacklist 文件，文件中的每一行表示一个文件路径，如果文件路径在源目录中，则不会被翻译。

.translate-blacklist 文件示例： 

```
# 黑名单文件

billing/commercial-version.md
``` 

## 注意事项

- 请确保目标目录存在，否则会创建一个新目录。
- 请确保源目录存在，否则会报错。
- 请确保 Dify AI API 密钥正确，否则会报错。
- 请确保用户名正确，否则会报错。
- 请确保查询语句正确，否则会报错。
- 请确保响应模式正确，否则会报错。

