# FND-02 交接（当前入口）

版本：基础工程0.2.0，基于0.1.0增量；v0.6产品架构不改。50h窗口沿用原T0，不重新计时。

## 已做

可运行ReplayGenerationBackend、严格随包脚本与3个scenario、配置profile/env/factory、只读fixture单点；规格／node-ID映射、真实3对RED/GREEN、异步事件屏障、开发模板、命令记录与本地Git历史。

最终本地132 Python＋20前端通过，另实跑loopback HTTP与离线wheel资源验证；继承73 Python全部保留，本轮新增59。当前UI仍为旧工作台，无需为本切片重做界面；浏览器布局和手机设备本轮未重测。

## 运行

默认 `./scripts/dev` 仍是mock。回放：

```bash
MIRA_PROFILE=replay MIRA_PROVIDERS__GENERATION=replay ./scripts/dev
# 可额外指定 MIRA_PROVIDERS__REPLAY_SCENARIO=delayed-photo 或 failed-tail
```

同时指定generation是为避免用户以前复制的.env中generation=mock覆盖profile。health的mode=mock是固定替身家族，不宣称live；场景名由本地配置决定。输入任意文字只启动固定scenario。

## 不要误解

回放是generation fixture，不是全会话event sourcing。没有真实Codex/JEV/ASR/TTS/摄像头/生图，原164条产品验收未改。没有自动付费或凭据读写，尚未修改Mac／GitHub。

## 下一项

基础组织现在够用，停止扩建方法论工具。按WP03/04在原ports/factory上接固定计划的可取消实际音频与角色执行器；并行WP01选定获准carrier。新代码先写最小spec与负例，但不复制整个FND02文件夹制造空模板。

共享写面owner仍是schemas.py、domain/transitions.py、bootstrap；同一时刻只让一个集成负责人修改。取消后旧内容不复活、实际回执才进历史、fixture不审批live均不可放松。
