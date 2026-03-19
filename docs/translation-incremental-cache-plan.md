# 文档翻译增量缓存方案

## 一、目标

实现文档增量翻译，解决两个痛点：

1. **减少 token 消耗**：只翻译变更的段落，未变更段落直接使用缓存
2. **翻译一致性**：通过相似段落匹配，保持前后翻译表达一致

---

## 二、缓存存储结构

### 目录布局

```
目标目录/
├── docs/                                    # 翻译后的文档
│   ├── guide/
│   │   ├── install.md
│   │   └── config.md
│   └── index.md
│
└── .translation-cache/                      # 隐藏目录，存放翻译缓存
    ├── guide/
    │   ├── install.md.json                  # 每个源文档对应一个缓存文件
    │   └── config.md.json
    └── index.md.json
```

**规则**：

- 缓存目录：目标目录下的 `.translation-cache/`
- 缓存文件名：`源文档相对路径.json`

---

## 三、数据格式

### 缓存文件结构

```json
{
  "version": 1,
  "source_doc_hash": "sha256_of_full_source_doc",
  "last_translated": "2024-01-01T00:00:00",
  "paragraphs": {
    "a3f2c1": {
      "source_content": "第一章 安装",
      "translation": "Chapter 1 Installation",
      "type": "normal"
    },
    "b7e9d4": {
      "source_content": "```python\nprint('hello')\n```",
      "translation": "```python\nprint('你好')\n```",
      "type": "code"
    },
    "c1d2e3": {
      "source_content": "!!! note\n    这是提示框",
      "translation": "!!! note\n    This is a note",
      "type": "admonition"
    }
  },
  "translation_memory": [
    {
      "source": "DataKit",
      "translation": "DataKit",
      "first_seen": "2024-01-01"
    },
    {
      "source": "采集器",
      "translation": "Collector",
      "first_seen": "2024-01-01"
    }
  ]
}
```

**字段说明**：

| 字段 | 说明 |
|------|------|
| `version` | 缓存格式版本，用于后续兼容 |
| `source_doc_hash` | 整个源文档的 SHA256，用于快速判断文档是否变化 |
| `paragraphs` | 段落级翻译缓存，key 为内容 hash 前6位 |
| `paragraphs[].type` | 段落类型：`normal` \| `code` \| `admonition` \| `table` |
| `translation_memory` | 术语翻译记忆，确保术语一致性 |

---

## 四、核心模块设计

### 1. 文档解析器 (`parser.py`)

**职责**：将 Markdown 文档拆分为段落，生成内容指纹

```python
class Paragraph:
    content_hash: str      # 内容 SHA256 前6位
    full_hash: str         # 完整 SHA256
    content: str           # 原文内容
    paragraph_type: str    # normal | code | admonition | table

def parse_file(file_path: Path) -> List[Paragraph]:
    """解析文档，返回段落列表"""

def parse_content(content: str) -> List[Paragraph]:
    """解析文本内容，返回段落列表"""

def split_text_paragraphs(text: str) -> List[str]:
    """按双换行符切分文本段落"""

def merge_short_paragraphs(paragraphs: List[str], min_length: int = 200) -> List[str]:
    """合并短段落，使用贪婪算法确保段落不少于 min_length 字符"""
```

**块识别规则**：

| 类型 | 识别方式 | 示例 |
|------|----------|------|
| 代码块 | ``` 或 ~~~ 包围 | ```python\ncode\n``` |
| admonition | !!! 或 ??? 开头 | !!! note\n 内容 |
| 表格 | 连续多行以 \| 开头且列数一致 | \| a \| b \| |
| 普通段落 | 非上述类型的文本，按空行切分 | 文本内容 |

**段落合并策略**：

为提高翻译质量和效率，对普通文本段落进行合并处理：

- **最小长度阈值**：200 字符
- **合并算法**：贪婪算法，从当前段落开始，若长度不足则依次合并后续段落，直到达到阈值或无更多段落
- **合并分隔符**：`\n\n`（保持段落间的视觉分隔）
- **目的**：
  1. 减少 API 调用次数，降低开销
  2. 提供更完整的上下文，提高翻译质量
  3. 避免短段落翻译时信息丢失

---

### 2. 缓存管理器 (`cache_manager.py`)

**职责**：管理缓存文件的读写

```python
class CacheManager:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir
        self.cache_dir = target_dir / '.translation-cache'

    def load_cache(self, source_rel_path: Path) -> Optional[CacheData]:
        """加载指定文档的缓存"""

    def save_cache(self, source_rel_path: Path, cache_data: CacheData):
        """保存缓存到文件"""

    def get_paragraph_translation(self, cache: CacheData, para_hash: str) -> Optional[str]:
        """获取段落翻译结果"""

    def save_paragraph_translation(self, cache: CacheData, para_hash: str, para: Paragraph, translation: str):
        """保存段落翻译结果"""

    def find_similar_paragraph(self, content: str, cache: CacheData, threshold: float = 0.6) -> Optional[Tuple[str, str, float]]:
        """在缓存中找相似段落，返回 (源文本, 译文, 相似度)"""

    def extract_terms_from_similar(self, source_text: str, translation: str) -> List[Tuple[str, str]]:
        """从相似段落中提取术语对照，返回 [(中文术语, 英文术语), ...]"""
```

**相似度算法**：使用编辑距离（Levenshtein），阈值 60%

**相似段落处理策略**：

当发现相似段落时，不再提供整段参考翻译，而是从中提取术语对照：

1. **问题背景**：提供整段参考翻译会导致模型直接复制参考译文，忽略当前输入内容的差异
2. **解决方案**：从相似段落中提取中英文术语对照，添加到术语表
3. **术语提取规则**：
   - 识别中文文本片段（2-20字）
   - 查找中文片段后紧跟的英文单词
   - 最多提取 10 个术语对

---

### 3. 翻译器扩展 (`translator.py`)

**职责**：调用 LLM 翻译，注入上下文和术语表

```python
class DocumentTranslator:
    def translate_paragraph(
        self, 
        text: str, 
        translation_memory: List[Dict] = None
    ) -> str:
        """翻译单个段落"""
        
    def build_translation_prompt(
        self, 
        text: str, 
        translation_memory: List[Dict] = None
    ) -> Tuple[str, str]:
        """构建翻译 Prompt"""
```

**增强 Prompt 模板**：

```python
SYSTEM_PROMPT = """你是一个专业的中文到英文技术文档翻译专家。

## 术语表（必须保持一致）
{terminology_list}

## 翻译要求
1. 必须与已有翻译保持术语一致
2. 保持 Markdown 格式完整

请翻译以下内容："""
```

**注意**：不再提供参考翻译，避免模型直接复制参考译文而忽略输入内容差异。术语一致性通过术语表保证。

---

## 五、完整翻译流程

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: 解析源文档                                                │
│ source_path → paragraphs: [p_0, p_1, p_2, ...]                  │
│ 每个段落包含: content, content_hash, paragraph_type             │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: 文档级 hash 比对                                          │
│ doc_hash = sha256(所有段落内容拼接)                               │
│ 如果 doc_hash == cache.source_doc_hash                          │
│    且 所有段落 hash 都在缓存中 → 跳过整个文档                     │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: 加载缓存                                                  │
│ cache = cache_manager.load_cache(doc_rel_path)                  │
│ 获取 translation_memory                                          │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: 对比段落，确定需要翻译的项                                │
│ for para in paragraphs:                                         │
│   if para.content_hash in cache.paragraphs:                     │
│     # 完全匹配，使用缓存                                         │
│     cached = cache.paragraphs[para.content_hash]                │
│     if cached.source_content == para.content:                   │
│       use_cache(para.content_hash)                              │
│     else:                                                        │
│       # 内容完全相同但 hash 碰撞（极小概率），重新翻译            │
│       need_translate.append(para)                               │
│   else:                                                          │
│     # hash 不存在，需要重新翻译                                  │
│     # 在缓存中找相似段落，提取术语添加到术语表                   │
│     similar = find_similar_paragraph(para.content, cache)       │
│     if similar:                                                  │
│       ref_source, ref_translation, similarity = similar         │
│       terms = extract_terms_from_similar(ref_source, ref_translation) │
│       for chinese_term, english_term in terms:                  │
│         update_translation_memory(cache, chinese_term, english_term) │
│     need_translate.append(para)                                 │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: 翻译需要更新的段落                                        │
│ for para in need_translate:                                     │
│   translation = translator.translate_paragraph(                 │
│     para.content,                                                │
│     translation_memory=cache.translation_memory                 │
│   )                                                              │
│   # 保存到缓存                                                   │
│   cache.paragraphs[para.content_hash] = {                       │
│     "source_content": para.content,                             │
│     "translation": translation,                                 │
│     "type": para.paragraph_type                                 │
│   }                                                              │
│   # 提取术语更新 translation_memory                             │
│   extract_and_update_memory(para.content, translation, cache)   │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: 按源文档顺序组装译文                                      │
│ result = ""                                                      │
│ for para in paragraphs:                                         │
│   if para.content_hash in cache.paragraphs:                     │
│     result += cache.paragraphs[para.content_hash].translation   │
│   else:                                                          │
│     # 这个分支理论上不会走到（已在 Step 5 处理）                 │
│     result += get_new_translation(para)                         │
│   result += "\n\n"  # 段落间空行                                 │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 7: 保存译文和缓存                                            │
│ write_file(target_path, result)                                 │
│ cache_manager.save_cache(doc_rel_path, cache)                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 六、特殊文件处理

### .pages 文件

- **不拆分**：整体作为单一段落处理
- **缓存 key**：整个文件内容的 hash（不是段落 hash）
- **翻译方式**：直接调用 LLM 翻译整体内容

---

## 七、文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `mkdocs_translator/parser.py` | 新增 | 文档解析器，段落拆分，块识别，段落合并 |
| `mkdocs_translator/cache_manager.py` | 新增 | 缓存读写，段落匹配，相似度计算，术语提取 |
| `mkdocs_translator/translator.py` | 修改 | 扩展支持段落级翻译和术语表注入 |
| `mkdocs_translator/cli.py` | 修改 | 集成新翻译流程，移除 metadata.json 依赖 |
| `mkdocs_translator/metadata.py` | 删除 | 已移除，改用 .translation-cache 判断文件变更 |

---

## 八、文件变更检测

### 检测逻辑

不再使用源目录的 `metadata.json` 和 `last-metadata.json`，改为直接读取目标目录的 `.translation-cache` 判断文件是否需要翻译：

```python
def needs_translation(source_file: Path, cache_manager: CacheManager) -> bool:
    relative_path = source_file.relative_to(source_path)
    cache = cache_manager.load_cache(relative_path)
    
    # 1. 缓存文件不存在 → 需要翻译
    if cache is None:
        return True
    
    # 2. 计算当前文档 hash
    paragraphs = parse_file_incremental(source_file)
    doc_hash = compute_doc_hash(paragraphs)
    
    # 3. 文档 hash 不一致 → 需要翻译
    if cache.source_doc_hash != doc_hash:
        return True
    
    # 4. 检查段落缓存完整性
    for para in paragraphs:
        if para.content_hash not in cache.paragraphs:
            return True
        cached_para = cache.paragraphs[para.content_hash]
        if cached_para.source_content != para.content:
            return True
    
    return False
```

### 优势

1. **简化存储**：只维护一份缓存数据，避免数据冗余
2. **一致性**：缓存数据与翻译结果一一对应
3. **可移植性**：缓存随目标目录一起迁移，无需额外文件

---

## 九、边界情况处理

| 场景 | 处理方式 |
|------|----------|
| 文档完全未变 | 文档级 hash 匹配，跳过 |
| 段落内容完全相同 | hash 匹配，直接使用缓存 |
| 段落内容有变更 | hash 不存在，翻译新段落 |
| 段落有变更 + 相似匹配 | hash 不存在，从相似段落提取术语添加到术语表，再翻译 |
| 新增段落 | 新 hash，翻译并新增缓存 |
| 删除段落 | 缓存保留，不影响其他段落 |
| 段落顺序变化 | 按当前顺序组装，hash 匹配到正确位置 |
| 代码块 | 作为整体段落翻译，LLM 保持代码不变 |
| LLM 翻译失败 | 记录错误日志，该段落不写入缓存 |

---

## 十一、术语提取规则

从翻译结果中自动提取术语：

```python
def extract_terms(source: str, translation: str) -> List[Dict]:
    # 1. 专有名词：连续英文（长度 >= 3）
    # 2. 技术术语：驼峰命名、缩写（API、SDK、HTTP）
    # 3. 括号对照：原文"A（B）" → 译文"A（B）"
    # 4. 首次出现的英文单词保留在译文中
```

---

## 十二、终端进度输出

### 1. Worker 进度行

每个 worker 一行，固定位置显示当前工作状态：

```
Worker 1: (2/5) install.md [p 3/12 ████████░░░░░░░░░░░░ 45%] (缓存:5/12)
Worker 2: (1/5) config.md  [p 0/8 ] 使用缓存
Worker 3: (5/5) .pages     [p -/- ] Done in 3.2s
Worker 4: (0/5) index.md   [p -/- ] 等待中...
```

**格式说明**：

| 元素 | 说明 |
|------|------|
| `(2/5)` | 当前文件索引 / worker 中总文件数 |
| `install.md` | 当前文档名 |
| `[p 3/12]` | 当前段落索引 / 总段落数 |
| `███████░░` | 段落级进度条 |
| `(缓存:5/12)` | 缓存命中数 / 总段落数 |

### 2. Total 进度行

最后位置显示总体进度：

```
Total: 50 files | Completed: 30 | Failed: 2 | Cached: 120 paras
```

**格式说明**：

| 元素 | 说明 |
|------|------|
| `Total: 50 files` | 需要翻译的总文件数 |
| `Completed: 30` | 已完成文件数 |
| `Failed: 2` | 失败文件数 |
| `Cached: 120 paras` | 使用缓存的段落总数 |

### 3. 进度条关闭顺序

翻译完成后，进度条按以下顺序关闭，确保终端输出整齐：

1. 先关闭所有 Worker 进度条（按 worker_id 从小到大）
2. 最后关闭 Total 进度行，保持在最底部

---

## 十三、调试日志

### 日志级别

- 默认日志级别：`DEBUG`
- 日志文件：`translation.log`

### 段落分割日志

```python
# parse_content 函数
[parse_content] Total parts after extraction: 3
[parse_content] Part 0: type=text, length=150
[parse_content] Part 1: type=code, length=80
[parse_content] Part 2: type=text, length=200
[parse_content] Split into 5 text paragraphs before merge
[parse_content] After merge: 3 text paragraphs
[parse_content] Added text paragraph 0: hash=a3f2c1, length=250, preview='# 第一章 安装\n\n本文档介绍如何安装...'
[parse_content] Total paragraphs: 4
```

### 段落合并日志

```python
# merge_short_paragraphs 函数
[merge_short_paragraphs] Input: 5 paragraphs, min_length=200
[merge_short_paragraphs] Before merge [0]: length=50, preview='# 标题\n'
[merge_short_paragraphs] Before merge [1]: length=100, preview='第一段内容...\n'
[merge_short_paragraphs] Merged 2 paragraphs into one, final length=252
[merge_short_paragraphs] Output: 4 paragraphs
```

### 相似段落匹配日志

```python
# 从相似段落提取术语
从相似段落提取了 5 个术语，相似度: 0.85
```

---

## 十四、待确认事项

无

---

**方案版本**：v1.2  
**最后更新**：2026-03-19