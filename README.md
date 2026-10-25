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
| `pull <题>` | 拉题面 + 图片 + 样例（自动解压 zip），生成 C++ 文件 |
| `statement <题>` | 只看题面 |
| `submit <题>` | 提交代码；外站题直连 vjudge，AC 后才同步到 7FA4（`--via 7fa4` 走代理） |
| `push <题>` | 把 vjudge 上已 AC 的记录同步到 7FA4，不重复提交 |
| `vjlogin` / `vjcheck` | 用账号密码登录 vjudge / 检查会话是否有效 |
| `task` / `tasks` | 查看 vjudge 任务 |
| `run <题>` | 本地编译（Windows / Linux 通用）并在样例上跑 |
| `paper` | 纸面题答案图片：`get` 备份 / `submit` 上传 / `restore` 还原 |
| `export <题>` | 题面 markdown 导出 PNG（本地图片一起嵌入） |
| `sftp` | SFTP 存储（5307）：`login/ls/pwd/cd/lcd/lpwd/get/put/mkdir/rm/rmdir` |
| `template` | 查看/设置代码模板（`{{id}} {{no}} {{title}} {{short}} {{url}} {{date}}`） |
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
python upload.py                          # 语法检查 -> 上传 -> commit -> push
python upload.py --no-git                 # 只传 SFTP
python upload.py --no-sftp                # 只推 git
python upload.py --dry-run                # 只打印计划
python upload.py --backup                 # 远程旧文件先备份成 .bak
python upload.py --host 1.2.3.4 --user me # 临时指定 SFTP 账号
python upload.py --save                   # 把本次 SFTP 账号写进 config.json
```

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
