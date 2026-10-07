# 旧剧情存档：显式检查、升级与撤回

普通临时 `--story` 会话不需要迁移。新版遇到可识别的旧持久存档时，
不会重新开局或改写数据库：配对会返回 `story_checkpoint_canon_upgrade_required`
及检查指引。未知版本、不同剧情图、损坏数据仍拒绝启动，不会自动修复。

此工具仅支持明确审核过的一对作者设定：canon 2 → canon 3，明确兼容磁盘
schema 5 和当前 schema 6；原四节点剧情图及其内容哈希完全相同。
旧 schema 5 的 dry-run 只在内存补充默认章节状态，升级仍保留 schema 5
的字段形状及完整原始备份；之后真正有新状态 revision 的普通保存才写 schema 6。
新增设定不能把旧 episode 改称新版共同经历。普通加载对已匹配 canon 的
schema 3–5 保持只读兼容；这不扩大本 canon 升级工具的范围，schema 3/4
仍需另行检查。未知 schema、损坏载荷或档案缺失继续拒绝，不猜测或越级迁移。

## 本机操作

先关闭使用这份存档的 MIRA 服务。数据库和目录继续要求本机用户私有；
数据库须位于源码目录之外。以下路径和scope要替换成原来的准确值。
工具不读取服务配置、不登录、不调用模型，不修改默认设置。以下命令在新版源码根目录运行，
使用已安装项目依赖的 `.venv/bin/python`；如果沿用外部项目环境，替换为该解释器的绝对路径。

```sh
.venv/bin/python tools/story_checkpoint.py dry-run \
  --db /你的私有目录/character.sqlite3 --scope 原来的scope \
  --authorize-story-checkpoint
```

检查结果包含版本、状态revision、保留episode数量、是否取消未呈现动作或
场景同意，以及 `checkpoint_digest`；不输出剧情正文、scope、回执内容或路径。
`dry-run`不会改动文件，也不会创建缺失数据库。最多检查4096条episode和4MiB
档案，超限会拒绝，绝不截断。先确认报告，再复制其完整digest显式提交：

```sh
.venv/bin/python tools/story_checkpoint.py commit \
  --db /你的私有目录/character.sqlite3 --scope 原来的scope \
  --authorize-story-checkpoint --expected-digest 上一步的完整digest
```

一次事务保留完整原checkpoint row及升级后row，再更新当前状态的版本绑定。
旧episode、回执、衣装与已确认进度保留；episode自身的canon版本保持原值。
未呈现grant会取消，不能成为已发生经历；场景同意也不从旧RAM内容重建。
再次加载使用原有重入规则，新的回执才可产生新episode。相同提交重试是幂等的。
原row及迁移时间保存在同一私有数据库的只追加历史中，不进入模型上下文。
本工具不是数据库备份替代品；现有备份继续保留。

## 撤回条件

只有升级后尚未新增进度、checkpoint和episode档案都未改变时才允许撤回。
先保持服务关闭，再预览及提交：

```sh
.venv/bin/python tools/story_checkpoint.py rollback-preview \
  --db /你的私有目录/character.sqlite3 --scope 原来的scope \
  --authorize-story-checkpoint
.venv/bin/python tools/story_checkpoint.py rollback \
  --db /你的私有目录/character.sqlite3 --scope 原来的scope \
  --authorize-story-checkpoint --expected-digest 撤回预览的完整digest
```

撤回逐字段恢复原checkpoint row，并保留升级与撤回两条记录；原episode表不变。
撤回后用对应旧版本应用重入，未呈现grant仍受旧版重入取消规则约束。
为了保持范围明确，同一迁移ID只允许一次升级及一次撤回，撤回后不会再次升级。
如果已恢复使用并产生新进度，撤回会拒绝覆盖它；原始row仍保留供另行审查。

当前证据只覆盖合成临时SQLite和离线HTTP/Actor，没有打开或迁移真实用户存档，
没有证明用户实际看见、听见或理解。旧版启动本身不会因为这份工具获得新功能。
