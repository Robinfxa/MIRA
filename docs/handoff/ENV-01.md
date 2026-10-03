# 当前交接：ENV-01 / foundation 0.4.0

先读 `docs/development/API_ENV.md`。本次准备开发服务环境，不是替代FND03分块测试，也不是live产品完成。原T0不重新计50小时。

已实现：typed服务参数、原loader标准alias和secret边界、私密模板初始化、纯offline报告、显式有界目录GET、独立env测试块；application/HTTP wire/live factory不变。

`python tools/api_env.py init`不覆盖文件；`check`默认不联网，字段缺失退出2。metadata必须另行授权；真实key只在本机，不能发聊天。OpenAI备用key使用已提供的安全设置流程；Codex和ADC仍由原工具管理登录。

未完成：真实账号验证、Codex/网关/JEV/ASR/TTS/D-M适配、完整自主开发队列、真实音频与手机。不要把check或catalog成功标为live_ready。

下一步：一次收齐本机carrier及model、JEV、本地Google项目ADC/声线和预算；在权限范围明确后，按原ports/factory开发真实adapter。前端可并行做固定音频的真实可取消播放，不等待所有账户，严格区别fixture和live验收。

共享写面仍是config/loader、bootstrap、schemas、domain转换，由集成人收口。局部RED/GREEN，影响面并行，集成才full。不要继续开发第二套env系统或OAuth网关。
