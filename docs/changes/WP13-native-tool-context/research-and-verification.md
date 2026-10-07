# Luna 工具上下文：研究与本轮落实

公开资料实际查阅于2026-10-06 UTC。以下记录针对本项目的接口取舍；完整合并源码与验收结果以同包 START-HERE 为准。没有把私人对话送去检索或实时模型测试。

## 采用的主来源

- [OpenAI function calling 官方指南](https://developers.openai.com/api/docs/guides/function-calling)：明确工具何时应调用、何时不调用，用严格参数schema、匹配call_id的结果和有限工具轮。本项目仍保每轮至多一个操作及一次结果续答，没有因本轮研究增加请求次数。
- [官方 Codex 认证说明](https://learn.chatgpt.com/docs/auth)与[provider源码](https://github.com/openai/codex/blob/main/codex-rs/model-provider-info/src/lib.rs)：订阅身份和官方API计费路线分开。MIRA的订阅兼容适配器不等于公开API支持保证；不会因为失败自动切API。
- [官方协议模型源码](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/models.rs)：工具请求与结果需要正确关联。此处借鉴协议结构，不复制私有凭据或把未验证账户当作可用。

社区参考：[Open WebUI issue29630](https://github.com/open-webui/open-webui/issues/29630)，2026-09-04，报告中断流的call_id去重/回放问题；[OpenCode issue48441](https://github.com/anomalyco/opencode/issues/48441)，2026-09-11，报告回放provider标识问题。这些只用于设计回归反例，不作为MIRA实际故障的因果证明。

## 已落地的有界修正

原生请求现在在facts.character_story.chapter保留唯一当前章节投影，包含未相认阶段可达下一步；不重复添加第二份canon。成功、pending、held和失败继续依据程序结果与真实呈现回执。已看照片不等于已正式赠送，旧角色声明不能替代当前确认。

工具失败保留闭集具体原因；缺原因不编造供应商、道德或素材来源解释。当前图片任务pending优先于续答中没有新工具权限这件事，未来额度不足不被写成当前任务已经失败。看内搭/脱外套通过既有cream_inner_only衣装工具表达，保留内搭；不存在基于关键词直接执行的代码。

安全诊断只记录固定工具名、状态、原因、阶段和已观察到的回执类别，不记录参数原文、私人对话或图片内容。旧日志保持兼容。共享提示与原生说明已去重，未提高指令或请求上限。

## 验证边界

本轮有实际序列化Responses请求、合成HTTP、Actor与精确回执的离线回归，覆盖相认/确认/否认、早期照片重用、赠送前提、Stop与晚到结果、内搭切换、pending图片及未知错误。它们证明软件合同，不证明真实模型必然理解每句自然语言，也不证明账户图片资格或设备画面质量。
