# 角色动画暂停与恢复

本切片基于 20261005-2030 交付源码，只修复代码角色在切回页面、关闭“减少动态效果”之后仍然冻结的问题。用户暂时采用的人物几何、衣装、表情、头发、局部颈根和相机轨迹保持原样；静态 Pixi 回退与语音播放架构不变。

页面隐藏或启用减少动态效果时，角色关闭嘴部运动并取消 RAF。两项限制全部解除后，当前仍有效的 idle/listening/thinking/speaking 状态恢复一个 RAF，不补算隐藏期间的时间。全局 Stop、Close、显式暂停和绘制失败仍有各自的阻止条件，页面恢复不会解除它们。新的有效非 idle 状态可启动下一次表现，包括该状态在页面隐藏时到达的情况。

暂停期间正在执行的举机动作仍被取消，保留最后成功绘制的位置；恢复环境只允许当前状态的呼吸、眨眼等运动继续，不会把取消的举机补成完成，不会生成成功回执。prepare/apply/transition 的既有提交顺序和会话许可复核保持不变。

## 动作幅度的现有控制位置

本次没有改变幅度。放大或减弱尚待明确选择，不能靠调大整个画布来修复生命周期。现有控制是源码中的独立通道，当前没有面向用户的幅度滑块：

- `code-native-vendor/character.js` 的 `stateAt`：`head` 为状态倾角加正弦摆头，摆动系数 0.45；`headX` 横向系数 0.35；`breath` 呼吸系数 0.45。倾角与横向位移不是同一单位，不应使用一个倍率盲目放大。
- 同一函数的 `eyeOpen`：4.6 秒周期与短暂眨眼窗口控制闭眼时序；`gazeX`、`brow` 分别控制视线和眉部，独立于眨眼。
- `mouth`：只在 speaking 阶段运行，范围 0.8–3.3，角频率 11.4。它是阶段正弦示意，没有读取 PCM 能量、音素或词时间；幅度变化不会使它成为音频同步口型。文字回复不会因显示字幕而开启 speaking。
- `strand`、`strand2`、`strand3`：错相头发摆动，系数分别 1.05、1.5、1.85；`hair.js` 有自己的约束和连接变换。头发、头颈和肩部接缝需要一起做视觉复验，不能只放大单个值。
- `body.js`：呼吸输入限制在 ±0.5，衣料呼吸缩放使用 0.008；正式组合使用 `rigidGrip`，相机/手指的独立闲置晃动不因此自动开启。受许可的举机由 `camera-motion.js` 和 renderer 的有限过渡单独控制。

路径均相对于 `apps/web/src/features/presentation/`。面部情绪由 `expression.js` 在当前嘴部几何上变形，保持现有 speaking 幅度；几何来源 hash 位于 `apps/web/public/scene/code-native/readiness-catalog.json`。本次仅更新该目录的 rendererSource hash。

## 验证边界

规格与可执行映射见 `specs/features/CODE-SCENE-01-semantic-renderer/spec.md` 的 CODE-SCENE-009。同一测试集合先在原实现产生真实行为失败，再由修复通过；证据独立保留在源码之外。测试使用生产 renderer、控制器和播放路径，Canvas、RAF、传输和 AudioContext 边界使用合成替身。Node 原生 TypeScript 转换不是严格 tsc、生产 bundle、真实浏览器绘制或用户设备音频验收；完整质量检查由集成负责人针对最终同树结果记录。
