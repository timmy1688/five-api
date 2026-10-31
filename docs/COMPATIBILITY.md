# 兼容矩阵与验证边界

版本：Five API 0.4.0，验证日期 2026-10-25。真实网络测试使用本地可控上游、MySQL 8、Redis 7，不调用付费 OpenAI/Anthropic 服务。内置模型目录不等于厂商接口认证。

| 接口 | 协议与覆盖 |
| --- | --- |
| /v1/chat/completions | OpenAI JSON、SSE、工具调用、用量与退避头 |
| /v1/completions、/v1/embeddings | OpenAI；文本和 token 数组输入回归 |
| /v1/responses | OpenAI JSON、命名 SSE、output_text、completed 用量 |
| /v1/messages | Anthropic 原生消息、tool_use、流式、缓存用量 |
| /v1/messages/count_tokens | Anthropic 或本地估算，不计费，仍受吞吐限制 |
| /v1/images/generations、edits、variations | OpenAI 兼容多模态回归，按张及可用 token 计量 |
| /v1/audio/speech | 二进制透传，输入按字符估算与定价 |
| /v1/audio/transcriptions、translations、/v1/rerank | multipart/JSON、按次及厂商用量 |
| /v1/videos、查询、content、删除、remix | 任务归属与相同上游 ID 隔离；Redis 任务状态需保留 |

| 客户端 | 实测版本与范围 |
| --- | --- |
| openai Python SDK | 3.37.0；真实 HTTP 的聊天、工具、流式、Responses 与认证错误 |
| anthropic Python SDK | 2.3.0；真实 HTTP 的消息、tool_use、文本流与 final usage |
| httpx | 0.28.1；API、断流、取消、超时、故障转移 |
| Claude Code、Codex、Cursor | 提供配置示例；本次未完成对应 CLI/桌面版本的端到端认证，不宣称已全面兼容 |

SDK 契约参考 [OpenAI Python](https://developers.openai.com/api/reference/python) 和 [流式响应](https://developers.openai.com/api/docs/guides/streaming-responses)。具体厂商、代理版本、Beta 或多模态扩展需要用实际部署另验。

网关仅在流式首包前切换；首包后断流不会重放已发出的回答。显式零用量与缺失用量分开处理；缺失字段估算，不能据此承诺和厂商账单完全一致。

模型健康探测调用实际文本推理接口。GPT/Claude 降智参考采用指令遵循、合成计算和强制工具参数检查，使用随机标记与数字减少缓存影响，保留每次证据与套件版本。它是小规模回归信号，无法鉴定真实型号，不能替代业务评测。[OpenAI 的评估说明](https://developers.openai.com/api/docs/guides/evaluation-best-practices) 同样强调生成结果的变化性和任务相关评测。

定时探测默认可用性 900 秒、降智参考 86400 秒，最多两个并行。DeepSeek 等文本模型参与可用性检测；仅 GPT/Claude 相关模型参与降智参考。非文本模型不参与这套合成探测。

## 压测

2026-10-31，8 核 16 GB 单机，网关按镜像默认运行 8 个进程。压测分两部分：模拟环境测网关自身能处理多少，真实环境测接入真实厂商后的效果。两部分每次测完都逐条核对扣费，全部一致。

### 模拟环境：处理上限

上游是本机的模拟服务，固定 5 毫秒返回，非流式，同时 64 个请求。网关、MySQL、Redis 和压测程序在同一台机器上。

| 网关进程数 | 16 个租户（次/分钟） | 1 个租户（次/分钟） |
|---|---|---|
| 1 | 1.1 万 | 7900 |
| 2 | 2.0 万 | 8400 |
| 4 | 1.9 万 | 8700 |
| 8 | 2.6 万 | 9100 |

- 多个租户时，进程数从 1 加到 2 能力接近翻倍；再往上受同机 MySQL 的限制，增长变慢。
- 单个租户约每分钟 9000 次封顶，不随进程数增加：同一租户的扣费要排队，保证余额不被扣穿。

### 真实环境：DeepSeek

渠道 `deepseek-v4-flash`，流式输出，每次回答约 1.2 秒，4 个租户。每一级并发先直连 DeepSeek、再经过网关，各发「并发数 × 4」次。官方账号有限流，并发控制在正常业务量内。

| 同时在线请求 | 成功（网关 / 直连） | 首字耗时中位（网关 / 直连） | 整体耗时中位（网关 / 直连） |
|---|---|---|---|
| 10 | 40/40 / 40/40 | 179 / 162 毫秒 | 1252 / 1168 毫秒 |
| 20 | 80/80 / 80/80 | 172 / 153 毫秒 | 1219 / 1101 毫秒 |
| 50 | 200/200 / 200/200 | 168 / 162 毫秒 | 1214 / 1208 毫秒 |

- 网关让首字只慢 6–19 毫秒，用户感知不到。
- 320 次调用每次只结算一次，按 DeepSeek 返回的 token 数和售价重算，每笔都一致，共 0.028 美元。

### 重新测试

```bash
cd backend
../.venv/bin/python -m scripts.benchmark --workers 1,2,4,8                          # 模拟环境
../.venv/bin/python -m scripts.real_benchmark --channel <渠道 ID> --model deepseek-v4-flash   # 真实环境，产生少量费用
```

两个脚本只用临时创建的租户和 Key，测完删除。真实环境脚本默认并发 10、20、50，最高允许 200，避免触发厂商限流。原始数据：[模拟环境](benchmarks/synthetic.json)、[真实环境](benchmarks/real-deepseek.json)。
