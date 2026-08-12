# 中日、中韩 Prompt 与可观测性术语整理说明

## 1. 产物

正式实现后，完整的中英日韩术语对照和 Prompt 分别位于：

```text
mkdocs_translator/data/terminology.yml
mkdocs_translator/prompts.py
```

`terminology.yml` 是唯一内置词典来源，`prompts.py` 根据语言 profile 和当前语言有效词条动态生成 system prompt。`multilingual_prompts.py` 只保留对准备阶段导出名称的兼容引用，不再保存另一份词典。

当前词典包含 154 个规范化中文词条，每个词条都包含 `en`、`ja`、`ko` 三个值，三种语言均已接入正式翻译流程。普通词条使用固定译文；APM、RUM 这类概念词同时保存全称、缩写和使用策略。

## 2. 整理原则

- 优先采用 Datadog 日语、韩语官方技术文档中的稳定译法。
- Guance、DataKit、DataFlux Func、APM、RUM、SAML 等品牌名和行业缩写保持不变。
- 产品功能名优先使用可观测性行业术语，不做逐字翻译。
- UI 按钮和菜单使用简短名词或动作词，不翻译成长句。
- 同一概念不混用音译和意译。
- 宽泛普通词不进入强制词典，优先收录“日志查看器”“页面性能”等完整专业短语。
- APM、RUM 在每篇 Markdown 标题或正文首次出现中文全称时采用“全称（缩写）”，后续采用缩写；导航和其他紧凑 UI 只使用缩写。
- 日语正文使用正式、自然的 `です・ます` 文体；韩语正文使用正式的 `합니다` 文体。
- 日语使用自然的日文标点，韩语使用自然的韩文技术文档标点，不继承现有英文 prompt 的半角标点和复数规则。

## 3. 关键术语决策

| 中文 | 英文对照 | 日语 | 韩语 | 说明 |
| --- | --- | --- | --- | --- |
| 应用性能监测 | Application Performance Monitoring (APM) | アプリケーションパフォーマンスモニタリング（APM） | 애플리케이션 성능 모니터링(APM) | 首次出现用全称加缩写，后续/UI 使用 APM |
| 用户访问监测 | Real User Monitoring (RUM) | リアルユーザーモニタリング（RUM） | 실제 사용자 모니터링(RUM) | 首次出现用全称加缩写，后续/UI 使用 RUM |
| 指标集 | Measurement | メジャーメント | 메저먼트 | Guance/InfluxDB 数据模型实体，不是“测量值” |
| 时间线 | Time Series | 時系列 | 시계열 | 按现有英文语义处理为时序数据 |
| 排行榜 | Top List | トップリスト | 상위 목록 | 采用 Datadog 可视化名称 |
| 查看器 | Explorer | エクスプローラー | 탐색기 | 采用 Datadog Explorer 用语 |
| 异常追踪 | Incident | インシデント | 인시던트 | 按现有英文产品含义处理 |
| 静默 | Mute | ミュート | 음소거 | 采用监控告警领域用语 |
| 服务拓扑 | Service Map | サービスマップ | 서비스 맵 | 采用 Datadog APM 用语 |
| 顶层 Span | Top-level Span | トップレベルスパン | 최상위 스팬 | 与 root span 区分 |
| 服务顶层 Span | Service Entry Span | サービスエントリスパン | 서비스 엔트리 스팬 | 采用 Datadog APM 用语 |
| 页面性能 | Page Performance | ページパフォーマンス | 페이지 성능 | 避免把普通“页面”强制翻译成 RUM View |
| 日志查看器 | Log Explorer | ログエクスプローラー | 로그 탐색기 | 采用 Datadog Explorer 用语 |
| 链路追踪 | Distributed Tracing | 分散型トレーシング | 분산 추적 | 不再错误映射为 APM |
| 可用性监测 | Synthetic Monitoring | Synthetic モニタリング | 신서틱 모니터링 | 采用 Synthetic Monitoring 产品术语 |
| API 拨测 | API Tests | API テスト | API 테스트 | Synthetic 产品术语 |
| 多步拨测 | Multistep Tests | マルチステップ API テスト | 다단계 API 테스트 | 采用日、韩官方用语，不强行统一音译 |
| 作战室 | Warroom | ウォールーム | 워룸 | 事件响应领域通用名称 |
| 安全断言标记语言 | SAML | SAML | SAML | 使用标准缩写 |
| 付费计划与账单 | Plans & Billing | 料金プランと請求 | 요금제 및 청구 | 修正现有英文词条中缺少分隔符的问题 |
| 会话重放 | Session Replay | セッションリプレイ | 세션 리플레이 | RUM 行业用语 |

## 4. 对现有英文词表的规范化

现有 `prompts.py` 中有两类不适合直接迁移的数据：

1. 多个中文别名合并在一个词条中，例如 `相关配置/配置步骤`、`列表操作/相关操作`。
2. `付费计划与账单`、`观测云费用中心`、`用户访问 PV` 等条目缺少统一的冒号分隔。

正式词典已将别名拆成独立词条，并修复上述结构问题。`通知对象管理` 等重复项只保留一个规范定义。

## 5. 仍需产品侧最终确认的词语

以下名称属于 Guance 自身的数据模型或产品导航，不一定能从 Datadog 获得完全对应的官方译名。当前版本采用专业且语义一致的建议译法，接入生产前应由日、韩产品或本地化人员做最后确认：

| 中文 | 日语建议 | 韩语建议 | 原因 |
| --- | --- | --- | --- |
| 指标集 | メジャーメント | 메저먼트 | Guance 数据模型名称 |
| 自建节点 | セルフホストノード | 자체 호스팅 노드 | 保留“节点”产品语义，没有替换成 Datadog 的 Private Location |
| 智能巡检 | インテリジェントインスペクション | 지능형 점검 | Guance 功能名称 |
| 属性声明 | 属性クレーム | 속성 클레임 | 需结合实际 SAML UI 上下文确认是 Claim 还是 Attribute Statement |
| 告警策略管理 | アラートポリシー管理 | 알림 정책 관리 | Guance 自有导航名称，采用自然的本地化表达 |

## 6. 主要术语参考

- [Datadog 日语术语表](https://docs.datadoghq.com/ja/glossary/)
- [Datadog 韩语术语表](https://docs.datadoghq.com/ko/glossary/)
- [Datadog 日语服务地图](https://docs.datadoghq.com/ja/tracing/services/services_map/)
- [Datadog 韩语服务地图](https://docs.datadoghq.com/ko/tracing/services/services_map/)
- [Datadog 日语 RUM Explorer](https://docs.datadoghq.com/ja/real_user_monitoring/explorer/)
- [Datadog 韩语 RUM Explorer](https://docs.datadoghq.com/ko/real_user_monitoring/explorer/)
- [Datadog 日语 Synthetic Monitoring](https://docs.datadoghq.com/ja/synthetics/)
- [Datadog 韩语多步骤 API 测试](https://docs.datadoghq.com/ko/synthetics/multistep/)
- [Datadog 日语 SAML](https://docs.datadoghq.com/ja/account_management/saml/)
- [Datadog 韩语 SAML](https://docs.datadoghq.com/ko/account_management/saml/)
- [Datadog 日语计费](https://docs.datadoghq.com/ja/account_management/billing/pricing/)
- [Datadog 韩语计费](https://docs.datadoghq.com/ko/account_management/billing/)
