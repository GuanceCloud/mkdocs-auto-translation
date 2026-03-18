# MkDocs Translator

MkDocs Translator 是一个自动化工具，用于将 MkDocs 文档库从一种语言翻译为另一种语言。它使用兼容 OpenAI 格式的大模型 API 进行翻译，并保持文档的目录结构和 Markdown 格式。

## 特性

- 使用兼容 OpenAI 格式的大模型 API 进行高质量的文档翻译
- 保持原始文档的目录结构和 Markdown 格式
- 支持增量翻译，避免重复处理未更改的文件
- 自动复制非翻译文件（如图片、CSS等）到目标目录
- 提供详细的翻译进度和结果报告
- 支持流式翻译响应，实时显示翻译进度
- 内置重试机制和超时控制，确保翻译稳定性

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
# OpenAI API Key（必需）
export OPENAI_API_KEY="your-openai-api-key"

# 可选：自定义 API 端点（用于兼容 OpenAI 格式的其他大模型）
export OPENAI_BASE_URL="http://one-api.dataflux.cn/v1"
```

4. 运行翻译：

```bash
python -m mkdocs_translator.cli \
--source /path/to/source \
--target /path/to/target \
--target-language "英语" \
--user "your-username" \
--workers 10 \
--overwrite-resources \
--delete-removed-resources
```

或者在参数中指定 API Key 和 Base URL：

```bash
python -m mkdocs_translator.cli \
--source /path/to/source \
--target /path/to/target \
--target-language "英语" \
--user "your-username" \
--workers 10 \
--overwrite-resources \
--delete-removed-resources \
--base_url http://one-api.dataflux.cn/v1 \
--api-key "your-openai-api-key"
```

### 可选参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--api-key` | 大模型 API Key | 环境变量 `OPENAI_API_KEY` |
| `--base-url` | API 端点地址 | `http://one-api.dataflux.cn/v1`，环境变量 `OPENAI_BASE_URL` |
| `--model` | 使用的模型名称 | `deepseek-v3.2` |
| `--response-mode` | 响应模式：`streaming` 或 `blocking` | `streaming` |
| `--workers` | 并行工作线程数 | `1` |
| `--check-chinese` | 检查翻译结果是否包含中文字符 | `false` |
| `--check-line-count` | 检查翻译前后行数差异是否超过 5% | `false` |
| `--overwrite-resources` | 是否将资源文件覆盖到目标目录 | `false` |
| `--delete-removed-resources` | 是否删除目标目录中，在源目录中不存在的资源文件 | `false` |

5. 添加黑名单文件：

在源目录中创建一个 .translate-blacklist 文件，文件中的每一行表示一个文件路径，如果文件路径在源目录中，则不会被翻译。

.translate-blacklist 文件示例：

```
# 黑名单文件

# 目录前缀匹配
datakit/
integrations/

# 精确匹配
billing/commericial-version.md

# 通配符匹配
billing/commericial-*.md
billing/v?/*.md
test-*.md
```

## 注意事项

- 请确保目标目录存在，否则会创建一个新目录。
- 请确保源目录存在，否则会报错。
- 请确保 API Key 正确，否则会报错。
- 支持任何兼容 OpenAI 格式的 API 端点（如 OpenAI、Azure OpenAI、Claude 等）。
- 使用流式响应模式时，终端会实时显示翻译进度（chunks 数量、速度、已用时间）。

