#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键发布：把 7fa4_terminal.py 传到 SFTP 的 /share/terminal.py，并推送到 git 远程。

用法：
    python upload.py                      # 上传 + 提交 + 推送（默认 origin/main）
    python upload.py --no-git             # 只上传 SFTP
    python upload.py --no-sftp            # 只推 git
    python upload.py --dry-run            # 只打印将要做的事，不落地

凭据来源（优先级从高到低）：
    1. 命令行 --host/--port/--user/--password/--key
    2. 环境变量 SFTP_HOST / SFTP_PORT / SFTP_USER / SFTP_PASSWORD / SFTP_KEY
    3. config.json 里的 sftp_host / sftp_port / sftp_user / sftp_password / sftp_key
       （%APPDATA%\\7fa4_terminal\\config.json，可用 --config 或 7FA4_CONFIG 覆盖）
    4. 交互输入（密码用 getpass，不回显）

git 部分：仓库默认取脚本所在目录，远程默认 origin（可用 --remote 改）；
分支默认 main；有改动才提交，推送用 HEAD:<branch>，不切换当前分支。
"""

import argparse
import datetime
import getpass
import json
import os
import posixpath
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY_NAME = "7fa4_terminal.py"
DEFAULT_REMOTE_PATH = "/share/terminal.py"
DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"
REMOTE_MODE = 0o644


# ---------------------------------------------------------------- 配置
def user_config_dir():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "7fa4_terminal")


def config_file(args=None):
    override = getattr(args, "config", None) or os.environ.get("7FA4_CONFIG")
    return os.path.abspath(override) if override else os.path.join(user_config_dir(), "config.json")


def load_config(args=None):
    try:
        with open(config_file(args), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg, args=None):
    path = config_file(args)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return path


def env(*names):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return ""


# ---------------------------------------------------------------- SFTP
def resolve_sftp(args, cfg):
    """合并 CLI / 环境变量 / config.json，返回连接参数字典。"""
    host = (args.host or env("SFTP_HOST") or str(cfg.get("sftp_host") or "")).strip()
    port_raw = args.port or env("SFTP_PORT") or cfg.get("sftp_port") or 22
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        raise SystemExit(f"[错误] 端口不合法：{port_raw!r}")

    user = (args.user or env("SFTP_USER") or str(cfg.get("sftp_user") or "")).strip()
    password = args.password or env("SFTP_PASSWORD") or cfg.get("sftp_password") or ""
    key = args.key or env("SFTP_KEY") or cfg.get("sftp_key") or ""

    if not host:
        raise SystemExit(
            "[错误] 没有 SFTP 主机。任选一种方式提供：\n"
            "  1) python upload.py --host 1.2.3.4 --user 你的账号\n"
            "  2) set SFTP_HOST=1.2.3.4 & set SFTP_USER=你的账号\n"
            "  3) python 7fa4_terminal.py config set sftp_host=1.2.3.4 sftp_user=你的账号"
        )
    if not user:
        user = input("SFTP 用户名: ").strip()
    if not password and not key:
        password = getpass.getpass("SFTP 密码: ")

    return {"host": host, "port": port, "user": user,
            "password": password or None, "key": key or None}


def fmt_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}B" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.0f}B"


class Progress:
    """put 的进度回调：每跨过 10% 打一行。"""

    def __init__(self, label, total, quiet=False):
        self.label, self.total, self.quiet = label, total, quiet
        self.step = -1

    def __call__(self, done, total):
        if self.quiet or not total:
            return
        pct = int(done * 100 / total)
        if pct // 10 > self.step:
            self.step = pct // 10
            print(f"\r  {self.label} {pct:3d}%  {fmt_size(done)}/{fmt_size(total)}",
                  end="" if pct < 100 else "\n", flush=True)


def remote_prepare(sftp, remote, mkdir):
    """确认远程目录存在，必要时创建。"""
    parent = posixpath.dirname(remote.rstrip("/")) or "/"
    try:
        attr = sftp.stat(parent)
    except IOError:
        if not mkdir:
            raise SystemExit(f"[错误] 远程目录不存在：{parent}（加 --mkdir 可自动创建）")
        sftp.mkdir(parent) if parent != "/" else None
        print(f"  [mkdir] {parent}")
        return parent
    if not (attr.st_mode or 0) & 0o40000:
        raise SystemExit(f"[错误] 远程父路径不是目录：{parent}")
    return parent


def sftp_publish(args, cfg):
    try:
        import paramiko
    except ImportError:
        raise SystemExit("[错误] 需要 paramiko：python -m pip install paramiko")

    local = os.path.abspath(args.file)
    if not os.path.isfile(local):
        raise SystemExit(f"[错误] 本地文件不存在：{local}")

    conn = resolve_sftp(args, cfg)
    remote = posixpath.normpath(args.remote_path)
    size = os.path.getsize(local)
    who = f"{conn['user']}@{conn['host']}:{conn['port']}"

    if args.dry_run:
        print(f"[SFTP] 将上传 {local} -> {who}:{remote}  ({fmt_size(size)})")
        return True

    print(f"[SFTP] {who}  上传 {fmt_size(size)} -> {remote}")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(conn["host"], port=conn["port"], username=conn["user"],
                    password=conn["password"], key_filename=conn["key"],
                    timeout=args.timeout, allow_agent=False, look_for_keys=not conn["key"])
    except paramiko.AuthenticationException:
        raise SystemExit(f"[错误] SFTP 认证失败（{who}）")
    except Exception as exc:
        raise SystemExit(f"[错误] 连接 {who} 失败：{exc}")

    try:
        sftp = ssh.open_sftp()
    except Exception as exc:
        ssh.close()
        raise SystemExit(f"[错误] 打开 SFTP 通道失败：{exc}")

    try:
        remote_prepare(sftp, remote, args.mkdir)
        tmp = posixpath.join(posixpath.dirname(remote.rstrip("/")) or "/",
                             f".{posixpath.basename(remote)}.uploading")
        sftp.put(local, tmp, callback=Progress(posixpath.basename(remote), size))
        try:
            sftp.chmod(tmp, REMOTE_MODE)
        except IOError:
            pass

        backup = None
        if args.backup:
            try:
                sftp.stat(remote)
                backup = remote + ".bak"
                try:
                    sftp.remove(backup)
                except IOError:
                    pass
                sftp.rename(remote, backup)
                print(f"  [backup] {remote} -> {backup}")
            except IOError:
                backup = None

        try:
            sftp.posix_rename(tmp, remote)
        except (IOError, OSError):
            try:
                sftp.remove(remote)
            except IOError:
                pass
            sftp.rename(tmp, remote)

        got = sftp.stat(remote)
        if got.st_size != size:
            raise SystemExit(f"[错误] 校验失败：远程 {got.st_size}B != 本地 {size}B")
        print(f"  [OK] {remote}  {fmt_size(got.st_size)}  "
              f"{datetime.datetime.fromtimestamp(got.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")

        if args.save:
            cfg.update({"sftp_host": conn["host"], "sftp_port": conn["port"],
                        "sftp_user": conn["user"]})
            if args.password:
                cfg["sftp_password"] = args.password
            if args.key:
                cfg["sftp_key"] = args.key
            print(f"  [save] 已写入 {save_config(cfg, args)}")
        return True
    except (IOError, OSError) as exc:
        raise SystemExit(f"[错误] SFTP 操作失败：{exc}")
    finally:
        try:
            sftp.close()
        finally:
            ssh.close()


# ---------------------------------------------------------------- git
def run(cmd, cwd=None, capture=True):
    kwargs = {"cwd": cwd or SCRIPT_DIR, "text": True, "encoding": "utf-8", "errors": "replace"}
    if capture:
        kwargs.update(capture_output=True)
    return subprocess.run(cmd, **kwargs)


def git_out(*argv):
    res = run(["git", *argv])
    if res.returncode != 0:
        raise SystemExit(f"[错误] git {' '.join(argv)} 失败：{(res.stderr or res.stdout).strip()}")
    return res.stdout.strip()


def pick_remote(name):
    remotes = git_out("remote").split()
    if name in remotes:
        return name
    raise SystemExit(f"[错误] 远程 {name} 不存在（现有：{'、'.join(remotes) or '无'}）。"
                     f"先执行：git remote add {name} <仓库地址>，或用 --remote 指定")


def git_publish(args):
    if run(["git", "rev-parse", "--show-toplevel"]).returncode != 0:
        if not args.init:
            raise SystemExit(f"[错误] {SCRIPT_DIR} 不是 git 仓库（加 --init 可自动 git init）")
        run(["git", "init"], capture=False)
        print(f"  [git] init {SCRIPT_DIR}")

    remote = pick_remote(args.remote)
    branch = args.branch
    print(f"[git] 仓库 {git_out('rev-parse', '--show-toplevel')}  远程 {remote}  分支 {branch}")

    if args.dry_run:
        print(f"  将执行：git add -A && git commit -m {args.message!r} && git push {remote} HEAD:{branch}")
        return True

    run(["git", "add", "-A"], capture=False)
    staged = run(["git", "diff", "--cached", "--name-only"]).stdout.split("\n")
    staged = [line for line in staged if line.strip()]
    if staged:
        res = run(["git", "commit", "-m", args.message])
        if res.returncode != 0:
            raise SystemExit(f"[错误] 提交失败：{(res.stderr or res.stdout).strip()}")
        print(f"  [commit] {len(staged)} 个文件：{', '.join(staged[:8])}"
              f"{' 等' if len(staged) > 8 else ''}")
    else:
        print("  [commit] 没有改动，跳过提交")

    push = ["git", "push", remote, f"HEAD:refs/heads/{branch}"]
    if args.force:
        push.insert(2, "--force-with-lease")
    res = run(push, capture=False)
    if res.returncode != 0:
        raise SystemExit(
            "[错误] 推送失败。常见原因：\n"
            f"  * 远程有他人提交：git pull {remote} {branch} 后重试\n"
            "  * 认证失败：检查凭据（Windows 可用 git credential manager，或用带 token 的 https 地址）\n"
            "  * 分支受保护：换分支或到网页端合并")
    print(f"  [OK] 已推送 {remote}/{branch}")
    return True


# ---------------------------------------------------------------- main
def syntax_check(path):
    try:
        with open(path, encoding="utf-8") as f:
            compile(f.read(), path, "exec")
    except SyntaxError as exc:
        raise SystemExit(f"[错误] {os.path.basename(path)} 语法错误，已中止发布：\n{exc}")
    return True


def build_parser():
    p = argparse.ArgumentParser(
        prog="upload.py",
        description="发布 7fa4_terminal.py：SFTP 上传到 /share/terminal.py + 推送 git 远程")
    p.add_argument("-f", "--file", default=os.path.join(SCRIPT_DIR, ENTRY_NAME),
                   help="要发布的本地文件（默认同目录的 7fa4_terminal.py）")
    p.add_argument("--remote-path", default=DEFAULT_REMOTE_PATH,
                   help=f"远程目标路径（默认 {DEFAULT_REMOTE_PATH}）")
    p.add_argument("--host", help="SFTP 主机")
    p.add_argument("--port", help="SFTP 端口（默认 22，或 config 的 sftp_port）")
    p.add_argument("-u", "--user", help="SFTP 用户名")
    p.add_argument("-p", "--password", help="SFTP 密码（不推荐写在命令里）")
    p.add_argument("--key", help="SFTP 私钥路径")
    p.add_argument("--timeout", type=int, default=25, help="连接超时秒数（默认 25）")
    p.add_argument("--backup", action="store_true", help="上传前把远程旧文件备份成 .bak")
    p.add_argument("--mkdir", action="store_true", help="远程目录不存在时自动创建")
    p.add_argument("--save", action="store_true", help="把本次的 SFTP 账号密码写进 config.json")
    p.add_argument("--config", help="指定 config.json 路径")

    p.add_argument("--remote", default=DEFAULT_REMOTE,
                   help=f"git 远程名（默认 {DEFAULT_REMOTE}）")
    p.add_argument("--branch", default=DEFAULT_BRANCH, help=f"推送分支（默认 {DEFAULT_BRANCH}）")
    p.add_argument("-m", "--message", help="提交信息（默认自动生成时间戳）")
    p.add_argument("--init", action="store_true", help="当前目录不是仓库时自动 git init")
    p.add_argument("--force", action="store_true", help="推送使用 --force-with-lease（谨慎）")

    p.add_argument("--no-sftp", action="store_true", help="跳过 SFTP 上传")
    p.add_argument("--no-git", action="store_true", help="跳过 git 推送")
    p.add_argument("--no-check", action="store_true", help="跳过语法检查")
    p.add_argument("--dry-run", action="store_true", help="只打印计划，不做任何改动")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.no_sftp and args.no_git:
        raise SystemExit("[错误] --no-sftp 与 --no-git 不能同时使用")
    if not args.message:
        args.message = "deploy: update terminal.py " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"== 发布 {os.path.basename(args.file)} ==")
    if not args.no_check:
        syntax_check(os.path.abspath(args.file))
        print("[check] 语法检查通过")

    cfg = load_config(args)
    failed = []

    if not args.no_sftp:
        try:
            sftp_publish(args, cfg)
        except SystemExit as exc:
            print(str(exc))
            failed.append("SFTP")

    if not args.no_git:
        try:
            git_publish(args)
        except SystemExit as exc:
            print(str(exc))
            failed.append("git")

    if failed:
        print(f"\n[失败] {' / '.join(failed)} 未完成")
        return 1
    print("\n[完成] 发布流程结束" if not args.dry_run else "\n[完成] dry-run 结束（未做任何改动）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[已取消]")
        sys.exit(130)
