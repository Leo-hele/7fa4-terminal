#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""7FA4 终端安装程序：检查 Python、装依赖、生成 7fa4 命令。

用法：
    python install.py                 # 装依赖 + 生成 7fa4 命令
    python install.py --no-deps       # 只生成命令，不动依赖
    python install.py --with-pil      # 额外装 Pillow（export 导出 PNG 需要）
    python install.py --uninstall     # 移除生成的命令，保留依赖
    python install.py --dry-run       # 只看计划

装完在终端直接敲 7fa4 即可（Windows 为 7fa4.cmd），例如：
    7fa4 login -u 用户名 -p 密码
    7fa4 list 6.5.5
"""

import argparse
import os
import subprocess
import sys
import sysconfig

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(SCRIPT_DIR, "7fa4_terminal.py")
COMMAND = "7fa4"
MIN_PYTHON = (3, 8)
REQUIRED = ["requests"]
OPTIONAL = {"paramiko": "SFTP 上传/下载", "pillow": "export 导出 PNG"}


def log(msg=""):
    print(msg, flush=True)


def scripts_dir():
    """优先用当前解释器的 Scripts 目录，不可写时退回 ~/.local/bin。"""
    candidates = []
    path = sysconfig.get_path("scripts")
    if path:
        candidates.append(path)
    candidates.append(os.path.join(os.path.expanduser("~"), ".local", "bin"))
    for cand in candidates:
        try:
            os.makedirs(cand, exist_ok=True)
            probe = os.path.join(cand, ".7fa4-write-test")
            with open(probe, "w") as f:
                f.write("")
            os.remove(probe)
            return os.path.abspath(cand)
        except OSError:
            continue
    raise SystemExit("[错误] 找不到可写的命令目录，可用 --dir 指定")


def check_python():
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(f"[错误] 需要 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 或更高，"
                         f"当前是 {sys.version.split()[0]}")
    log(f"[1/4] Python {sys.version.split()[0]}  OK  ({sys.executable})")
    if not os.path.isfile(ENTRY):
        raise SystemExit(f"[错误] 找不到 {ENTRY}，请把 install.py 和 7fa4_terminal.py 放在同一目录")


def missing(pkgs):
    out = []
    for pkg in pkgs:
        name = "PIL" if pkg == "pillow" else pkg
        try:
            __import__(name)
        except ImportError:
            out.append(pkg)
    return out


def pip_install(pkgs, dry):
    if not pkgs:
        return True
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *pkgs]
    log("      " + " ".join(cmd))
    if dry:
        return True
    res = subprocess.run(cmd)
    if res.returncode != 0:
        log(f"[警告] 依赖安装失败：{', '.join(pkgs)}。可手动执行："
            f"{sys.executable} -m pip install {' '.join(pkgs)}")
        return False
    return True


def install_deps(args):
    pkgs = list(REQUIRED)
    if args.paramiko:
        pkgs.append("paramiko")
    if args.with_pil:
        pkgs.append("pillow")
    need = missing(pkgs)
    if args.no_deps:
        log(f"[2/4] 跳过依赖安装（缺失：{', '.join(need) if need else '无'}）")
        return
    if not need:
        log("[2/4] 依赖已就绪")
        return
    log(f"[2/4] 安装缺失依赖：{', '.join(need)}")
    pip_install(need, args.dry_run)


def launcher_body():
    if os.name == "nt":
        return f'@echo off\r\n"{sys.executable}" -u "{ENTRY}" %*\r\n'
    return f'#!/bin/sh\nexec "{sys.executable}" -u "{ENTRY}" "$@"\n'


def install_command(target_dir, dry):
    name = COMMAND + (".cmd" if os.name == "nt" else "")
    path = os.path.join(target_dir, name)
    body = launcher_body()
    log(f"[3/4] 生成命令 {path}")
    if dry:
        return path
    os.makedirs(target_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(body)
    if os.name != "nt":
        os.chmod(path, 0o755)
    return path


def on_path(directory):
    parts = [os.path.abspath(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p.strip()]
    return os.path.abspath(directory) in parts


def verify(dry):
    if dry:
        return
    res = subprocess.run([sys.executable, "-u", ENTRY], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    ok = res.returncode == 0 and "usage" in (res.stdout + res.stderr).lower()
    log(f"[4/4] 自检 {'通过' if ok else '异常'}"
        + ("" if ok else f"：{(res.stderr or res.stdout).strip()[:200]}"))
    if not ok:
        raise SystemExit(1)


def uninstall(target_dir):
    removed = []
    for name in (COMMAND, COMMAND + ".cmd", COMMAND + ".ps1", COMMAND + ".bat"):
        path = os.path.join(target_dir, name)
        if os.path.isfile(path):
            os.remove(path)
            removed.append(path)
    log("[OK] 已移除：" + (", ".join(removed) if removed else "（没有找到已安装的命令）"))


def main(argv=None):
    p = argparse.ArgumentParser(prog="install.py", description="7FA4 终端安装程序")
    p.add_argument("--dir", help="命令安装目录（默认 Python 的 Scripts 目录）")
    p.add_argument("--no-deps", action="store_true", help="不安装/升级依赖")
    p.add_argument("--paramiko", action="store_true", help="额外安装 paramiko（SFTP 功能）")
    p.add_argument("--with-pil", action="store_true", help="额外安装 Pillow（export 导出 PNG）")
    p.add_argument("--uninstall", action="store_true", help="移除已生成的 7fa4 命令")
    p.add_argument("--dry-run", action="store_true", help="只打印计划，不写入文件")
    args = p.parse_args(argv)

    target_dir = os.path.abspath(args.dir) if args.dir else scripts_dir()
    log("== 7FA4 终端 安装程序 ==")

    if args.uninstall:
        uninstall(target_dir)
        return 0

    check_python()
    install_deps(args)
    path = install_command(target_dir, args.dry_run)
    verify(args.dry_run)

    log("")
    log(f"[完成] 已安装命令：{path}")
    if not on_path(target_dir):
        log(f"[提示] {target_dir} 不在 PATH 里，把它加进去再重开终端，否则敲 7fa4 会 command not found")
        if os.name == "nt":
            log(f"       PowerShell: setx PATH \"$env:PATH;{target_dir}\"")
        else:
            shell = os.path.basename(os.environ.get("SHELL") or "")
            rc = "~/.zshrc" if shell == "zsh" else "~/.bashrc"
            log(f"       echo 'export PATH=\"{target_dir}:$PATH\"' >> {rc} && source {rc}")
            log(f"       本次会话临时生效： export PATH=\"{target_dir}:$PATH\"")
    log("")
    log("下一步：")
    log("  7fa4 login -u 用户名 -p 密码     # 登录并保存会话")
    log("  7fa4 list 6.5.5                  # 看题目列表")
    log("  7fa4 pull Q6.4.6.1               # 拉题面 + 样例")
    log("发布新版本：python upload.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[已取消]")
        sys.exit(130)
