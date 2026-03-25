# 文档翻译增量缓存方案

## 一、目标

实现文档增量翻译，解决以下痛点：

1. **减少 token 消耗**：只翻译变更的内容，未变更部分直接使用缓存
2. **翻译质量**：通过段落合并保证上下文连贯性
3. **缓存复用**：最大化利用已有翻译缓存

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

### 缓存文件结构（v2）

```json
{
  "version": 2,
  "source_doc_hash": "sha256_of_full_source_doc",
  "last_translated": "2024-01-01T00:00:00",
  "paragraphs": {
    "a3f2c1": {
      "content": "段落1原文"
    },
    "b7e9d4": {
      "content": "段落2原文"
    },
    "93d1c2": {
      "content": "段落3原文"
    }
  },
  "merge_units": [
    {
      "hashes": ["a3f2c1", "b7e9d4"],
      "translation": "段落1译文\n\n段落2译文"
    },
    {
      "hashes": ["93d1c2"],
      "translation": "段落3译文"
    }
  ],
  "translation_memory": [
    {
      "source": "DataKit",
      "translation": "DataKit",
      "first_seen": "2024-01-01"
    }
  ]
}
```

**字段说明**：

| 字段 | 说明 |
|------|------|
| `version` | 缓存格式版本，当前为 2 |
| `source_doc_hash` | 整个源文档的 SHA256，用于快速判断文档是否变化 |
| `paragraphs` | 段落原文缓存，key 为内容 hash 前6位，value 只存原文 |
| `merge_units` | 合并翻译单元列表，按文档顺序存储 |
| `merge_units[].hashes` | 该合并单元包含的段落 hash 列表 |
| `merge_units[].translation` | 合并后的整体译文 |
| `translation_memory` | 术语翻译记忆，确保术语一致性 |

---

## 四、核心设计思想

### 1. 段落切分与合并分离

- **切分阶段**：按 `\n\n`（双换行符）切分，保持细粒度
- **合并阶段**：翻译时合并相邻小段落，保证上下文

### 2. 合并策略（200字阈值）

```
最小合并长度：200 字符
策略：贪婪合并，直到达到阈值或遇到可复用的 merge_unit
```

### 3. 缓存复用优先

当旧 merge_unit 中所有段落都未变化时，直接复用译文：

```
旧 merge_unit: [p0, p1, p2]
新段落: p0(未变), p1(未变), p2(未变)
→ 直接复用旧译文
```

### 4. 设计决策

| 决策点 | 选择 | 说明 |
|--------|------|------|
| 合并单元内段落变化 | 整体重翻译 | 保证上下文连贯性 |
| 新段落归入策略 | 归入相邻 merge_unit | 保持翻译连贯 |
| 小段落处理 | 允许单独翻译 | 优先保证缓存复用 |
| 译文存储 | 整体存储在 merge_unit | 不拆分，保持完整性 |

---

## 五、核心模块设计

### 1. 文档解析器 (`parser.py`)

```python
@dataclass
class Paragraph:
    content_hash: str      # 内容 SHA256 前6位
    full_hash: str         # 完整 SHA256
    content: str           # 原文内容
    paragraph_type: str    # normal | code | admonition | table

@dataclass
class PlannedMergeUnit:
    hashes: List[str]          # 段落 hash 列表
    merged_content: str        # 合并后的原文
    translation: str           # 译文
    need_translate: bool       # 是否需要翻译

def parse_file_incremental(file_path: Path) -> List[Paragraph]:
    """解析文档，返回段落列表"""

def plan_merge_units(
    paragraphs: List[Paragraph],
    old_merge_units: List[MergeUnit],
    min_length: int = 200
) -> List[PlannedMergeUnit]:
    """
    决策合并策略：
    1. 如果旧 merge_unit 中所有段落都未变 → 复用
    2. 否则 → 贪婪合并直到达到阈值
    """

def assemble_translation(planned_units: List[PlannedMergeUnit]) -> str:
    """组装最终译文"""
```

### 2. 缓存管理器 (`cache_manager.py`)

```python
@dataclass
class ParagraphCache:
    content: str  # 只存原文

@dataclass
class MergeUnit:
    hashes: List[str]      # 段落 hash 列表
    translation: str       # 整体译文

@dataclass
class CacheData:
    version: int = 2
    source_doc_hash: str = ""
    last_translated: str = ""
    paragraphs: Dict[str, ParagraphCache]
    merge_units: List[MergeUnit]
    translation_memory: List[Dict[str, str]]
```

---

## 六、完整翻译流程

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: 解析源文档                                                │
│ paragraphs = parse_file_incremental(source_file)                │
│ doc_hash = compute_doc_hash(paragraphs)                         │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: 判断是否需要翻译                                          │
│ if cache.source_doc_hash == doc_hash:                           │
│   → 直接使用缓存，跳过翻译                                        │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: 决策合并策略                                              │
│ planned_units = plan_merge_units(paragraphs, cache.merge_units) │
│                                                                 │
│ 策略：                                                          │
│ - 旧 merge_unit 完整复用 → need_translate = False               │
│ - 否则贪婪合并 → need_translate = True                          │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: 执行翻译                                                  │
│ for unit in planned_units:                                      │
│   if unit.need_translate:                                       │
│     unit.translation = translate(unit.merged_content)           │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: 更新缓存                                                  │
│ cache.paragraphs = {所有段落的 content}                          │
│ cache.merge_units = planned_units                               │
│ cache.source_doc_hash = doc_hash                                │
│ cache_manager.save_cache(relative_path, cache)                  │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: 组装译文                                                  │
│ result = "\n\n".join(mu.translation for mu in merge_units)      │
│ write_file(target_file, result)                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 七、场景示例

### 场景1：文档完全不变

```
旧 merge_units: [[p0, p1], [p2, p3]]
新段落: p0, p1, p2, p3 (全部未变)
结果: 直接复用所有 merge_units ✓
```

### 场景2：合并单元内段落变化

```
旧 merge_units: [[p0, p1], [p2, p3, p4]]
新段落: p0, p1_1(变化), p2, p3, p4
结果: 
  - [p0, p1_1] 重新翻译
  - [p2, p3, p4] 复用
```

### 场景3：删除段落

```
旧 merge_units: [[p0, p1], [p2, p3, p4]]
新段落: p0, p2, p3, p4 (p1 删除)
结果:
  - [p0] 单独翻译
  - [p2, p3, p4] 复用
```

### 场景4：新增段落

```
旧 merge_units: [[p0, p1], [p2, p3]]
新段落: p0, p1, p_new, p2, p3
结果:
  - [p0, p1] 复用
  - [p_new] 单独翻译（或与相邻合并）
  - [p2, p3] 复用
```

---

## 八、文件变更检测

```python
def needs_translation(source_file, cache_manager):
    cache = cache_manager.load_cache(relative_path)
    
    # 1. 缓存不存在 → 需要翻译
    if cache is None:
        return True
    
    # 2. 计算 hash
    paragraphs = parse_file_incremental(source_file)
    doc_hash = compute_doc_hash(paragraphs)
    
    # 3. hash 不同 → 需要翻译
    if cache.source_doc_hash != doc_hash:
        return True
    
    # 4. hash 相同 → 无需翻译
    return False
```

---

## 九、文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `mkdocs_translator/parser.py` | 新增 | 文档解析器，段落拆分，合并策略 |
| `mkdocs_translator/cache_manager.py` | 新增 | 缓存读写，MergeUnit 管理 |
| `mkdocs_translator/translator.py` | 修改 | 支持段落级翻译和术语表注入 |
| `mkdocs_translator/cli.py` | 修改 | 集成新翻译流程 |
| `mkdocs_translator/metadata.py` | 删除 | 已移除 |

---

## 十、调试日志

### 合并策略日志

```python
[plan_merge_units] Reused merge_unit: ['a3f2c1', 'b7e9d4']
[plan_merge_units] Stop merge at 2, next can reuse old merge_unit
[plan_merge_units] New merge_unit: ['e5f6a7'], length=150
[plan_merge_units] Total planned units: 3, need translate: 1
```

---

**方案版本**：v2.0  
**最后更新**：2026-03-24