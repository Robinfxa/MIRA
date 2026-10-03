# STARTUP-01 离线启动与安装包

范围：工具启动与 wheel 资源可靠性，不改变 HTTP、Actor、provider、配置 loader 合同。
共同基点：`ebb578dde665c9c7269e4a64b508182680b2fa66`。测试 owner 为 tooling；package 块负责真实离线构建／安装验收；architecture、config、http、web 是消费者。开发只跑定向 RED/GREEN，集成 owner 负责 affected/full/release。
资源：合成临时配置、独立构建目录、已安装依赖和本机 loopback；不读私密 `.env` 或认证缓存，不安装依赖、不调用 live provider。不将自动 HTTP/静态资源检查称为真机、音频或人工验收。

### STARTUP01-001 有能力验证的解释器
Given 默认 `.venv` 不完整，而当前解释器可导入应用，When 启动，Then 使用已验证解释器。显式 `--python` 是唯一选择，失败不得静默换环境。探针有超时、不打印导入失败原始内容、不扫描任意开发虚拟环境目录。

### STARTUP01-002 显式安装与默认离线
Given 缺少运行依赖或编译工具，When 启动，Then 有界退出 2 并给出显式安装命令，不自动安装。归档的 shell 脚本无需执行位即可通过 `sh scripts/dev` 调用。

### STARTUP01-003 密钥隔离的固定演示
Given 私密 dotenv、进程变量或默认配置指向 live，When 默认 demo 启动，Then 仍由唯一 loader 接收显式 mock/replay 与 fixture 设置，不读取 dotenv、不读取进程业务配置、不开启外部／付费调用或原文记录。端口与 replay 场景仅由受限 CLI 参数选择。

### STARTUP01-004 安装包包含工作台
Given 已编译前端，When 离线构建并安装 wheel 到临时目标，Then config、回放 fixtures、HTML、CSS、原创 SVG、worklet 和编译模块来自安装目录并可服务。缺少编译 JS 时 wheel 构建失败，不生成看似可用但无工作台的包。

验证收据写入 `docs/verification/startup-01/` 的唯一 run。新测试不替代旧 164 条产品验收；本 slice 不检查 live provider、真实设备和跨平台。
