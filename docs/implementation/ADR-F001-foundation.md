# ADR-F001：基础工程实现组织

状态：在用户授权“开始最基础架构搭建”内采用的实施选择；不是新产品G项。
基础：架构／开源复用 v0.6、50小时计划。源架构保持历史字节。

## 决定

后端 Python 3.11+（本轮实测3.13.5）＋FastAPI；领域为纯 dataclass／纯转换；
应用通过 Protocol 消费生成、审核、诊断端口；适配器在 composition root 显式装配。
选择 Python 是为语音基础设施的后续接入保留直接路径，不代表现在已安装Pipecat。

前端严格 TypeScript＋原生ES模块和DOM；不提前引入React/Vue、状态库、打包插件和第二个开发服务。
现阶段工作台只需要这些能力，Charivo等renderer可通过EffectExecutor接入；以后换组件框架不改变HTTP与许可合同。
这不是因不存在现成前端库而自造渲染器；当前DOM实现明确是诊断替身。

后端部署与浏览器同源，FastAPI只服务index、public和编译dist。不上公网、不新增OAuth、账号池、后台管理或消息中间件。
状态由每会话一个SessionActor顺序归约，asyncio.Lock覆盖短同步转换，所有Provider await在锁外。
不引入全局service locator、动态反射工厂、万能BaseService或每个实体一个Repository。

## 配置与工厂

入口 `__main__`→`load_settings`→`create_app`→lifespan→`build_container`→`create_providers`。
配置是不可变对象，构造函数注入所需依赖；业务类不读取env、不根据provider名称if/else。
每个app实例有自己的Registry／Journal；关闭生命周期收回会话任务。

## 公共合同

HTTP DTO唯一编辑位置是 `entrypoints/http/schemas.py`。
OpenAPI与TS类型由 `tools/export_contracts.py` 导出，CI检查漂移。
wire标记 `0.1.0-foundation`，只承载固定Mock范围与瞬时DOM效果，不冒称语音v0.2完整协议。
按当前日期可用的工具最小实现了本项目DTO词汇导出器；不支持的schema会失败，后续复杂化优先替换为成熟codegen。

## 已实现语义子集

输入与停止代际、全局完整grant集合、冻结身份、同请求幂等、局部停止锁、旧结果失效、
有截止序号的迟到Mock回执、已收到回执的历史、正常封口与失败分开、内存配额和session释放。
此处不提供连续音频游标、语义范围算法、真实模型I/O判定、视频、素材加载或断线持久恢复。

## 存储与隐私边界

Registry与事件Journal当前均为内存：重启不恢复，过限拒绝，不暗中无限增长。
事件Journal是有界诊断记录而非可重建全部用户内容的持久event store；数据库／outbox在WP05另实现。
会话能力token仅浏览器内存持有，接口无全局session列表；不是生产账号鉴权。
stop/hide/delete与全资源清理的生产语义仍以原书为准，不把本次DELETE等同用户隐私全链删除。

## 非目标与真实取舍

HTTP轮询只用于基础联调；后续音频不可通过这条JSON轮询传输。
选择一个语音transport并接入原Actor，不另起一套自动回复主控。
`fixture`审核只接受固定受控候选，禁止与live生成混用。媒体／ASR／TTS端口声明不计作功能。
无需私人key能联调，不代表真实服务已经完整运行。
