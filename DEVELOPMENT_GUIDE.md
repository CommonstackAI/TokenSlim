# Smart Token Gateway 开发指导文档

> 基于 development_plans.md 方案一 | 最终对齐版 | 2026-03-11

---

## 1. 产品定位

Smart Token Gateway (STG) 是部署在 OpenClaw Gateway 和上游 LLM API 之间的 ASGI 代理服务。

### 核心价值
- 透明代理：所有请求自动经过压缩、缓存、预算检查
- 零代码改动：用户无需修改现有代码
- 成本优化：通过压缩和缓存降低 token 消耗 20-40%

### 解决的痛点
| 痛点 | 社区声量 | 案例编号 |
|------|---------|---------|
| Prompt 太长浪费 token | ⭐⭐⭐⭐⭐ | #27, #211-215 |
| 重复请求无缓存 | ⭐⭐⭐⭐ | #180-184 |
| 多 Agent 成本爆炸无控制 | ⭐⭐⭐⭐⭐ | #1-27, #66-84 |
| 成本不透明，超支无感知 | ⭐⭐⭐⭐ | #1-27 |

---

## 2. 部署拓扑

### 基本部署

OpenClaw Gateway 监听 18789 端口，配置 UNCOMMON_ROUTE_UPSTREAM 指向 STG 的 8404 端口。STG 接收请求后进行处理，然后转发到上游 LLM API（如 OpenRouter）。

### 与 UncommonRoute 共存

当需要与 UncommonRoute 共存时，请求链路为：
- OpenClaw Gateway (18789) → UncommonRoute (8403) → STG (8404) → 上游 API

UncommonRoute 先进行模型路由选择，STG 再对最终模型进行压缩、缓存和预算控制。

---

## 3. 请求处理流水线

### Stage 1: EXTRACT（提取指纹）
从请求中提取以下信息用于缓存匹配：
- 最后一条 user message
- system prompt 的 hash 值
- model 名称
- temperature 参数

### Stage 2: L1 CACHE（快速粗粒度缓存）
- 对最后 user message 进行 embedding（< 5ms）
- 查找条件：相同 model + 相同 system_hash + cosine 相似度 > 0.95
- 命中：直接返回缓存响应（stream 模式模拟 SSE）
- 未命中：继续下一阶段

### Stage 3: COMPRESS（渐进式 LLM 压缩）
压缩触发条件：messages 总 token >= 4096

渐进式压缩策略（多轮累积压缩）：

第一次压缩（当对话首次超过阈值）：
1. 从 messages 数组末尾往前扫描，保留最后 2 轮对话（可能是 1-4 条消息）
2. 剩余的所有消息（除了 system 和最后 2 轮）= 待压缩内容
3. 将待压缩内容存入 History Index（带 embedding）
4. 调用 qwen3.5-27b 生成摘要
5. 构建新的 messages = [system, "[对话摘要] ...", ...最后2轮]
6. 注入 _stg_retrieve_history tool

示例：
```
原始 messages（总计 5000 tokens，超过阈值）:
  [system]  "You are a helpful assistant..."
  [user]    "解释 CAP 定理"
  [assistant] "CAP 定理是..."（2000字）
  [user]    "举个实际例子"
  [assistant] "比如 DynamoDB..."（1500字）
  [user]    "那和 BASE 有什么关系"
  [assistant] "BASE 理论是..."（1800字）  ← 最近第2轮
  [user]    "总结一下"                    ← 最近第1轮

压缩后:
  [system]  "You are a helpful assistant..."
  [system]  "[对话摘要] 用户询问了 CAP 定理、实际案例（DynamoDB AP 选择）、以及 BASE 理论与 CAP 的关系..."（400 tokens）
  [assistant] "BASE 理论是..."（1800字）
  [user]    "总结一下"
```

后续压缩（对话再次超过阈值）：
1. 检测 messages 中是否已存在 "[对话摘要]" 标记
2. 如果存在：
   - 提取现有摘要（system message 中的 [对话摘要]）
   - 从末尾往前保留最后 2 轮
   - 中间部分（摘要之后、最后2轮之前）= 新的待压缩内容
   - 将新的待压缩内容存入 History Index
   - 调用 qwen3.5-27b 生成新摘要
   - 将新摘要追加到旧摘要后面：`[对话摘要] 旧内容... [对话摘要2] 新内容...`
   - 检查合并后的摘要长度
3. 如果合并后的摘要超过阈值（4096 tokens）：
   - 对整个摘要进行二次压缩
   - 压缩策略：对久远的对话摘要更加省略（假设模型不需要调用久远的原始数据），对最近的对话摘要保留更多细节
   - 确保最终摘要 ≤ 30% 阈值（1228 tokens）
4. 构建新的 compressed_messages

示例（第二次压缩）：
```
当前 messages（再次超过阈值）:
  [system]  "You are a helpful assistant..."
  [system]  "[对话摘要] 用户询问了 CAP 定理..."（400 tokens）
  [assistant] "BASE 理论是..."（1800字）
  [user]    "总结一下"
  [assistant] "总结..."（3000字）          ← 超过阈值
  [user]    "新的问题1XXX"
  [assistant] "新问题1的回答XXX"（2000字）  ← 最近第2轮
  [user]    "新的问题2XXX"                ← 最近第1轮

压缩后:
  [system]  "You are a helpful assistant..."
  [system]  "[对话摘要] 用户询问了 CAP 定理... [对话摘要2] 用户要求总结，讨论了新问题1..."
  [assistant] "新问题1的回答XXX"（2000字）
  [user]    "新的问题2XXX"
```

摘要长度控制：
- 首次压缩目标：原始 token 数的 30%
- 多轮压缩目标：合并后不超过阈值（4096 tokens）
- 二次压缩硬性上限：30% 阈值（1228 tokens）
- LLM 自行决定实际长度，但不超过上限

压缩成本预估：
- 计算方式：原始未压缩的 token 数 - 压缩后的 token 数
- 多轮压缩：始终与"完全不压缩"的原始 token 数比较
- 只有当预期节省大于压缩成本时才执行压缩

### Stage 4: L2 CACHE（精确细粒度缓存）
- 对压缩后的完整内容进行 embedding
- 查找缓存
- 命中：直接返回
- 未命中：继续

### Stage 5: BUDGET CHECK（预算检查）
- 预估 token 消耗和成本
- 检查四级限额：per_request / hourly / daily / session
- 超限：返回 429 + 剩余额度 + 重置时间
- 通过：继续

### Stage 6: FORWARD（转发）
将 compressed_messages 转发到上游 API

### Stage 6.5: TOOL INTERCEPT（工具拦截）
如果 LLM 调用了 _stg_retrieve_history：
- 拦截该 tool call（不转发上游）
- 用 query embedding 在 History Index 搜索最相关的原始消息
- 返回原始消息作为 tool result
- LLM 继续生成最终回复

### Stage 7: POST-PROCESS（后处理）
收到最终响应后：
- 解析 usage (prompt_tokens, completion_tokens)
- 写入 L1 + L2 缓存
- 记录两笔消费（压缩 + 正式调用）
- 注入 response header

---

## 4. 技术选型

| 组件 | 技术 | 理由 |
|------|------|------|
| 网关层 | Python + Starlette | 与 UncommonRoute 架构一致 |
| 压缩 LLM | qwen/qwen3.5-27b via OpenRouter | 便宜，和正式调用走同一个 upstream |
| Embedding | all-MiniLM-L6-v2（384 维，本地 ONNX） | < 5ms，零 API 调用 |
| 存储 | SQLite（缓存 + 消费记录 + History Index） | 单文件，零运维 |
| Token 计数 | tiktoken | 精确计数 |

---

## 5. 核心模块设计

### 5.1 Prompt Compressor（提示压缩器）

职责：
- 渐进式 LLM 驱动的对话历史压缩
- 支持多轮累积压缩
- 保留关键信息，删除冗余内容
- 生成摘要并注入检索工具

压缩系统提示词要点：
- 保留所有关键事实、决策、代码片段、技术细节和数据点
- 删除问候语、重复内容、填充词和确认信息
- 使用与对话相同的语言输出
- 为每个主要讨论主题包含 [turn_X-Y] 引用标签
- 简洁输出，仅使用必要的 token
- 结合用户最新命令，保留历史关键信息

渐进式压缩流程：

首次压缩（对话首次超过 4096 tokens）：
1. 统计 messages 总 token 数
2. 如果 < 4096 → 返回原始内容，不压缩
3. 从 messages 数组末尾往前扫描，保留最后 2 轮对话
4. 分割：old_messages（待压缩）+ recent_messages（最后 2 轮）
5. 将 old_messages 存入 History Index（带 embeddings）
6. 调用 qwen3.5-27b 生成 old_messages 的摘要
7. 构建 compressed_messages = [system, system("[对话摘要] ..."), ...recent]
8. 注入 _stg_retrieve_history tool 定义

后续压缩（对话再次超过阈值）：
1. 检测 messages 中是否已存在 "[对话摘要]" 标记（在 system message 中）
2. 如果存在：
   - 提取现有摘要内容（system message）
   - 从末尾往前保留最后 2 轮
   - 中间部分（摘要之后、最后2轮之前）= 新的待压缩内容
   - 将新的待压缩内容存入 History Index（追加）
   - 调用 qwen3.5-27b 对新的待压缩内容生成摘要
   - 将新摘要追加到旧摘要后面：`[对话摘要] 旧内容... [对话摘要2] 新内容...`
   - 检查合并后的摘要 token 数
3. 如果合并后的摘要超过阈值（4096 tokens）：
   - 对整个摘要进行二次压缩
   - 压缩策略：对久远的对话摘要更加省略（假设模型不需要调用久远的原始数据），对最近的对话摘要保留更多细节
   - 确保最终摘要 ≤ 30% 阈值（1228 tokens）
4. 构建新的 compressed_messages

摘要长度控制：
- 首次压缩目标：原始 token 数的 30%
- 多轮压缩目标：合并后不超过阈值（4096 tokens）
- 二次压缩硬性上限：30% 阈值（1228 tokens）
- LLM 自行决定实际长度，但不超过上限

成本计算：
- 节省计算：原始未压缩的 token 数 - 压缩后的 token 数
- 多轮压缩：始终与"完全不压缩"的原始 token 数比较
- 只有当预期节省大于压缩成本时才执行压缩

返回结果：
- compressed_messages: 压缩后的消息列表
- original_stored: 原始消息是否已存储
- compression_ratio: 压缩比率
- compressor_tokens_used: 压缩 LLM 消耗的 token
- compressor_cost: 压缩成本
- summary_regenerated: 是否进行了摘要再生成（多轮压缩标记）
- summary_compressed: 摘要本身是否被二次压缩

### 5.2 History Index（历史索引）

职责：
- Session 级别的原始消息索引
- 支持语义检索
- 生命周期跟随 session
- 存储所有原始消息和摘要内容

存储结构：
- session_id: Session 标识
- turn_id: 轮次标识
- role: 角色（user/assistant/system）
- content: 消息内容（包括原始消息和摘要）
- embedding: 消息的向量表示
- created_at: 创建时间
- is_summary: 是否为摘要内容（布尔值）

存储策略：
- 首次压缩：存储被压缩的原始消息
- 后续压缩：追加新的被压缩消息
- 摘要内容：也存入 History Index，标记 is_summary=true
- 摘要被二次压缩：旧摘要和新摘要都保留在 History Index 中

检索功能：
- 输入：session_id + query 字符串 + top_k
- 处理：用 query 的 embedding 在该 session 的原始消息里做 cosine 搜索
- 输出：最相关的 top_k 条原始消息（优先返回 is_summary=false 的消息）

清理功能：
- Session 过期时清除该 session 的所有索引

_stg_retrieve_history Tool 定义：
- 名称：_stg_retrieve_history
- 描述：从对话早期检索原始详细内容。对话历史已被摘要以节省 token。仅当摘要缺少回答所需的具体细节时才调用此工具（例如：确切的代码、具体数字、完整引用）。不要为一般上下文调用 - 摘要在大多数情况下已足够。
- 参数：query（字符串，描述需要从早期对话中获取的具体细节）

### 5.3 Semantic Cache（语义缓存）

两级缓存架构：

缓存指纹（CacheFingerprint）：
- model: 模型名称
- system_hash: 所有 system messages 拼接的 sha256
- temperature: 温度参数（未传则默认 1.0）
- top_p: top_p 参数（未传则默认 1.0）
- seed: 随机种子（未传则 None，None 之间互相匹配）
- tools_hash: tools JSON 的 sha256（排除 _stg_retrieve_history）
- response_format: 响应格式（"json_object" | "text" | None）

L1 缓存（快速粗粒度）：
- 只看最后 user message 的 embedding
- 命中条件：fingerprint 全部字段完全匹配 + cosine > 0.95

L2 缓存（精确细粒度）：
- 用压缩后的完整 messages 内容做 embedding
- 命中条件同 L1

存储功能：
- 同时写入 L1 和 L2
- 包含 embedding、fingerprint、response 和 metadata

tools_hash 计算：
- 对 tools JSON 序列化后计算 sha256
- 排除 Gateway 注入的 _stg_retrieve_history
- 未传 tools 则返回空字符串 hash

缺省参数处理：
- 未传的参数按默认值处理（top_p=1.0, seed=None, response_format=None）
- None 值之间互相匹配

### 5.4 Budget Guard（预算守卫）

四级预算控制：
1. per_request: 单次请求限额
2. session: Session 级别限额
3. hourly: 小时级别限额
4. daily: 日级别限额

检查流程：
- 按顺序检查：per_request → session → hourly → daily
- 任一超限 → 返回 BudgetResult(allowed=False, blocked_by=..., reset_in_s=...)
- 全部通过 → 返回 BudgetResult(allowed=True)

记录功能：
- record_type: "compression" | "completion"
- 两笔分开记录
- 包含：cost, model, session_id, timestamp

### 5.5 Analytics Collector（分析收集器）

请求记录（RequestRecord）包含：

压缩相关：
- compressed: 是否压缩
- original_tokens: 原始 token 数
- compressed_tokens: 压缩后 token 数
- compression_ratio: 压缩比率
- compressor_model: 压缩模型名称
- compressor_tokens: 压缩 LLM 自身消耗

缓存相关：
- cache_hit: 是否命中缓存
- cache_level: "L1" | "L2" | None
- cache_similarity: 相似度分数

检索相关：
- history_retrieved: LLM 是否调用了 _stg_retrieve_history
- history_retrieve_tokens: 检索注入的原始消息 token 数

预算相关：
- budget_blocked: 是否被预算阻止
- budget_blocked_by: 阻止原因

成本相关（分开两笔）：
- compression_cost: 压缩 LLM 成本
- completion_cost: 正式调用成本
- total_cost: 合计

延迟相关：
- gateway_latency_ms: 网关处理延迟
- compression_latency_ms: 压缩 LLM 耗时
- upstream_latency_ms: 上游 API 耗时

---

## 6. Streaming 策略

| 场景 | 行为 |
|------|------|
| 缓存命中 | 模拟 SSE stream 返回 |
| 无压缩，直接透传上游 | 正常 stream 透传 |
| 有压缩，上游正常返回 | 正常 stream 透传 |
| 有压缩，LLM 调用了 _stg_retrieve_history | 降级非流式，等完整响应后一次性返回 |

降级时注入 header：
- x-stg-stream-degraded: true
- x-stg-stream-degraded-reason: history_retrieval

---

## 7. Response Header 注入

所有响应都会注入以下 header：

基本信息：
- x-stg-request-id: 请求 ID
- x-stg-session-id: Session ID

缓存信息：
- x-stg-cache: hit|miss
- x-stg-cache-level: L1|L2（命中时）
- x-stg-cache-similarity: 0.97（命中时）

压缩信息：
- x-stg-compressed: true|false
- x-stg-compression-ratio: 0.25（压缩到原来的 25%）
- x-stg-original-tokens: 12000
- x-stg-compressed-tokens: 3000
- x-stg-summary-regenerated: true|false（是否进行了多轮压缩）
- x-stg-summary-compressed: true|false（摘要本身是否被二次压缩）

成本信息：
- x-stg-compression-cost: 0.0003（压缩 LLM 成本）
- x-stg-completion-cost: 0.0049（正式调用成本）
- x-stg-total-cost: 0.0052

其他信息：
- x-stg-history-retrieved: true|false（是否触发了原始消息检索）
- x-stg-budget-remaining-hourly: 0.85
- x-stg-stream-degraded: true|false（是否降级为非流式）
- x-stg-stream-degraded-reason: ...（降级原因）

---

## 8. Session 与请求追踪

### sessionKey（统一主键）

来源优先级：
1. x-openclaw-session-key header（OpenClaw 原生）
2. x-session-id header（通用）
3. messages 首条 user message sha256[:8]（兜底）

绑定范围：
- 缓存 L1/L2 的 lookup scope
- History Index 的存储和检索 scope
- Budget session 级限额的累计 scope
- Analytics 的 session 维度聚合

### request_id（单次请求追踪）

生成方式：uuid.uuid4().hex[:12]

用途：
- 双笔计费关联（compression + completion 同一个 request_id）
- Response header: x-stg-request-id
- Analytics 单条记录标识

---

## 9. 配置文件结构

配置文件采用 JSON 格式，包含以下部分：

### upstream（上游配置）
- base_url: 上游 API 地址
- api_key: API 密钥

### compressor（压缩配置）
- base_url: 压缩 LLM API 地址
- api_key: API 密钥
- model: 压缩模型名称（默认 qwen/qwen3.5-27b）
- threshold_tokens: 压缩触发阈值（默认 4096）
- keep_recent_rounds: 保留最近轮数（默认 2）
- summary_ratio: 摘要比率（默认 0.3）
- summary_max_tokens: 摘要最大 token 数（默认 2000）

### cache（缓存配置）
- enabled: 是否启用缓存
- similarity_threshold: 相似度阈值（默认 0.95）
- ttl_minutes: 缓存 TTL（默认 60 分钟）
- max_entries: 最大缓存条目数（默认 10000）
- only_temperature_zero: 是否仅缓存 temperature=0 的请求

### budget（预算配置）
- per_request: 单次请求限额（null 表示不限制）
- hourly: 小时限额
- daily: 日限额
- session: Session 限额

### history_index（历史索引配置）
- enabled: 是否启用
- follow_session_lifecycle: 是否跟随 session 生命周期
- storage_path: 存储路径（默认 ~/.smart-token-gateway/history.db）
- file_permission: 文件权限（默认 0600）

### gateway（网关配置）
- port: 监听端口（默认 8404）
- host: 监听地址（默认 127.0.0.1）

### models_pricing（模型定价）
静态配置，手动维护各模型的 input/output 价格（每百万 token 的美元价格）

---

## 10. 项目文件结构

smart-token-gateway/
├── stg/
│   ├── __init__.py
│   ├── proxy.py              # ASGI 代理主入口 + Stage 编排
│   ├── compressor.py         # LLM 压缩（qwen3.5-27b 调用）
│   ├── history_index.py      # 原始消息索引 + _stg_retrieve_history 拦截
│   ├── cache.py              # 两级语义缓存（L1 + L2）
│   ├── budget.py             # 四级预算控制
│   ├── analytics.py          # 请求记录 + 统计（双笔计费）
│   ├── embedding.py          # 本地 embedding（all-MiniLM-L6-v2）
│   ├── token_counter.py      # Token 计数（tiktoken）
│   ├── config.py             # 配置加载
│   └── types.py              # 数据类型定义
├── tests/
│   ├── test_compressor.py
│   ├── test_history_index.py
│   ├── test_cache.py
│   ├── test_budget.py
│   └── test_e2e.py           # OpenClaw debate/workflow 端到端测试
├── pyproject.toml
└── config.json

---

## 11. 依赖项

核心依赖：
- httpx>=0.27: 异步 HTTP 转发
- uvicorn>=0.30: ASGI server
- starlette>=0.38: ASGI 框架
- tiktoken>=0.7: Token 计数
- sentence-transformers>=3.0: 本地 embedding（~90MB 模型）
- numpy>=1.26: cosine similarity

---

## 12. 全部对齐决策

| # | 决策项 | 确认值 |
|---|--------|--------|
| 1 | 压缩方式 | LLM 摘要（qwen/qwen3.5-27b） |
| 2 | 压缩 LLM endpoint | 与用户相同的上游 API（OpenRouter），独立配置项 |
| 3 | 压缩触发阈值 | messages 总 token >= 4096 |
| 4 | 保留最近轮数 | 2 轮（最后 4 条 user/assistant 消息） |
| 5 | 摘要 max_tokens | min(original_tokens * 0.3, 2000)，LLM 自行决定实际长度 |
| 6 | 压缩成本承担 | 用户承担，分开两笔记录 |
| 7 | 流水线顺序 | 两级缓存（L1 在压缩前，L2 在压缩后） |
| 8 | 缓存相似度阈值 | cosine > 0.95 |
| 9 | 缓存 TTL | 60 分钟 |
| 10 | Streaming 缓存命中 | 模拟 SSE stream 返回 |
| 11 | 端口 | 8404 |
| 12 | 第一版形态 | 独立 proxy，后续包装 OpenClaw Plugin（JS bridge + Python） |
| 13 | 原始消息检索 | 注入 _stg_retrieve_history tool，LLM 按需调用，prompt 明确"除非必要才调用" |
| 14 | History Index 生命周期 | 绑定 sessionKey，session 过期则清除 |
| 15 | 检索 tool 名称 | _stg_retrieve_history（不易冲突前缀） |
| 16 | 计费展示 | 分开两笔（compression + completion） |
| 17 | 拦截层级 | 拦截 OpenClaw Gateway 所有流量，非 /v1/chat/completions 透传 |
| 18 | 与 UncommonRoute 共存 | UncommonRoute (8403) → STG (8404) → 上游（STG 拿到最终模型名） |
| 19 | Session 主键 | sessionKey 统一：缓存主键 + History Index 主键 + Budget session 级限额 |
| 20 | 请求追踪 | request_id（STG 自生成 uuid hex 12 位），用于单次追踪 + 双笔计费关联 |
| 21 | Session 解析优先级 | x-openclaw-session-key → x-session-id → messages 首条 user hash 兜底 |
| 22 | Tool 注入范围 | v1 仅支持 OpenAI chat completions 风格 tools；Responses API / 其他方言不注入，只做压缩 |
| 23 | Streaming 降级 | 压缩后触发 _stg_retrieve_history 时降级非流式，header 标注 x-stg-stream-degraded |
| 24 | 缓存命中维度 | model + system_hash + temperature + top_p + seed + tools_hash + response_format + prompt embedding |
| 25 | tools_hash 计算 | sha256(tools JSON 序列化)，排除 _stg_retrieve_history |
| 26 | 缺省参数缓存 | 未传的参数按默认值处理（top_p=1.0, seed=None, response_format=None），None 互相匹配 |
| 27 | 计费模型 | v1 静态 models_pricing 配置，不做实时价格同步，精确账单以上游为准 |
| 28 | History Index 存储 | 默认开启，本地 SQLite（~/.smart-token-gateway/history.db），权限 0600 |
| 29 | History Index 关闭时 | 压缩仍生效，但不注入 _stg_retrieve_history tool |

---

## 13. 拦截层级与路由策略

拦截策略：拦截 OpenClaw Gateway 所有流量

路由行为：
- /v1/chat/completions: 完整流水线（压缩 + 缓存 + 预算 + tool 注入）
- /v1/responses 等其他 chat API: 压缩 + 缓存 + 预算，但不注入 _stg_retrieve_history
- /v1/models, /health 等: 直接透传到上游，不处理

与 UncommonRoute 共存时的链路：
OpenClaw Gateway (18789) → UncommonRoute (8403) → STG (8404) → OpenRouter

---

## 14. 测试场景

基于真实 OpenClaw 场景：

| 场景 | 来源 | 测试重点 |
|------|------|---------|
| ClawHub Bot Debate（案例 #66-67） | OpenClaw 原生 skill | 压缩（每轮累积上下文）+ L1 缓存（同辩题重跑） |
| ClawHub Automation Workflows（案例 #72, #75） | OpenClaw 原生 skill | 预算控制 + 多步 token 追踪 |

---

## 15. 开发计划

| 阶段 | 内容 | 工时 |
|------|------|------|
| Week 1 | proxy.py 骨架 + config + types + token_counter | 2 天 |
| Week 1 | budget.py + analytics.py（双笔计费） | 2 天 |
| Week 1-2 | embedding.py + cache.py（L1 + L2 两级缓存） | 3 天 |
| Week 2 | compressor.py（qwen3.5-27b 调用 + 摘要生成） | 3 天 |
| Week 2-3 | history_index.py + _stg_retrieve_history tool 拦截 | 3 天 |
| Week 3 | proxy.py Stage 编排串联 + response header 注入 | 2 天 |
| Week 3 | 端到端测试（Debate + Workflow 场景） | 2 天 |

---

## 16. 预期效果

- 用户 token 成本下降 20-40%（压缩 + 缓存联合）
- L1 缓存命中率 15-30%
- 压缩后 input tokens 减少 40-70%（对长对话）
- 原始消息检索命中准确率 > 90%

---

## 17. 计费声明（v1）

- 静态 models_pricing 配置，手动维护
- 用于 Gateway 侧的预算控制和成本展示
- 不保证与 OpenRouter 实时账单 100% 对齐
- 精确账单以上游 provider 为准

---

## 18. 实现注意事项

### 18.1 安全性
- History Index 存储文件权限必须设置为 0600
- API key 不得记录到日志
- 敏感信息不得出现在 response header

### 18.2 性能
- Embedding 计算必须 < 5ms
- L1 缓存查询必须 < 10ms
- 压缩决策必须在 100ms 内完成

### 18.3 可靠性
- 压缩失败时降级为不压缩
- 缓存失败时降级为直接转发
- 预算检查失败时默认允许通过（fail-open）

### 18.4 可观测性
- 所有关键操作必须记录到 analytics
- 异常情况必须记录详细日志
- Response header 必须包含完整的处理信息

---

## 19. 后续演进方向

### v1.1 计划
- 动态模型定价同步
- 更多压缩策略（extractive summarization）
- 缓存预热功能

### v2.0 计划
- 封装为 OpenClaw Plugin（JS bridge + Python）
- 支持更多 LLM API 方言
- 分布式缓存支持

---

## 附录：关键术语

- STG: Smart Token Gateway
- L1 Cache: 一级缓存（粗粒度，基于最后 user message）
- L2 Cache: 二级缓存（细粒度，基于完整压缩后内容）
- History Index: 历史索引（存储原始消息用于检索）
- sessionKey: Session 统一主键
- request_id: 单次请求追踪 ID
- CacheFingerprint: 缓存指纹（用于精确匹配）
- _stg_retrieve_history: 注入的检索工具名称

