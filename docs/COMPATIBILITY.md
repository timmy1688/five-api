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

模拟环境与真实 DeepSeek 渠道的压测见 [压测报告](BENCHMARK.md)。
