# ENV-01 开发服务环境

状态：用户要求的开发env实现切片；不是live MVP完成。基线foundation 0.3.0 / 产品架构v0.6。

## 范围与分块
沿用唯一config/loader，登记各API而不激活live工厂。新增env块；开发先单文件，影响面config/providers/actor/http，集成才full。无新OAuth网关、无账户池、无自动推理与付费。

### ENV01-001 配置与运行状态分开
登记text/image/vision/jev/speech，不自动启用任何live backend。
### ENV01-002 凭据各归其主
OpenAI、JEV、网关分别持有秘密；标准别名在原loader中分层归一，不歧义覆盖，不复用legacy通用key。
### ENV01-003 不披露秘密
TOML不能放秘密；repr、配置导出、诊断与错误不含秘密原值。
### ENV01-004 路由显式且受限
Codex原生/本机网关/标准API手工选择，无auto；网关仅数字loopback/v1，官方端点固定，未知参数拒绝。
### ENV01-005 声音单独配置
ASR与TTS locale分开，Google项目、quota项目、STT区域和TTS声线单列；ADC由供应商管理，不读取认证文件。
### ENV01-006 默认检查不访问网络
离线报告只说明字段准备程度；登录、目录、推理、产品adapter分别记录，不产生假live_ready。
### ENV01-007 元数据检查有双重准入
仅显式CLI请求且允许metadata、请求数有界、所选服务credential就绪时GET模型目录；无推理、无重试、无重定向、无环境代理。
### ENV01-008 结果只能证明本次操作
401/403/429/5xx/超时/非法或过大JSON分开；目录成功不是推理/生图/语音通过，响应正文不落日志。
### ENV01-009 私密初始化不覆盖
显式init创建空模板，已有文件/符号链接拒绝覆盖；POSIX文件权限0600；不自动登录、不读Codex/ADC缓存。
### ENV01-010 原流程与证据不漂移
离线分块纳管，历史与产品164条不改，真实探针不进入默认full/release；新文档解释待办和本地一次性准备。
### ENV01-011 Live拒绝说明真实边界
当应用工厂收到live provider配置时，仍必须明确拒绝且不能回退到Mock或付费API；错误文案应说明适配器已存在，但该工厂尚未完成所需的已验证live组合与显式准入。仅有环境配置字段不启用live启动，并提示执行离线配置检查、查看当前服务设置说明。
