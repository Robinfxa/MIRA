# Luna角色工具与连续对话

直连入口默认使用真实 Responses function 工具：show_photo、generate_story_image、set_outfit、set_accessory、set_emotion、perform_action、set_scene、advance_story。Luna识别语义并提出一个封闭工具调用；程序核对当前会话/epoch、参数、素材readiness、输入/邀请来源、有限剧情前置状态和预算，再编译现有前端可消费的grant。正常路径不调用JEV，不伪造ALLOW；工具名字或台词本身也不是执行凭据。

普通聊天仍只调用一次Luna。工具轮最多一次工具、两次Luna，显式有限generation-requests时每次扣原总数；订阅文字默认无本机请求次数和轮数上限，官方API默认仍20次/20轮。Google语音、图片和默认连续聆听预算不随文字无限改变。合法首轮随附文字先呈现，再执行可选工具、提交相同call_id的function_call_output和一次续答。正常schema只声明正文；若收到合法正文加已识别的旧pose/scene/story/affect字段，正文保留、旧副作用held且不会执行。非法正文、损坏JSON、未知字段或工具协议错误仍失败。续答失败保留已准入的独立正文，并如实记录错误；没有自动重试、第三次续答或API回退。

工具结果反映实际pending、shown、held、failed、cancelled或unavailable。shown须有本次操作精确匹配的软件呈现回执；无ACK仍是pending，超时不意味着已显示或渲染失败。清除角色/拒绝邀请这类无视觉控制可返回applied，shown仍为false。慢图片可以在返回pending后继续到原时限；后来的事实进入下一轮上下文，不暗中再调Luna。

Stop、新输入和关闭取消旧工作。关闭照片只撤销当前照片/待呈现图片；已经显示过的历史保留为shown、visible=false，普通续答可继续且不能重新弹图。当前仍可见的固定照片可复用精确回执；换回其他已离开的控制目标要重新执行并取得回执。perform_action只抬起或放回角色手中的相机，不调用真实摄像头或拍摄。

advance_story的相认、赠图邀请和交付需要各自scene回执；show_photo仅构成照片预览，不能代替赠送。x.story/x.promise由Luna把当前获准canon叙成一个有界draft_cue，工具先真实呈现该字幕，再等待其回执并续答，不等续答去制造工具正在等待的字幕。普通聊天无需推进故事。

角色声明由Luna的typed current-input act解释，包括语境中的混合写法；应用只校验有限类型、原样当前输入和来源，不用短语白名单代替语义。此状态仅指虚构角色，不能授予现实身份、认证或记忆scope。相认仍须scene回执。若需确认，x.ask_role呈现问题后保留本会话短期引用；只有紧接着的新输入可用confirm_role引用该实际呈现的问题。同轮普通续答不使问题失效；后续无关对话、退出角色、Stop或Close消耗/清除它，未确认引用不写存档。

## 启用可变虚构画面

保留已使用的完整订阅、语音、env和登录参数。在--story基础上追加：

```text
--story-images
--authorize-story-image-data-to-openai
--authorize-story-image-subscription-usage
--authorize-story-image-custom-brief
```

最后一个是本版新增的范围选择：允许把本轮请求的有界虚构环境/物件描述发送给所选OpenAI图片服务。默认仍关闭，旧固定catalog同意不会自动扩大。brief最多600个Unicode字符，不接受参考图片、任意URL/路径、provider选择、权限、预算或读取私密库指令；完整聊天和记忆packet不会被自动附加到图片请求。已知密钥形状、私钥块等在本地拒绝；程序校验显式授权和brief范围，独立读图继续审核精确像素。结构校验并不能保证识别所有敏感内容。不要把私人资料或凭据当图片描述。

本切片从三个固定场景扩到可变虚构风景/环境/物件；不重绘角色、不声称新拍了真实照片或与用户共同旅行。生成图仍经历PNG规范化、精确字节绑定的独立读图和呈现回执。图片及读图优先沿用订阅兼容路线，API保留明确选择，不自动切换。

默认每进程至多一个图片任务、一次图片请求和至多一次独立读图，没有增加次数、字节或时长。取消/失败也可能消耗服务额度；重启本地计数不重置供应商用量。原MIRA登录可复用，过期时可能走原认证刷新；无需为新版本复制Codex认证或重新创建登录。订阅端点的工具/图片/读图账户资格仍未实测，软件检查不能证明账户支持。

可把原完整serve命令改成check核对声明；check不读取登录、不开麦、也不验证真实模型。声明中media_tools说明每工具轮最多2次模型请求，story_images显示custom brief范围是否明确启用。不要把configured_not_live_verified当账户验证成功。

## 兼容与对话

默认正文分块采用既有合法句边界的确定性分块，不等待JEV；语音保持完整cue与同一PCM队列。 工具首轮随附语音与工具续答若都包含speech，是两个独立cue，会最多消耗2次既有TTS预算，并按前一条尾块完成后再请求和播放后一条。字幕分块本身不增加TTS；普通单cue语音只请求一次。软件队列已用不同PCM尾块离线验证，真实声卡与听感仍需设备验收。

明确选择 --action-review-mode legacy_jev 才启用旧JEV动作/提案通路；构造直连adapter时相应设置native_character_tools=False。旧图片提议另外使用 --legacy-media-proposals，并且只在显式legacy_jev下使用；它与custom brief不可组合。所有兼容选择均是显式设置，不会因新工具失败自动回退。

自然角色对话可说世界观中的灯塔照片，来源元数据留在事实层；用户直接问现实来源时仍据实回答。生成图是想象画面，不能当作真实新拍照。重复问候不必每次重念身份或雨声设定；短追问应结合本轮之前的原话。近期第一人称视图把同一轮相同字幕/语音合并为一条引用，不改变原历史/回执，也不是新增永久记忆。跨重启记忆仍依既有独立存档、scope、配对和传输许可。

本轮验证均为合成离线协议和真实程序生命周期。实际模型自然程度、订阅工具支持、图片质量、设备显示及额外往返耗时仍待用户自行运行验证；没有在云端调用真实账户。


图片跨普通回复保留、当前job取消工具与一次订阅完成提示的精确边界见[后台图片](BACKGROUND_STORY_IMAGES.md)。完成提示与初始工具轮共用生成账本；API不新增自主调用，图片/TTS额度不扩张。
