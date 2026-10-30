# 7FA4 终端

7FA4 OJ 的命令行客户端（Python + requests），在终端里完成登录、看题、拉题面、本地对拍、提交、
同步 vjudge 记录、SFTP 存取、题面导出 PNG 等操作。

- 主程序：`7fa4_terminal.py`（单文件，无框架依赖）
- 安装程序：`install.py`
- 发布工具：`upload.py`

## 功能

| 命令 | 作用 |
| --- | --- |
| `login` / `logout` / `whoami` | 登录 `jx.7fa4.cn` / `in.7fa4.cn`（自动探测可用站点）、退出、查看状态 |
| `list [章节]` | 题目列表，支持 `list 6.5.5` 这种章节号 |
| `pull <题>` | 拉题面 + 图片 + 样例（自动解压 zip），生成 C++ 文件；题面默认取**渲染后的 HTML**（`--from-md` 用 markdown 源码） |
| `statement <题>` | 只看题面（同样默认走渲染后的 HTML） |
| `submit <题>` | 提交代码并自动跟进评测结果；外站题直连 vjudge，AC 后才同步到 7FA4（`--via 7fa4` 走代理），`--no-watch` 不跟进 |
| `push <题>` | 把 vjudge 上已 AC 的记录同步到 7FA4，不重复提交 |
| `vjlogin` / `vjcheck` | 用账号密码登录 vjudge / 检查会话是否有效 |
| `task` / `tasks` | 查看 vjudge 任务 |
| `run <题>` | 本地编译（Windows / Linux 通用）并在样例上跑，用户输出/错误写到 `<名>.out` / `<名>.err`；目录里有多份 cpp 时默认跑 `pull` 生成的那份（`-f` 指定其它） |
| `stress <题>` | 对拍：随机数据跑「正解 vs 暴力」，不一致就保存用例（`1.in`/`sol.out`/`brute.out`） |
| `contest [比赛]` | 模测：不给参数列最近几场，给了看题目列表 + 我的排名/各题得分 |
| `progress` | 进度排行（通过数、积分），`--me` 只看自己 |
| `article <id>` | 读帖子/帮助/公告（也接受 `.../article/124` 的 URL） |
| `prints` | 提交打印队列（姓名/后缀/审核/打印状态） |
| `friends` | 好友/关注列表（双向 / 关注我 / 我关注）+ 群 |
| `chat [联系人]` | 聊天：看消息、`-m` 发消息、`--ask` 发求助、`--accept` 同意求助 |
| `submission <编号>` | 看提交状态、分数、时间/内存，`--code` 显示代码、`--save` 存代码；`--revoke` 作废、`--delete` 删除 |
| `submissions` | 提交记录查询：`--page/--pages` 分页，`--problem/--submitter/--status/--language/--min-score/--max-score` 筛选 |
| `plan [show\\|add] [日期]` | 计划按天读写：`plan show 明天`、`plan add 后天 -m "..." -p "71354"`；`plan home` 看首页概览 |
| `review` | **站点复盘（tag）**：`show` 查看、`timeline -i N` 改时间线、`set -q 题目` 改某题，写完直接上传 |
| `help [命令]` | 分级帮助：`help` 总览，`help sftp` 看该命令参数 |
| `paper` | 纸面题答案图片：`get` 备份 / `submit` 上传 / `restore` 还原 |
| `export <题>` | 题面 markdown 导出 PNG（本地图片一起嵌入） |
| `sftp` | SFTP 存储（5307）：`login/ls/pwd/cd/lcd/lpwd/get/put/mkdir/rm/rmdir` |
| `template` | 查看/设置代码模板（`{{id}} {{no}} {{title}} {{short}} {{url}} {{date}} {{infile}} {{outfile}} {{freopen}} {{io_mode}}`） |
| `config` | 查看/修改本地配置（`show/get/set/unset`） |
| `update` | 从 `update_url`（默认 `http://localhost:9080/terminal.py`）检查并更新自身 |
| `get` / `post` / `raw` | 直接发 HTTP 请求 |
| `shell` | 交互式终端 |

题目参数支持三种写法：ID（`72874`）、题号（`Q6.4.6.1` / `6.4.6.1`）、标题关键字。

## 环境要求

- Python 3.8+（Windows / macOS / Linux）
- 必需：`requests`
- 可选：`paramiko`（`sftp` 命令）、`Pillow`（`export` 导出 PNG）

## 安装

```bash
python install.py                 # 检查 Python、装必需依赖、生成 7fa4 命令
python install.py --paramiko      # 顺带装 SFTP 依赖
python install.py --with-pil      # 顺带装 Pillow（export 需要）
python install.py --uninstall     # 移除 7fa4 命令（不动依赖）
```

安装程序会：

1. 校验 Python 版本与 `7fa4_terminal.py` 是否同目录；
2. 用当前解释器 `pip install` 缺失的依赖；
3. 在 Python 的 `Scripts` 目录生成 `7fa4`（Windows 为 `7fa4.cmd`）启动器，指向本仓库的脚本；
4. 跑一次自检并提示 PATH 配置。

命令目录不在 PATH 时，PowerShell 下：

```powershell
setx PATH "$env:PATH;<上一步打印的目录>"
```

Linux / macOS 说明：

- 安装目录取 `python3 -m sysconfig` 的 `scripts` 目录（发行版 python 通常是 `/usr/local/bin`，一般要 root 才能写）。
- 不可写时自动退回 `~/.local/bin`，生成文件名就是 `7fa4`（`chmod 755`，`#!/bin/sh` 启动器）。
- `~/.local/bin` 默认不一定在 PATH（Ubuntu 的 `~/.profile` 只在目录已存在时才加入），安装程序会打印该执行的命令：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
7fa4 --help
```

- 也可以显式指定目录：`python3 install.py --dir ~/.local/bin`；装在 venv 里则用 venv 的 `bin` 目录。
- 若装完 `7fa4` 报 `ModuleNotFoundError: requests`，说明启动器用的解释器缺依赖：`python3 -m pip install requests`（或 `--user`）。

手动安装也可以：

```bash
python -m pip install requests paramiko
python 7fa4_terminal.py --help
```

## 快速开始

```bash
7fa4 login -u 用户名 -p 密码        # 登录并保存会话
7fa4 list 6.5.5                     # 看某章节题目
7fa4 pull Q6.4.6.1                  # 拉题面、样例，生成 6.4.6.1.cpp
7fa4 run Q6.4.6.1                   # 本地跑样例
7fa4 stress Q6.4.6.1 -g gen.cpp -b brute.cpp   # 对拍：随机数据 vs 暴力
7fa4 submit Q6.4.6.1 -l cpp17       # 提交
7fa4 export Q6.4.6.1                # 题面导出 PNG
7fa4 sftp login                     # SFTP 存取（5307），详见下文
```

外站题（vjudge 代收的题）：

```bash
7fa4 vjlogin                                   # 登录 vjudge，保存会话
7fa4 pull Q6.5.5.1                             # 拉题面
7fa4 submit Q6.5.5.1                           # 直连 vjudge，AC 后自动同步
7fa4 submit Q6.5.5.1 --via 7fa4                # 改走站点代理（需要验证码）
7fa4 push Q6.5.5.1 --rid 73684626              # 手动同步某次 AC
```

## SFTP 存取

服务器 5307 端口（SFTPGo），登录一次后账号密码写入 `config.json`，之后不用再输：

```bash
7fa4 sftp login                     # 交互输入账号密码
7fa4 sftp login -u 用户名 -p 密码
```

**本地暂存目录**默认是项目下的 `sftp/`（首次使用自动创建）。`put` 的相对路径从这里找文件，
`get` 不指定本地路径时也落到这里；要传别处的文件就写 `./xxx` 或绝对路径：

```bash
7fa4 sftp lcd                  # 切换本地暂存目录（默认 ./sftp）
7fa4 sftp lpwd                 # 查看本地暂存目录
```

**远程当前目录**用 `cd` 切换，记在 `config.json` 的 `sftp_cwd`，之后的相对路径都按它解析：

```bash
7fa4 sftp cd share             # -> /share
7fa4 sftp cd latex             # -> /share/latex
7fa4 sftp cd ../OI-wiki        # -> /share/OI-wiki
7fa4 sftp cd /                 # 回根目录
7fa4 sftp pwd                  # 当前远程目录
```

常用操作：

```bash
7fa4 sftp ls                   # 列当前远程目录
7fa4 sftp ls latex/            # 也接受相对/绝对路径
7fa4 sftp put test.cpp         # ./sftp/test.cpp -> <cwd>/test.cpp
7fa4 sftp put test.cpp bak/    # 目标是已存在目录时自动拼上文件名
7fa4 sftp get a.out            # <cwd>/a.out -> ./sftp/a.out
7fa4 sftp get a.out D:\tmp\    # 指定本地目录
7fa4 sftp mkdir proj           # 远程建目录（相对 cwd）
7fa4 sftp rmdir proj / rm a.out
```

路径规则：

- 远程：`/` 或 `~` 开头按绝对路径，其它相对 `sftp_cwd`
- 本地：绝对路径或 `./` 开头按当前工作目录，其它相对路径落到 `sftp/`

`cd` 会先校验目标存在且是目录；`ls` 输出目录优先，带大小和修改时间。

## 好友 / 聊天

```bash
7fa4 friends                      # 关注关系汇总 + 前 30 条（双向优先）
7fa4 friends -n 100 --search 初一  # 按账号/昵称/姓名/年级过滤
7fa4 friends --all                # 连没有关注关系的也列（全站在线用户很大）
7fa4 friends --groups             # 只看群

7fa4 chat                         # 概览：好友/群数量 + 发言限制
7fa4 chat 张三 -n 20              # 看最近 20 条消息
7fa4 chat 张三 -m "在吗"          # 发普通消息
7fa4 chat 张三 --ask "第 3 题怎么读入"   # 发求助（内容变成【求助】第 3 题怎么读入）
7fa4 chat 张三 --accept -m "我看看"      # 同意求助（【同意求助】+ 附言）
7fa4 chat 自己 -m "备忘"           # 给自己发（测试用，不会打扰别人）
```

接口（页面里的私有 API）：

| 用途 | 接口 |
|---|---|
| 联系人/群 | `GET /chat/info` → `{user, limit, groups, friends}` |
| 拉消息 | `GET /chat/chat?type=user\|group&target_id=<id>&take=N` → `{chats:[{id, content, send_time, sender_id, ...}]}` |
| 发消息 | `POST /chat/chat` 表单 `{type, target_id, content}`，`content` 是纯文本（图片是 markdown dataURL） |

注意 `content` 里存的是 JSON 字符串（`{"type":"text","content":"..."}`），`type` 支持 `text/image/pat/sticker/emoji/file`；
工具会自动解析成可读文本。发言有频率限制（当前账号：每 2400 秒最多 4 条），`--dry-run` 可以先看要发什么。

「求助 / 同意求助」都是普通文本消息加固定前缀（`【求助】` / `【同意求助】`），站点没有专门的求助消息类型，
所以对方在网页上看到的就是一条带前缀的聊天记录。

## 题面来源：优先渲染后的 HTML

站点的 `/problem/<id>/markdown/html` 返回的是**作者写的 markdown 源码**，有时本身就有错（漏段落、公式没闭合等）。
所以 `pull` / `statement` 现在默认：

1. 取题目页 `/problem/<id>` 渲染后的 HTML；
2. 在 HTML 里找题面容器（`#problem-content` / `.markdown-body` / `.problem-statement` /
   `.ui.bottom.attached.segment` / `.statement`，按顺序试），用**配对 div** 的方式截出正文；
3. 把正文 HTML 转回 markdown：`<h1..h6>` → `#..######`、`<pre>` → 围栏代码块、
   `<code>` → 行内反引号、`<li>` → `- `、表格单元格用 ` | ` 分隔、`<img>` → `![](url)`；
   MathJax 渲染出来的 `<span class="mjpage"><svg>…` 只取 `<title>` 里的 TeX，还原成 `$n$`、`$1 \le n \le 9$`；
   源码里的换行/缩进会先折成空格（`<pre>` 内容先挖出来占位），否则 SVG 这种多行标签会把一句话拆成好几行；
4. 如果容器没定位到（提取结果里出现「提交代码/评测记录/我的提交」这类噪声 ≥2 处）或正文太短，
   自动回退到 markdown 源码。

`pull` 会打印来源，方便确认：

```
$ 7fa4 pull 82606
[题面] statement.md（来源：渲染后的 HTML）
[输入输出] 文件：xxx.in -> xxx.out
```

需要旧行为时加 `--from-md`（只看源码）。

## 文件输入输出

有些题要求读写文件（`freopen`），`pull` 会从题面里认出来并写进 `meta.json`：

```bash
7fa4 pull Q1.2.3.4
# [输入输出] 文件：data.in -> data.out（模板里的 {{freopen}} 已填好）
```

识别规则（**先看题目页 HTML，再看 markdown 源**）：

- `输入文件：x.in` / `输入文件名：x.in` / `输入文件名为 x.in`
- 表格里分成两格：`<td>输入文件</td><td>x.in</td>`
- `从文件 x.in 读入` / `Input file: x.in`
- 输出同理；只写一边时另一边按扩展名推导（`.in ↔ .out`）

文件名要求是 ASCII（`[A-Za-z0-9_.-]`），所以「输入文件格式如下」「输入文件说明」这类不会被误判。
有些题只把这句话写在题目页 HTML 里（markdown 源里没有），现在两边都会查。

已经 pull 过的题目：`meta.json` 里没有 `io` 时，`run`/`stress` 会现场从 `statement.md` 再猜一次；
如果代码是旧的（没 `freopen`），`pull <题> -f` 按模板重新生成带 `{{freopen}}` 的版本。

模板里加一行 `{{freopen}}` 即可自动插入：

```cpp
int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
{{freopen}}          // 文件 IO 的题会变成下面两行，标准 IO 的题是空
    // freopen("data.in", "r", stdin);
    // freopen("data.out", "w", stdout);
```

其他占位符：`{{infile}}` / `{{outfile}}`（文件名）、`{{io_mode}}`（`file` / `stdin`）。

`run` / `stress` 会自动照顾文件 IO：把样例输入复制成 `data.in`、程序在临时目录里跑，
再从 `data.out` 读回输出比对（不会污染题目目录）。

## 对拍

```bash
7fa4 stress Q6.4.6.1                          # 自动找：pull 那份当正解，brute/baoli/bf、gen/maker/rand
7fa4 stress Q6.4.6.1 -s ac.cpp -b brute.cpp -g gen.cpp -n 500
7fa4 stress problems/77425_luoguP4597 --dir D:\tmp\stress   # 直接给目录
```

规则：

- 正解默认是 `pull` 生成的那份（`meta.json` 的 `cpp`），`-s` 可换
- 暴力按文件名猜（`brute/baoli/bf/暴力/naive`），生成器按 `gen/maker/rand/data` 猜，都会跳过正解本身
- 生成器标准写法：**读 `argv[1]` 当随机种子**，数据打到 stdout
- 每轮顺序：`gen(seed) → sol → brute`，用 `run_cpp` 编译产物放临时目录，跑完删除
- 不一致（或正解 TLE/RE）时把用例存到 `<题目目录>/stress/fail<轮次>/`：`1.in`、`sol.out`、`brute.out`、`note.txt`，
  并打印第一处不同的行号和两边内容，可直接 `7fa4 run <题> -f ...` 复现
- 暴力 TLE 会跳过该轮（认为是数据超出暴力范围），不误判

## 计划 / 复盘 / 提交详情

```bash
7fa4 plan                            # 今天的计划（描述 + 题目：id/题号/题目名 + 教师计划 + 完成情况）
7fa4 plan show 昨天 --no-titles        # 不查题目名（省几次请求）
7fa4 plan show 明天                   # 看明天的（也支持 后天 / yesterday / 2026-10-28 / +3）
7fa4 plan add 明天 -m "树剖复习" -p "71354 Q3.3.6.4"   # 写明天的计划
7fa4 plan add 后天 -m "线段树合并" -r "已完成 2/3" -t "剩余题明天补"
7fa4 plan add 明天 -n                 # 只看将要提交的内容
7fa4 plan home                       # 首页概览：今日计划文本 + 作业表（题号/题目/截止）

7fa4 submissions                      # 最近 20 条提交
7fa4 submissions --page 2 --pages 2   # 看第 2、3 页
7fa4 submissions --problem 77425      # 只看某题
7fa4 submissions --submitter 2025005011 --status Accepted   # 按人 + 状态
7fa4 submissions --language cpp17 --min-score 90            # 按语言 + 分数

7fa4 review export 3152624            # 下载复盘成 md（默认 reviews/<tag>.md）
7fa4 review new 3152624               # 生成空模板，从零开始写
#   ... 用编辑器改 md ...
7fa4 review import 3152624 -f reviews/3152624.md     # 上传（改完直接提交）
7fa4 review import 3152624 -f reviews/3152624.md -n  # 只看解析结果不上传

7fa4 review show 3152624              # 看这场复盘（时间线 + 每题：常规检查/子任务/反思/估分）
7fa4 review show "https://jx.7fa4.cn:8888/review/user_tag/edit?user_id=2194&tag_id=3152624"
7fa4 review html 3152624              # 走 /review/user_tags/html 的原始视图

7fa4 review timeline 3152624 -i 3 -p "B 题正解" -a "写完发现假了，放弃"   # 改第 3 行时间线
7fa4 review set 3152624 -q 82376 --rethink "数据：样例。探索：整体二分。反思：输出多了。" \
    --guess 30 --normal "time=done,test=skip"                          # 改某道题的复盘
7fa4 review timeline 3152624 -i 1 -p "..." -n                          # 预演（不提交）

7fa4 submission 1048450              # 状态、分数、用时、内存、语言、提交者、提交时间
7fa4 submission /submissions?id=1048450   # 也接受这种写法
7fa4 submission 1048450 -c           # 显示代码（超过 2000 字符会先问 y/N，-y 跳过）
7fa4 submission 1048450 -s problems/72874_inf/   # 代码存成 submission1048450.cpp

7fa4 submission 1055544 --revoke         # 作废（POST /submission/<id>/revoke，状态变 Revoke）
7fa4 submission 1055544 --delete         # 删除（POST /submission/<id>/deleted，状态变 Deleted）
7fa4 submission 1055544 --rejudge        # 重新评测（需要管理员权限，普通账号会被拒绝）
7fa4 submission 1055544 --revoke -y      # 跳过确认
```

提交详情分两步请求：

1. **状态**走 `/submissions/?id=<编号>`（页面内嵌 `itemList`，取那一条），别人的提交也能看；
2. **代码**才进 `/submission/<编号>`。如果不是自己的提交，会先提示「这是 xx 的提交，代码页可能打不开」并问
   继续 / 停止（`-y` 不再询问）。站点对他人提交的代码页会直接抛
   `TypeError: ... reading 'is_owner'`，这时会打印该错误并说明取不到代码；
   若第一次失败，会再问一次「换个方式再试一次（重新请求）？」，同样可以停下来。

- `plan show` 里的题目名通过 `GET /api/v2/search/problems/<id>` 拿（返回 `Q3.3.6.4. 超级钢琴`），结果缓存在
  `config.json` 的 `problem_titles`；`--no-titles` 可跳过这些请求
- 计划接口：读 `GET /user_plan?format=json&user_id=<uid>&date=<ts>&type=day`，写 `POST /user_plan`
  （`{id, type, date, user_id, problem_ids, plan, result, tweak}`，`id` 为已有记录的编号）；`problem_ids` 用 `|` 分隔，
  命令行里用空格/逗号写会自动转换；用户 id 首次从首页 `/user_plans/<uid>` 取到后缓存进配置
- 提交记录页 `/submissions` 是服务端渲染，内嵌 `itemList`；参数：`page`、`problem_id`、`submitter`、`status`、`language`、`min_score`、`max_score`
- 复盘可以用 markdown 写：`review export` 导出 → 编辑 → `review import` 上传；格式是
  `## 时间线`（`### 14:30` + `计划：`/`完成：`）和 `## 题目`（`### S15.26.24.1 乾坤横移` +
  `估分：`/`常规：k=v, …`/`子任务：- 得分/总分 期望N 描述`/`反思：`/`其他：`/`错误：`）。
  多行内容用 `~~~` 围栏，避免正文里的「反思：」被当成字段；`review new` 只保留结构、内容清空，适合从零写
- 复盘直接读写**站点**的复盘 tag（不是本地文件）：
  - 读：`GET /review/user_tag/edit?format=json&user_id=<uid>&tag_id=<tid>` →
    `{tag_review:[{time,plan,achieve}], problems:[{id,title,exercise_name,review:{normal,subtasks,rethink,other,guess_score,...}}]}`
  - 写：`POST /review/user_tag/edit`，表单字段 `data` = 上面结构的 JSON（`problem_review` 以题目 id 为键）
  - `tag_id` 从编辑页 URL 里取（`?tag_id=...`），命令支持直接粘整条 URL
  - **时间线行数固定**：只能改已有行（`review timeline -i N`），服务端按行校验，新增行会报「第 N 行参数未完整填写」，
    所以 `review add` 只给提示不提交
  - 子任务的 `actual/expected/total/description` 要按字符串传（前端读的是输入框），数字 `0` 会被判成「没填写」；
    另外整表回传时不能把「通过检查」的项改成不通过，否则服务端拒绝保存
- 提交后跟进：先记下 `/submissions?submitter=<学号>` 里当前最新编号，提交成功后轮询这个列表找到更大的编号，
  再盯 `/submissions/?id=<编号>` 直到 `result` 出现且不在 `Judging/Compiling/Running/Waiting/Pending` 里；
  `--wait` 控制最长等待（默认 180s），`--no-watch` 关掉跟进，学号首次从 `/user/<uid>` 页面标题取到后缓存进配置
- 提交详情是从 `/submission/<id>` 页面内嵌的 `roughData` 与 `unformattedCode` 里解析的，
  已完成提交没有逐测试点明细（站点只在评测过程中通过 socket 推送），所以这里给的是概要 + 代码
- `run` 现在每组样例会写出 `<名>.out`（用户输出）和 `<名>.err`（标准错误）；如果期望输出本身就是 `<名>.out`，
  用户输出改写成 `<名>.user.out`，不会覆盖判题数据

## 配置

配置在 `config.json`：

- Windows：`%APPDATA%\7fa4_terminal\config.json`
- macOS：`~/Library/Application Support/7fa4_terminal/config.json`
- Linux：`~/.config/7fa4_terminal/config.json`

可用 `--config PATH` 或环境变量 `7FA4_CONFIG` 覆盖，老位置的配置启动时自动迁移。

常用键：

| 键 | 说明 |
| --- | --- |
| `host` | 探测到的可用站点 |
| `language` | 默认提交语言，如 `cpp17` |
| `vj_cookie` / `vj_user` | vjudge 会话 |
| `template` | 代码模板路径或内容 |
| `sessions` | 各站点登录态（自动维护） |
| `sftp_host` / `sftp_port` / `sftp_user` / `sftp_password` / `sftp_key` | SFTP 连接信息 |
| `sftp_cwd` / `sftp_local` | SFTP 远程当前目录 / 本地暂存目录 |
| `submitter` | 自己的学号（提交后跟进状态用，首次从 `/user/<uid>` 取到后缓存） |
| `user_id` | 站内用户 id（计划、复盘用，首次从首页 `/user_plans/<uid>` 取到后缓存） |
| `update_url` | 自动更新源，默认 `http://localhost:9080/terminal.py` |
| `auto_update` | `off` / `check`（默认，只提示）/ `apply`（自动替换） |
| `update_interval` | 自动检查间隔秒数，默认 `21600`（6 小时） |
| `update_checked_at` | 上次检查时间戳（程序自动维护） |

```bash
7fa4 config                            # 查看（敏感字段打码）
7fa4 config get host                   # 取某个值
7fa4 config set language=cpp17         # 写
7fa4 config unset vj_cookie            # 删
```

## 自动更新

`7fa4_terminal.py` 可以从 `http://localhost:9080/terminal.py` 拉取新版本并替换自身：

```bash
7fa4 update                       # 检查 + 应用
7fa4 update --check               # 只检查
7fa4 update --url http://其他地址/terminal.py
```

工作方式：

1. GET 远端文件，与本地字节比较，一致就报「已是最新」；
2. 不一致时先写 `7fa4_terminal.py.new`，用 `compile()` 做语法校验，失败则删除临时文件、不动原文件；
3. 通过校验后把原文件备份成 `7fa4_terminal.py.bak`，再 `os.replace` 原子替换；
4. 提示「重新执行命令即生效」（当前进程仍跑旧代码）。

启动时也会自动检查一次，策略由 `auto_update` 控制：

```bash
7fa4 config set auto_update=check     # 默认：只打印一行「有新版本，运行 update 应用」
7fa4 config set auto_update=apply     # 有新版本直接替换
7fa4 config set auto_update=off       # 完全不检查
7fa4 config set update_interval=3600  # 改检查间隔（秒）
```

检查带 2 秒超时，失败静默忽略（离线也能正常用），并把 `update_checked_at` 写回配置避免频繁请求。
`update` 子命令本身不会触发启动检查。

## 发布新版本

`upload.py` 把主程序上传到 SFTP 的 `/share/terminal.py`，并推送到 git 远程 `origin/main`（可用 `--remote` / `--branch` 改）。

```bash
python upload.py                          # 语法检查 -> 输入提交信息 -> 上传 -> commit -> push
python upload.py -m "修复 xxx 的显示"      # 直接指定提交信息，不问
python upload.py --no-git                 # 只传 SFTP
python upload.py --no-sftp                # 只推 git
python upload.py --dry-run                # 只打印计划
python upload.py --backup                 # 远程旧文件先备份成 .bak
python upload.py --host 1.2.3.4 --user me # 临时指定 SFTP 账号
python upload.py --save                   # 把本次 SFTP 账号写进 config.json
```

提交信息：不给 `-m` 时会在发布前提示输入一行，直接回车用默认的
`deploy: update terminal.py <时间>`，输入 `q` 取消；非交互环境（管道、CI）自动用默认值。

SFTP 连接信息按优先级取：命令行 `--host/--port/--user/--password/--key` →
环境变量 `SFTP_HOST/SFTP_PORT/SFTP_USER/SFTP_PASSWORD/SFTP_KEY` → `config.json` 的 `sftp_*` → 交互输入。

其他参数：`--remote-path`（默认 `/share/terminal.py`）、`--remote`、`--branch`、`-m`（提交信息）、
`--mkdir`、`--init`、`--no-check`、`--timeout`、`--force`（`--force-with-lease`，谨慎）。

上传采用「先写同目录临时文件，再原子改名」，完成后比对远程与本地字节数，避免出现半截文件。

## 目录结构

```
7fa4_terminal.py    主程序（命令全在这里）
install.py          安装程序（依赖 + 7fa4 命令）
upload.py           发布工具（SFTP + git）
README.md
template.cpp        代码模板示例
problems/           pull 下来的题目（题面、样例、代码、图片）
sftp/               SFTP 本地暂存目录（put 上传 / get 下载）
```

`problems/`、`sftp/`、`templates/`、`__pycache__/`、本地 `config.json` 不入库，见 `.gitignore`。

## 常见问题

**站点连不上？** jx 走公网、in 走校内网，只能二选一。程序会自动探测并缓存；也可 `--host in` / `--host jx` 显式指定。

**提交外站题提示需要验证码？** `--via 7fa4` 会把验证码画在终端里，同时保存图片并尝试打开。

**`sftp` 命令报缺少 paramiko？** `python -m pip install paramiko`，或 `python install.py --paramiko`。

**推送失败 `non-fast-forward`？** 远程有新提交，先 `git pull origin main` 再 `python upload.py`；认证问题检查 git 凭据或改用带 token 的 https 地址。

**提示远程不存在？** 默认用 `origin`，远程叫别的名字时用 `--remote <名字>`，或先 `git remote add origin <仓库地址>`。

**`7fa4` 命令找不到？** 命令目录不在 PATH，按安装程序末尾的提示加入 PATH 后重开终端。
