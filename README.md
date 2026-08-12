# MkDocs Translator

MkDocs Translator 使用兼容 OpenAI 格式的大模型 API，把中文 MkDocs 文档一次翻译成英语、日语和韩语，并保持 Markdown、`.pages`、资源文件和目录结构。

## 功能

- 单次运行支持 `en`、`ja`、`ko` 一种或多种语言
- 所有 `(文档, 语言)` 任务共享一个全局 worker 上限
- 每个语言目录维护独立增量状态
- 自动迁移源目录中的旧版英文 `metadata.json`
- 内置专业可观测性中英日韩术语，可由项目 YAML 覆盖
- 翻译成功后才原子替换目标文件，失败时保留旧译文
- 校验 Markdown 链接、图片、代码围栏、HTML、模板变量和 `.pages` YAML
- 同步图片、CSS、JavaScript 等非翻译资源

## 安装

```bash
git clone https://github.com/GuanceCloud/mkdocs-translator.git
cd mkdocs-translator
pip install -r requirements.txt
pip install -e .
```

设置 API：

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 可选
```

## 单语言运行

单语言模式中，`--target` 是该语言的实际目录，兼容原有调用方式：

```bash
mkdocs-translator \
  --source docs/zh \
  --target docs/en \
  --target-language en \
  --workers 10
```

也可以使用别名：

- 英语：`en`、`English`、`英语`、`英文`
- 日语：`ja`、`Japanese`、`日语`、`日文`
- 韩语：`ko`、`Korean`、`韩语`、`韩文`

## 多语言运行

多语言模式中，`--target` 是共同根目录，程序复用或自动创建标准语言子目录；已经存在的目录不会被删除或清空：

```bash
mkdocs-translator \
  --source docs/zh \
  --target docs \
  --target-languages en,ja,ko \
  --workers 10
```

输出结构：

```text
docs/
├── zh/
├── en/
│   └── .mkdocs-translator/
│       ├── metadata.json
│       └── last-run.json
├── ja/
│   └── .mkdocs-translator/
└── ko/
    └── .mkdocs-translator/
```

`--workers 10` 表示三种语言合计最多同时执行 10 个模型请求，不会为每种语言分别创建 10 个 worker。

## 自定义术语

使用 `--glossary` 覆盖或补充内置词典：

```yaml
version: 2
terms:
  观测云:
    ja: Guance
    ko: Guance
  应用性能监测:
    en:
      full: Application Performance Monitoring
      short: APM
    ja:
      full: アプリケーションパフォーマンスモニタリング
      short: APM
    ko:
      full: 애플리케이션 성능 모니터링
      short: APM
    usage: first_mention
    ui: short
  自定义功能:
    en: Custom Feature
    ja: カスタム機能
    ko: 사용자 정의 기능
```

```bash
mkdocs-translator \
  --source docs/zh \
  --target docs \
  --target-languages en,ja,ko \
  --glossary glossary.yml
```

自定义词条允许只配置需要覆盖的语言。普通固定词条可以继续使用 `version: 1`；
`version: 2` 额外支持同时定义 `full` 和 `short` 的概念词。`usage: first_mention`
表示 Markdown 标题或正文首次出现中文全称时使用“全称（缩写）”，后续使用缩写；
`ui: short` 表示 YAML 导航、菜单、按钮等紧凑 UI 文本只使用缩写。格式错误或未知语言字段会在调用模型前报错。

## 增量状态与旧版迁移

每种语言的状态保存在对应目标目录的 `.mkdocs-translator/metadata.json`。只要上次翻译成功、中文源文件 hash 未变化且目标译文仍然存在，就会跳过翻译。Prompt 和专业词典的修改不会触发已有文档重新翻译；指纹仅用于审计。

英文首次运行时，如果新状态不存在而中文源目录存在旧版 `metadata.json`，程序会只读校验并导入仍然有效的英文成功记录。旧文件不会被修改或删除；日语和韩语不会导入旧状态。

## 主要参数

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--target-language` | 单语言模式，`--target` 为具体语言目录 | 无 |
| `--target-languages` | 逗号分隔多语言模式，`--target` 为共同根目录 | 无 |
| `--glossary` | 自定义 YAML 术语文件 | 内置词典 |
| `--model` | 模型名称 | `gpt-4o` |
| `--response-mode` | `streaming` 或 `blocking` | `streaming` |
| `--workers` | 全局最大并发任务数 | `1` |
| `--check-chinese` | 检查英语、韩语正文中的残留汉字；日语自动跳过 | `false` |
| `--check-line-count` | 翻译前后行数差异不得超过 5% | `false` |
| `--check-structure` / `--no-check-structure` | 是否保护并校验链接、代码围栏、HTML、模板变量和 `.pages` 结构 | `true` |
| `--overwrite-resources` | 覆盖目标资源文件 | `false` |
| `--delete-removed-resources` | 删除源目录中已不存在的资源 | `false` |
| `--delete-removed-translations` | 删除已移除或已加入黑名单的译文和状态 | `false` |

`--target-language` 与 `--target-languages` 互斥，必须且只能提供一个。

使用 `--no-check-structure` 时，源文档会整篇原样发送给模型，不生成 `GXP_..._X` 保护标记，也不执行 Markdown/YAML 结构校验。空译文检查仍会执行；`--check-chinese` 和 `--check-line-count` 若显式启用也仍然有效。该模式可能接受模型对链接、代码、配置、HTML、模板变量或 `.pages` 结构的修改，请仅在能接受并人工复核这些风险时使用。

## 黑名单

在中文源目录创建 `.translate-blacklist`：

```text
# 目录前缀
integrations/

# 精确文件
billing/internal.md

# 通配符
drafts/*.md
```

黑名单在生成多语言任务前统一应用。除非显式使用 `--delete-removed-translations`，已有译文不会因为加入黑名单而被删除。

## 安全说明

- 已存在的语言目录会原地复用，不会删除重建。
- 只有新译文通过结构和语言校验后才替换旧文件。
- 翻译失败时 metadata 标记为 `failed`，下次自动重试。
- 目标语言目录不能等于中文源目录或位于中文源目录内部。
- `.mkdocs-translator`、旧 metadata、黑名单、日志和临时文件不会作为普通资源复制。
