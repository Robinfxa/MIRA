# 0.3.0 — FND-03 影响面选择与并行分块

## 0.4.1 · ENV-02 Provider Matrix

- Freeze main LLM, image generation and actual-image review to the OpenAI provider family, with Codex-native as the development default carrier and explicit API fallback.
- Freeze ASR and TTS provider fields to Google Cloud for the MVP.
- Keep JEV/TypeSafe as the existing DecisionBackend route; this update does not silently migrate semantic decisions into the main LLM.
- Make the speech provider decision typed, visible in environment inspection, and covered by targeted tests.

## 0.4.0 / ENV-01 · 2026-10-03

- 单一loader扩展typed服务参数、标准env别名、同层冲突检测与TOML secret拒绝。
- development空模板、私密init、离线字段检查、显式有界模型目录GET，均不注册live。
- 新env分块59测试；离线runner剥离常见服务凭据与Google配置；旧运行时/wire不变。
- 本地240 Python＋20 Node、TS及规格检查通过；发布尾检独立执行。真实账户/语音/生图未验。


- tests/quality.toml唯一登记9个离线块、2个发布块与影响规则。
- tools/check.py默认affected，精确lane、files、base、full/release和plan/matrix入口。
- 独立子进程/临时目录/前端构建/日志；失败、未运行、源码变更分开。
- SDD收集限定实际引用模块，spec变更反查关联行为块。
- 更新CI差分matrix、模板、开发约定与50小时计划；运行时合同和应用源码不改。

# CHANGELOG

## 0.2.0 · FND-02

新增受控generation fixture replay，不增加live能力。3个包内scenario、严格只读夹具引用、显式env/profile/factory装配、可注入异步等待。已有Actor/domain/wire继续承载许可、停止、回执。

新增规格及10项node-ID映射、开发模板、3对真实RED/GREEN日志、防覆盖记录器、离线wheel资源检查及loopback smoke。最终132 Python/20前端通过。package版本升级不等于消息协议升级；wire仍0.1.0-foundation。

保留0.1.0原报告/源架构；不声称新增语音、模型、图片、真实手机验证或远端CI。未改GitHub和用户电脑。

## 0.1.0 · FND-01（继承）

配置、工厂、分层、Mock控制闭环与73 Python/20前端测试。开发顺序没有在本轮补成TDD；作为基线复跑。
