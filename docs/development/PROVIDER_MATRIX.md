# ENV-02 · MVP Provider Matrix

状态：用户已确认 provider 方向；账户、型号、额度、真实适配器和性能仍需逐项验证。

## 决定

```text
主 LLM ----------┐
图片生成 ---------├── OpenAI family
D-M 实际读图 -----┘   carrier: codex_native | gateway | openai_api

ASR ---------------- Google Cloud Speech-to-Text V2
TTS ---------------- Google Cloud Text-to-Speech

Input/Output Decision -- JEV/TypeSafe（保持 G05 当前路线，不由本次决定更改）
```

## 设计含义

1. OpenAI 三项能力共享供应商家族，但不共享“已经验证”的状态；分别保留 model selection、错误、usage 与能力探测。
2. `codex_native` 是开发默认 carrier，`openai_api` 是显式备选；出现 key 不会自动切换，也不会自动允许付费。
3. ASR/TTS 两项都走 Google Cloud，但保持独立 capability 与 adapter，避免未来更换其中一项时重写另一项。
4. D-M 必须读取实际待展示图像；图片生成成功、prompt 符合或生成器自述都不能替代 D-M。
5. JEV 是第六个逻辑判断能力，不在“另外两个 Google”里。若未来为减少供应商将其迁移到 OpenAI structured-output，需要新变更记录和中文质量基线。

## 配置来源

开发 profile 明确：

```toml
[services.routes]
text = "codex_native"
image = "codex_native"
vision = "codex_native"

[services.speech]
asr_provider = "google_cloud"
tts_provider = "google_cloud"
```

运行时仍默认 Mock；这些字段只决定 live adapter 被实现后应选择的 Provider 家族。
