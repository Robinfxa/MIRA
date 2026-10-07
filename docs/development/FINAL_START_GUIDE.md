# MIRA 当前启动指南

本页与1810之后的完整体验整合候选对应。最终阶段、源码、release、独立验收及恢复证据以同包START-HERE为准。先按该包准确命令恢复到新目录，不混包或覆盖旧工作目录。

## 准备和离线体验

需要Python3.11–3.13、Node.js22.12+与npm。仅缺依赖时显式运行`python3 tools/bootstrap.py`；已有兼容解释器可替换下面的`.venv/bin/python`，不要搬迁旧虚拟环境，新目录也须有兼容前端依赖入口。

```sh
sh scripts/dev
```

同机打开http://127.0.0.1:8000。它是无私人密钥的固定Mock，不调用provider或真实麦克风。有声固定排练用`sh scripts/dev --profile rehearsal`；保留OFFLINE标识，声音为预录Flite/slt英文合成素材。端口冲突可加`--port 8123`。

## 复用原有配置

保留原.env、Google ADC与MIRA自己的登录，只沿用原绝对路径，不读取/复制其他应用认证。自选`--auth-store`继续用原路径，已有有效登录不用重新OAuth。完整命令如下，两个示例路径须替换为已有文件；保留已批准的数据/花费范围与任何更小的TTS/API/图片限额。

```sh
PYTHONPATH=apps/api/src .venv/bin/python tools/live_provider.py serve \
    --provider chatgpt_subscription --model gpt-6.1-sol --service-tier fast \
    --env-file /absolute/path/to/existing/.env --authorize-provider-data \
    --voice --adc-file /absolute/path/to/existing/application_default_credentials.json \
    --authorize-google-voice-data-and-spend --story \
    --story-images \
    --authorize-story-image-data-to-openai \
    --authorize-story-image-subscription-usage \
    --authorize-story-image-custom-brief
```

`luna_tools`默认协议不会把模型换成Luna，也不需要JEV。省略`--story-image-review-model`时独立读图跟随gpt-6.1-sol；可显式追加`--story-image-review-model gpt-6-luna`保留先前审核路线。Fast是请求等级，不是速度保证；不自动切API、换模型或重试。

把`serve`改为`check`只核查本机声明/必要元数据，不调用模型、不验证账户、不采集麦克风；它仍读取所选配置。制作交付只验证parser/help，没有读取真实配置。`live_provider.py`没有`--python`参数，使用已有解释器时直接替换命令开头。

## 默认与限制

订阅文字、本地聆听时长/发送/启动/续接次数、共享STT请求次数默认是真正None，不需`--local-unlimited`。STT仍计供应商用量且可能收费。显式`--stt-requests N`、`--listen-max-seconds N`、`--listen-max-utterances N`、`--listen-max-session-starts N`、`--listen-max-total-starts N`、`--listen-max-recognition-streams N`保留有限选择；文字仍有`--generation-requests N`、`--turns N`。

TTS默认20次/每次30秒，单STT RPC120秒，API默认20次生成/20轮；图片默认一任务/一次生成/至多一次独立读图、输出/累计8MiB、任务/生成/审核120/90/45秒。图片实际显示后的至多一次完成续答也计模型/TTS预算。时限、供应商配额、并发、背压、取消和Stop仍有效；重启本机计数不重置供应商账本。

浏览器由用户点击「开始自然对话」并允许麦克风。默认barge-in；明确保守模式保持。实际声音/字幕、完整声尾、回声和新语音中断须设备实测，建议耳机。Ctrl+C停止服务。

## 体验和剩余验收

图片跨普通回合与回复级打断保留；实际显示回执后才通知一次；精确取消和全局Stop防止迟到复活。夏禾相认后，同一次真实续答可说作者共同往事并邀赠照；一次接受后实际交付。不以内部说明、预览或口头宣称代替实际发生。

`--story`默认临时剧情。持久记忆、会话档案、checkpoint仍各自opt-in与配对，未自动保存真实用户经历。手机/电脑可按[双设备指南](PRIVATE-DEVICE-TESTING.md)使用已有受信HTTPS，两个临时会话独立、服务预算共享；当前不与私密库组合，不新增OS/证书/防火墙/隧道步骤，不绕过证书警告。

原PDF核心与用户追加范围见[当前验收](../mission/CURRENT-ACCEPTANCE.md)，唯一录制顺序见[实录指南](DEMO-RECORDING.md)。实际gpt-6.1-sol/Fast兼容、Google完整语音/中断、动态图片全链、手机与3–5分钟真实成片仍待同版本用户验收。
