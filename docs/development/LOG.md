# 开发日志（按追加记录）

本文件记录本轮真实操作，不重构既有FND-01的开发顺序。机器可核查命令在verification/fnd-02；时间取运行环境UTC，不据此猜测用户剩余小时。

## FND-02 / 准备

读取继承handoff、配置规范、50小时计划及实际源代码。解压v0.1.0至独立目录，原上传ZIP和原目录保持不变；在交付目录创建仅本地Git历史，未修改用户电脑或远端。

基线命令 `python tools/check.py`：73 Python、20前端均通过；合同无漂移、TS构建成功。证据 `../verification/fnd-02/runs/001-baseline/report.json`。尚未写本次实现。

随后先写FND-02 spec/proposal/design/tasks，选择有限生成夹具回放作为ports/factory/配置/TDD的打样。HTTP wire及业务状态转换保持不动。

## FND-02 / Cycle 1（规格→RED→GREEN）

通过已有load_settings/create_providers入口写9项测试，未先写replay实现；RED实际为8失败/1通过，原因是replay选择及REPLAY_SCENARIO尚不存在，不是依赖缺失或collection错误。见002-red-replay。

新增有限随包脚本、ReplayGenerationBackend和显式工厂分支；等待函数可注入，generate游标局部化。随后相同测试9项通过（003-green-replay），两次运行测试文件摘要相同。此时还未宣称所有资源负控完成。

## FND-02 / Cycle 2（负控RED→GREEN）

在Cycle1实现上添加29项资源与取消检查。实际RED为2失败/36通过：JSON parser静默接受重复顶层finish与嵌套fixture_id，导致失败／未知引用可能被末值覆盖。不是理论上猜测的失败，见004-red-script-hardening。

加入递归object-pairs重复键检查，并将非法编码／JSON／schema／深度错误统一为不含正文的资源错误；原38项测试全部通过（005-green-script-hardening）。首轮和本轮测试均未为迁就实现而修改断言。

## FND-02 / 重构与集成

共享固定fixture移到adapters/fixture_catalog.py并设为只读；生成器／审核器共同引用，旧mock模块仅保留兼容导入。测试同步屏障提到tests/support，避免测试模块互相依赖。domain、Actor及公共wire未改。

增加同一port对mock/replay的参数化测试，以及Event控制的停止、先回执后尾部失败、现有HTTP路径集成。006-refactor-and-integration实际120 Python通过。随后加入SDD node-ID映射校验及负例，007-quality-with-sdd实际130 Python、20前端通过。映射有10条需求；这个数字不是完整产品覆盖率。

## FND-02 / 工具复用补强与交付

评审发现最初规格检查器把requirement前缀写死FND02，不适合后续开发者复制；先加FND03测试，008实际2失败/10通过，再改为从feature ID派生前缀，009同12项通过。此轮仍保留真实失败日志，没有静默改成从未失败。

010验证旧run ID不能覆盖；011在临时source副本离线构建wheel，从wheel本身加载三份fixture成功。012与最终014均为132 Python/20前端通过，10条规格链接可收集，公共合同及TS检查通过。

013启动了真实loopback Uvicorn，走health/create/input/grants/receipt/stop/duplicate/delete，均通过；使用公开合成fixture，不是账户、声音、浏览器或移动设备验收。

完成规格/任务/开发模板、配置说明、CHANGELOG和handoff。原始v0.1.0 ZIP未改，产品G项和公共wire未变。源码仅在独立交付目录修改，Git只记录本地过程。当前应转入WP03/04真实可取消表现，不继续扩建基础工具。

## FND-03 / 用户要求与范围

用户要求TDD一开始按块并行，避免每轮全量。读取0.2.0源码确认check.py原来串行全量，规则也一律要求full；在新的0.3.0目录增量修改。旧包、FND02日志和v0.6原164条保持不变。

## FND-03 / 定向RED与GREEN

只跑19项架构基线（001）。先写FND03 spec、质量块清单、API形状和40项测试；002因行为未实现真实失败，003相同40项通过。实现是显式规则、标准库子进程、隔离目录，不增加xdist或云平台。

继续发现spec工具会collect全库：新增7项测试，004 RED后实现mapped-only收集，005 GREEN。影响面负例随后暴露spec改动只跑链接工具、漏跑行为消费者：006真实失败，再加入traceability反查，007通过。这不是只改文案。

## FND-03 / 按块实跑与收口复核

008 replay影响集合5块/100 Python通过，009 frontend两块/7 Python＋20 Node通过；未选块明确not_run。010初次集成full 180 Python＋20 Node通过，011仅跑package/smoke尾检，不重复full。

inventory复核发现`*_test.py`命名缺口，012新增负例确实失败，修复发现模式后013通过。由于变更测试选择器本身属于共享面，014再执行最终full：181 Python＋20 Node及18条SDD需求链接通过；015只复跑两项尾检，与014源码摘要相同。

四组红绿使用相同测试与命令；15份记录完整性核对通过。181含继承132＋新增49，不累计相加；前端仅调整测试导入路径，不改原20个断言。真实并行用双子进程屏障验证，单次耗时不当speed benchmark。

已更新SDD模板、贡献规则、PR、差分CI、50小时计划和交接。公开协议及apps/api/src、apps/web/src均与继承基线相同。没有真实模型/账号/浏览器/手机/远端CI操作；接下来回到产品WP03/04。

## ENV-01 / 开发API环境准备

用户要求设计开发env并准备API。读取FND03配置、工厂、测试分块与自主交接审计；新建foundation0.4.0独立工作目录。保留单一loader，不复制OAuth网关，不注册未实现live。GoogleSTT V2是本次建议开发起点，不反写为原ADR既定事实。

先写10条spec和配置测试，001 RED（11失败/15通过）后002相同26项GREEN。加入工具契约与28项测试，003真实RED，但参数显示名包含大payload；只缩短显示ID，004重新RED，005同组GREEN。原003输出保留，不伪称003/005完全相同。

后续负控发现压缩响应会被接受：006为1失败/31通过，拒绝压缩后007为32通过。再用真实离线子进程验证常见服务凭据被继承：008失败，修改quality环境筛选后009同组通过；这不替代OS文件隔离。

相关块先检查；最终一次full为240 Python＋20 Node、TS和28条规格链接通过。再只跑package/smoke尾检，源码摘要相同。所有外部HTTP为合成transport，本机loopback smoke单独执行。空模板check退出2且live_ready=false。汇总脚本曾误用source_digest及None计数字段，修正汇总读取后核验原报告；没有改原测试结果。

已添加typed服务配置、空模板创建、只读字段检查和显式目录GET；实际账户/ADC/JEV/语音/推理/生图未验证。打开可选OpenAI安全key设置UI，未接触key本身。未改用户Mac/GitHub，不重新计时。当前应转入产品音频与真实适配器任务。
