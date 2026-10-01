# Serein for Harlan · 自建分支说明

上游：`https://github.com/Yinglianchun/Serein` · 分支基线：`5459ce42f616`
本分支：`https://github.com/otaku2244/Serein-for-Harlan`（公开）

改动的目的只有一个：**让新开一个窗口时不用再手打 `/resume`**，Serein 自己把续接资料带进去。

---

## 一、一次性切换（只做一次）

作用：把安装目录的更新来源，从「原作者仓库」改成「你自己的仓库」。

### 第 1 步：把本地代码推到 GitHub

远端已经配好了（`origin` = 你的仓库，`upstream` = 原作者仓库，后者要留着才能跟进上游更新），**只差推送**：

```
双击  E:\workbuddy\2026-09-21-20-44-34\Serein-fork\fork\push-to-fork.cmd
```

或者在任意终端里：

```bash
cd E:\workbuddy\2026-09-21-20-44-34\Serein-fork
git push -u origin main
```

推送时会要求登录 GitHub。推完网页上应能看到 4 个提交，其中两个是代码改动（`feat(gateway): auto-load continuation material on a new window`、`fix(gateway): replay automatic resume snapshots without the /resume command`），另外两个是 `fork/` 下的工具与文档。

> 这台电脑上没有任何 GitHub 凭据（无 `~/.git-credentials`、凭据管理器里也没有条目），所以推送必须由你本人完成。

### 第 2 步：切换到 fork

```
双击  E:\workbuddy\2026-09-21-20-44-34\Serein-fork\fork\serein-cutover.cmd
```

它会先把两个文件传到 VPS，再让你选：`1` 只体检（只读）、`2` 直接执行、`3` 放进 screen 执行。**先选 1**，看清报告再回来选 2 或 3。

等价的手工命令（不依赖批处理，最保底）：

```bash
cd E:\workbuddy\2026-09-21-20-44-34\Serein-fork
scp fork/cutover-to-fork.sh root@154.21.200.74:/tmp/serein-cutover.sh
scp scripts/upstream_update.py root@154.21.200.74:/tmp/serein-updater.py
ssh -t root@154.21.200.74 "bash /tmp/serein-cutover.sh --updater-file /tmp/serein-updater.py"                  # 体检
ssh -t root@154.21.200.74 "bash /tmp/serein-cutover.sh --updater-file /tmp/serein-updater.py --apply --screen" # 执行
```

**为什么要先把文件传上去、而不是在 VPS 上 `curl` 下载**：这个脚本默认从 `raw.githubusercontent.com` 取新更新器，而国内 VPS 经常访问不了这个域名（`github.com` 本身却通常是通的 —— 你现在能跑 `se → 1` 就证明通）。`--updater-file` 就是绕开它的通道。切换完成之后，日常更新走的是 `git fetch https://github.com/otaku2244/Serein-for-Harlan.git`，不经过 `raw.githubusercontent.com`，所以不受影响。

`--screen` 是让脚本在 VPS 上把自己放进 screen 再执行 —— 中途要停服重建，SSH 掉线不能把构建打断在半路。机器没装 screen 时它会自己降级成直接跑，并提醒你别关窗口。用 `--apply` 时建议带上。

想跳过数据备份（更新器默认会先备份一次运行数据）就在 `--apply` 后面再加 `--skip-data-backup`。

### 脚本的 6 个步骤各自做什么

| 步 | 动作 | 可回滚性 |
|---|---|---|
| 0 | 体检环境：root、安装目录、git、python3、取文件的方式 | 只读 |
| 1 | 读 fork 的 `main` 提交号；读不到就中止并给出推送命令 | 只读 |
| 2 | **关键门禁**：核对磁盘源码与 `update-state.json` 记录的哈希是否完全一致 | 只读 |
| 3 | 取回 fork 版更新器（`--updater-file` 指定就用本地文件，否则下载），校验它确实指向本 fork、且语法通过，才继续 | 只读 |
| 4 | 备份 `update-state.json` → 把 `.git` 改名摘掉 → 替换更新器 | 全部只改名/备份，可还原 |
| 5 | 跑 `se → 1`（程序化喂两个选项：菜单 1、备份 1） | 更新器自带源码 zip 备份 |
| 6 | 独立校验结果：台账、容器、新模块是否真的到位 | 只读 |

第 2 步是全脚本唯一的硬门槛。它和更新器内部的第一道校验是同一套逻辑，所以第 2 步过了，第 5 步就一定会被放行。**报 `DIRTY` 时脚本会停住并列出漂移的文件名**，不会硬闯。

第 6 步之所以必须存在：`manage.py` 的菜单在更新失败时也会以退出码 0 结束（它把异常吞掉后回到菜单，再因 stdin 耗尽而正常退出）。所以不能信退出码，只能回读台账和容器状态。

### 为什么要把 `.git` 改名

`/root/Serein/.git` 现在记录的是**原作者仓库的检出**。切换后磁盘上跑的是你的代码，`.git` 却还说自己是上游 —— 一旦将来 `update-state.json` 因故丢失（比如从数据备份恢复），更新器的第三道校验就会去问这个 `.git`，然后看到几百个「已修改」文件，直接把 `se → 1` 锁死，报错信息还完全指不到真正原因。

改名成 `.git.upstream-<时间戳>` 就断掉这个隐患，同时保留现场（想查上游原来长什么样，`cd` 进去照样能 `git log`）。

改完之后 `/root/Serein` 不再是 git 检出，**`se → 1` 是唯一的更新通道**，这也正是更新器设计的样子。

### 切换完成后的验证

1. 第 6 步应该全绿（12 项）。
2. 网页进 **设置 → 功能**，确认多出两个开关：`开窗续接` 和 `新窗自动续接`，后者默认关闭。
3. 两个都打开，然后**开一个全新窗口**发第一条消息。
4. 回设置里的观测列表看这一轮：状态应显示「本轮由新窗自动续接带入资料，没有执行自动召回」。
5. 在同一个窗口再发第二条 —— 续接资料应当仍在（复用在原锚点位置），且不会重新召回一遍。

---

## 二、日常：原作者更新后怎么跟进

在本地 fork 目录：

```bash
git fetch upstream
git merge upstream/main
```

本分支只在 7 个文件上有差异，其中 6 个是上游文件（冲突只会出在这几行的附近）：

| 文件 | 我改了什么 |
|---|---|
| `src/serein/chat_resume_auto.py` | 新增，全部逻辑都在这里 |
| `src/serein/api/chat.py` | 约 10 行：接线 |
| `src/serein/deployment.py` | `DEFAULT_FEATURES` 加一个键 `auto_resume: False` |
| `web/src/components/FeatureSettings.jsx` | 加一行开关说明 |
| `web/src/recallObservationOutcome.js` | 加一行状态文案 |
| `scripts/upstream_update.py` | 只改 `REPOSITORY` 常量一行 |
| `release-files.json` | 加一个文件名 |

合并时唯一要小心的：`release-files.json`。它是一份纯文件名清单，**上游新增的文件名和我加的那个都要留着**，别合丢。

合完先跑一次 `python3 fork/test_chat_resume_auto.py`。它会当场告出上游是否动了补丁依赖的接口（比如 `inject_retained`、快照字典的键、`_prepend_dynamic_context_to_user_message`）。全绿再推。

> `fork/` 目录（这一个测试、切换脚本、本文档）**不在** `release-files.json` 里，所以它只是跟着 git 走，更新器不会把它当成部署源码、也不会往 VPS 上写。部署源码始终是 529 个文件。

合完推上去，然后上 VPS 跑 `se → 1`，它会从你的 fork 拉全部源码并重建。之后 `se → 1` 永久自洽：

- 你的 fork 没有新提交 → 提示「当前已是 main 最新提交」，不重建；
- 有新提交 → 正常更新。

---

## 三、这项改动到底怎么工作

原设计里，Serein 只在两种情况下带续接资料：你手打 `/resume`，或者这个窗口以前 `/resume` 过（把当年的快照重放到原位置）。一个从没 `/resume` 过的窗口，第一条消息必然是冷启动。

现实问题是窗口 ID：Operit 这类客户端每次开新窗口都送同一个 `operit`，所以 Serein 眼里**只有一扇窗**，`operit` 里 `/resume` 过一次，新开的窗口它也不认。你的指纹方案正好解掉这个。

改动做的事：

1. **每次请求**都记一次「这个窗口是不是头一回见」。窗口 ID 够具体（客户端自己给的唯一值）就用它；不够具体（`main`、`operit`、空、`unknown`、`default`、`serein`）就退化成**第一条真实用户消息的指纹**。指纹相同 = 同一个窗口，不同 = 新窗口。这正是「换窗自动感知」。
2. 头一回见的窗口、且没有存档快照时，**加载 `/resume` 会加载的同一份资料**并注入。
3. 这一轮**跳过自动召回**，避免同一批近期事件被送两遍。
4. 资料会照 `/resume` 的规矩存下来，所以后面几轮继续在原位置带着，不会第二条就掉。
5. 手动 `/resume` 完全不受影响，任何窗口都照旧可用。

**每个窗口只自动带入一次。** 之后就算客户端把前面的历史裁掉、消息数变少，也不会重复触发。

**任何失败都退化成「不注入」**，绝不打断一次正常对话 —— 资料读不到、超长、锚点找不到，都只记一条 warning。

---

## 四、回滚

三种情况，从轻到重：

**只想关掉这个行为** —— 设置 → 功能，关掉 `新窗自动续接`。立刻生效，不动任何代码。

**想退回上游代码** —— 用第 4 步留下的三个现场：

```bash
cd /root/Serein/deploy
mv update-state.json.before-fork-<时间戳> update-state.json
cd /root/Serein
mv .git.upstream-<时间戳> .git
cp -a scripts/upstream_update.py.before-fork-<时间戳> scripts/upstream_update.py
se          # 再进菜单 1，它会从上游拉回原版源码并重建
```

**想精确退回切换前的那一版** —— 更新器在第 5 步自动留了源码 zip：

```bash
ls -lt /root/Serein/deploy/backups/source-*.zip | head -3
```

解压覆盖即可（zip 里的路径就是相对安装目录的路径）。

数据层面不用回滚：这次只换代码，数据库结构没动。切换前如果选择了「先备份再更新」，运行数据备份也在 `deploy/backups/`。

---

## 五、边界与已知行为

- **指纹兜底只在窗口 ID 不具体时生效。** 客户端如果送唯一 ID，Serein 就认 ID，两条长得一样的第一句话会被当成两个窗口 —— 这是想要的。
- **续接资料存在 `chat_resume_contexts` 表里，窗口 ID 仍然是客户端给的那个原始值**（比如 `operit`），每个窗口 ID 最多保留 8 份。这是上游原有机制，我没动。指纹只用来判断「这是不是新窗口」。
- **客户端把动态状态塞进 system 提示词时，第二轮可能匹配不上前缀**（`retained()` 用的是前缀摘要比对）。匹配不上就老老实实不注入，不会出错 —— 只是那一轮拿不到续接资料。Operit 的【吧台现状】这类动态块属于这种情况。
- **两个 `.cmd` 只是省事的壳子。** 它们编码和跳转都静态校验过（UTF-8 无 BOM、LF、标签全部对得上），但**没有在本机实际跑过** —— 当前环境的沙箱禁止调用 `cmd.exe`。真正做事的逻辑全在 `cutover-to-fork.sh` 里，那个脚本的每个分支都在本机实测过。所以批处理万一有毛病，上面「等价的手工命令」永远可用。
- **安装／更新路径上没有第二处写死仓库地址。** 全仓库搜 `github.com` 一共 8 处，只有 `scripts/upstream_update.py` 一处参与机制（它就是我们要替换的那个，之后随每次更新自替换）。其余全是文档与帮助链接，与安装无关：`README.md` 的徽章、`web/package-lock.json` 的 npm 赞助信息、`docs/interactive-install.md` 的 Termux 说明、`docs/paper/manuscript.zh-CN.md` 的引用、`web/src/components/UsageGuide.jsx` 里指向上游仓库文档的帮助链接（这两条会继续指向上游 —— 上游文档描述的就是这套代码，指过去是对的）。另外 `manage.py` 的部署流程是从本地源码目录构建、不做 git clone，所以全新安装装出来的也是 fork 版本。

---

## 六、两个代码提交

```
91f7f30  fix(gateway): replay automatic resume snapshots without the /resume command
723d835  feat(gateway): auto-load continuation material on a new window
```

（另外两个提交只动 `fork/` 里的脚本、说明和测试，不改部署源码。）

第二个提交修的是第一个提交埋下的真问题，值得单独说明，因为它是**实测发现的、上游函数本身的限制**：

`chat_resume.inject_retained()` 的第一件事是从锚点消息里删掉 `/resume` 命令。自动续接的快照锚在一条**普通的**首条消息上，根本没有命令可删 —— 于是第二轮的 `remove_command()` 抛 `ValueError`，一次正常对话会变成 500。

已用真实的上游模块复现过：

```
[PASS] 上游注入器确实拒绝自动快照
[PASS] 失败原因正是「找不到 resume 命令」
[PASS] 替代注入器处理同样输入正常
[PASS] 真实 /resume 命令仍被上游路径正常剥离
```

修法是给自动快照走一条自己的注入路径（`chat_resume_auto.inject_retained`）：逻辑完全一致，只是不做命令剥离，并且**任何失败都返回原消息、同时把内部锚点标记清掉**（否则这个内部键会漏进发给上游模型的消息体里）。手动 `/resume` 的路径一行没碰。

验证方式：`fork/test_chat_resume_auto.py`，45 项断言全部通过。

```bash
python3 fork/test_chat_resume_auto.py
```

它不依赖容器、不依赖第三方库 —— `src/serein/core/` 是纯标准库，所以它自己搭一个临时包、把**真实的补丁模块**装进去直接跑，只有 `chat_resume` 用桩件替身。测试覆盖窗口指纹、首次认领、注入量超限降级、锚点缺失降级、内部标记不泄漏、list 型 content 处理，以及上面那 4 项对上游行为的对照。

桩件里的 `inject_retained` 和 `remember` 都是「一旦被调用就报错」的毒丸 —— 正因为如此，只要自动路径哪天误走回上游函数，整个测试会直接崩，不可能悄悄放过。
