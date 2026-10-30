#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""7FA4 OJ 终端客户端（argparse 命令行 + requests）

命令一览：
    login     登录 jx.7fa4.cn:8888 / in.7fa4.cn:8888 并保存会话
    logout    清除本地会话
    whoami    查看当前登录状态
    list      题目列表（支持章节号：list 1.2.1 / list 6.5.5）
    pull      获取题目：题面 + 图片（下载到 images/）+ 样例（自动解压 zip）+ 生成 C++ 文件
    statement 只看题面
    submit    提交代码并跟进评测状态（--no-watch 关闭；外站题直连 vjudge，AC 才同步到 7FA4；
              --via 7fa4 时会把验证码图片在终端画出来并保存/打开）
    push      把 vjudge 上已 AC 的记录同步到 7FA4（不重复提交）
    vjlogin   用 vjudge 账号密码登录并保存会话（替代手抠 JSESSIONID）
    vjcheck   检查 vj_cookie 是否还有效
    task      继续查看某个 vjudge 任务（--via 7fa4 代理提交时会给任务号）
    tasks     列出 7FA4 上的 vjudge 任务
    run       编译并在样例上运行（多份 cpp 时跑 pull 那份；输出/错误写到 <名>.out/.err）
    submission 查看提交：状态用 /submissions/?id=123，代码用 /submission/123（会问是否继续）
    submissions 提交记录查询：分页 + 题目/提交者/状态/语言/分数筛选
    plan      计划按天读写：plan show 明天 / plan add 后天 -m "..." -p "71354"
    review    站点复盘(tag)：show 查看 / timeline -i N 改时间线 / set -q 题目 改某题
    help      分级帮助：help 总览，help <命令> 看参数
    paper     纸面题答案图片：get 备份 / submit 上传 / restore 还原
    export    把题面 markdown 导出成 PNG（本地图片会一起嵌入）
    sftp      SFTP 存储（5307 端口）：login/ls/pwd/cd/lcd/get/put/mkdir/rm/rmdir
              本地文件默认走项目下的 sftp/ 目录，cd 切换远程当前目录（记在 config）
    template  查看/设置自己的代码模板（占位符 {{id}} {{no}} {{title}} {{short}} {{url}} {{date}}）
    config    查看/修改本地配置（host / vj_cookie / template）
    get/post/raw  直接发 HTTP 请求
    shell     交互式终端

题目参数支持三种写法：ID（72874）、题号（Q6.4.6.1 / 6.4.6.1）、标题关键字。

站点：jx.7fa4.cn 走公网、in.7fa4.cn 走校内网，默认自动探测可用站点并记录到 config.json，
也可用 --host in / --host jx 显式指定。

配置（config.json，位于 %APPDATA%\7fa4_terminal\，可用 --config PATH 或环境变量 7FA4_CONFIG 覆盖）：
host 站点、language 默认提交语言、vj_cookie vjudge 会话、template 代码模板、
sessions 各站点登录态（自动维护）。

示例：
    python 7fa4_terminal.py login -u 用户名 -p 密码
    python 7fa4_terminal.py list 6.5.5
    python 7fa4_terminal.py pull Q6.4.6.1
    python 7fa4_terminal.py statement 6.4.6.1 -h
    python 7fa4_terminal.py template set my_template.cpp
    python 7fa4_terminal.py run Q6.4.6.1
    python 7fa4_terminal.py submit Q6.4.6.1 -l cpp17
    python 7fa4_terminal.py pull Q6.5.5.1 --vj-cookie "JSESSIONID=xxx"   # 外站题拉题面
    python 7fa4_terminal.py submit Q6.5.5.1                             # 直连 vjudge，AC 才同步到 7FA4
    python 7fa4_terminal.py submit Q6.5.5.1 --via 7fa4                   # 改走站点代理
    python 7fa4_terminal.py push Q6.5.5.1 --rid 73684626                 # 手动同步某次 AC 记录
"""

import argparse
import base64
import datetime
import getpass
import hashlib
import html as htmllib
import io
import json
import os
import posixpath
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import unicodedata
import time
import urllib.parse
import zipfile

import requests

PASSWORD_SALT = "syzoj2_xxx"
HOSTS = {"jx": "jx.7fa4.cn", "in": "in.7fa4.cn"}
DEFAULT_HOST = "in"  # 两个站点都可达时优先用它；实际默认是自动探测
DEFAULT_PORT = 8888
PROBE_TIMEOUT = 2.0
# jx 走公网（211.137.101.118），in 走校内网（10.210.57.10），只能二选一，所以自动探测
HOST_CACHE = {}

VJ_BASE = "https://vjudge.net"
# 7FA4 的“外站题号”用的 oj 代号 -> vjudge 的 OJ 名称
VJ_OJ_NAMES = {
    "luogu": "洛谷", "cf": "CodeForces", "codeforces": "CodeForces",
    "atcoder": "AtCoder", "uoj": "UOJ", "qoj": "QOJ", "loj": "LibreOJ",
    "nowcoder": "NowCoder", "hdu": "HDU", "poj": "POJ", "codechef": "CodeChef",
    "spoj": "SPOJ", "acwing": "AcWing", "gym": "CodeForces::Gym",
}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.join(BASE_DIR, "problems")
def user_config_dir():
    """配置目录：Windows=%APPDATA%，macOS=Application Support，其它=XDG_CONFIG_HOME/~/.config。"""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "7fa4_terminal")


CONFIG_DIR = user_config_dir()
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
# 老位置（项目目录 / %Temp%），启动时自动搬过来
LEGACY_CONFIG_FILES = [
    os.path.join(BASE_DIR, "config.json"),
    os.path.join(tempfile.gettempdir(), "7fa4_terminal", "config.json"),
]
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

ERRORS = {
    1001: "用户不存在",
    1002: "密码错误",
    1003: "您尚未设置密码，请通过「找回密码」设置",
    1004: "账号长时间未登录，已暂停使用",
    1005: "当前无可用排课（课内无课）",
}

CPP_TEMPLATE = """#include <bits/stdc++.h>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
{{freopen}}
    return 0;
}
"""

# 题面里判断输入输出方式的写法（见 detect_io）


# ---------------------------------------------------------------- 工具
def resolve_host(value):
    value = (value or DEFAULT_HOST).strip().lower()
    return HOSTS.get(value, value)


def host_reachable(host, port, timeout=PROBE_TIMEOUT):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def pick_host(value, port):
    """--host 显式指定就用它；否则自动探测：上次可用的 > in > jx，结果记到 config.json。"""
    if value and str(value).strip().lower() not in ("auto", "", "none"):
        return resolve_host(value)
    if "host" in HOST_CACHE:
        return HOST_CACHE["host"]

    cfg = load_config()
    saved = cfg.get("host")
    candidates = []
    if saved:
        candidates.append(resolve_host(saved))
    for key in (DEFAULT_HOST, "jx", "in"):
        host = HOSTS[key]
        if host not in candidates:
            candidates.append(host)

    for host in candidates:
        if host_reachable(host, port):
            HOST_CACHE["host"] = host
            if cfg.get("host") != host:
                cfg["host"] = host
                try:
                    save_config(cfg)
                except OSError:
                    pass
            if host != HOSTS[DEFAULT_HOST]:
                print(f"[站点] 自动选择 {host}:{port}（{HOSTS[DEFAULT_HOST]}:{port} 不可达）")
            return host

    # 都不可达，先按默认走，报错信息里能看到具体原因
    print(f"[警告] {port} 端口上两个站点都连不上，先按 {HOSTS[DEFAULT_HOST]} 尝试")
    return HOSTS[DEFAULT_HOST]


def sanitize_name(name, default="problem"):
    name = (name or "").strip()
    name = re.sub(r"[\\/:*?\"<>|\s]+", "_", name)
    return name.strip("_") or default


def strip_tags(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def disp_width(text):
    """终端显示宽度：中文/全角算 2 列。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in str(text or ""))


def pad(text, width, align="left"):
    """按显示宽度补齐，超长按字符截断。"""
    text = str(text or "")
    if disp_width(text) > width:
        cut = ""
        for ch in text:
            if disp_width(cut + ch) > width:
                break
            cut += ch
        text = cut
    gap = max(0, width - disp_width(text))
    return (text + " " * gap) if align == "left" else (" " * gap + text)


# ---------------------------------------------------------------- 配置 / 模板
_CONFIG_MIGRATED = False


def set_config_path(path):
    """切换配置文件位置（--config / 7FA4_CONFIG）。显式指定时不再做自动迁移。"""
    global CONFIG_FILE, CONFIG_DIR, _CONFIG_MIGRATED
    target = os.path.abspath(os.path.expanduser(str(path).strip()))
    CONFIG_DIR = os.path.dirname(target) or "."
    CONFIG_FILE = target
    _CONFIG_MIGRATED = True
    return CONFIG_FILE


def migrate_config():
    """把老位置（项目目录 / %Temp%）的 config.json 搬到 %APPDATA%，只尝试一次。"""
    global _CONFIG_MIGRATED
    if _CONFIG_MIGRATED:
        return
    _CONFIG_MIGRATED = True
    if os.path.exists(CONFIG_FILE):
        return
    for legacy in LEGACY_CONFIG_FILES:
        if not os.path.exists(legacy):
            continue
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            shutil.move(legacy, CONFIG_FILE)
            print(f"[迁移] {legacy} -> {CONFIG_FILE}")
            return
        except OSError as exc:
            print(f"[警告] 迁移 config.json 失败：{exc}")


def load_config():
    migrate_config()
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


DEFAULT_LANGUAGE = "cpp17"


def default_language():
    """config.json 里的 language，没配置就 cpp17。"""
    value = load_config().get("language")
    return str(value).strip() if value else DEFAULT_LANGUAGE


def mask_config(cfg):
    """展示用：把会话 cookie 与 vj_cookie 打码。"""
    out = dict(cfg)
    sessions = cfg.get("sessions")
    if isinstance(sessions, dict):
        out["sessions"] = {
            key: ({**value, "cookies": {name: "***" for name in (value.get("cookies") or {})}}
                  if isinstance(value, dict) else value)
            for key, value in sessions.items()
        }
    if out.get("vj_cookie"):
        out["vj_cookie"] = "***"
    return out


def resolve_template_file(explicit=None):
    """返回模板路径：优先命令行 --template，其次 config.json 里配置的。"""
    if explicit:
        return explicit
    value = load_config().get("template")
    if value:
        path = value if os.path.isabs(value) else os.path.join(BASE_DIR, value)
        if os.path.exists(path):
            return path
    return None


def html_plain_text(html):
    """HTML -> 纯文本：块级元素换行、表格单元格用空格分开，保留「输入文件：x.in」这种写法。"""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?i)</t[dh]>", " ", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|table|section|pre)>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = htmllib.unescape(text).replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", text)


# 「输入文件：data.in」这类说法里，文件名的形态
IO_VALUE = r"([^\s，。；、,;:：<>\"'（）()]{1,60})"
IO_SKIP_WORDS = ("标准", "无", "不给", "省略", "同上", "格式", "说明", "文件", "以下", "见")

IO_IN_PATTERNS = (
    r"输入文件(?:名)?\s*(?:为|是)?\s*[:：]\s*" + IO_VALUE,
    r"输入文件(?:名)\s*(?:为|是)\s*" + IO_VALUE,
    r"输入文件(?:名)?\s+" + IO_VALUE,          # 表格里：输入文件 | seed.in
    r"从文件\s*" + IO_VALUE + r"\s*(?:中)?(?:读|输入)",
    r"(?:input|in)\s*file(?:name)?\s*(?:is)?\s*[:：]\s*" + IO_VALUE,
)
IO_OUT_PATTERNS = (
    r"输出文件(?:名)?\s*(?:为|是)?\s*[:：]\s*" + IO_VALUE,
    r"输出文件(?:名)\s*(?:为|是)\s*" + IO_VALUE,
    r"输出文件(?:名)?\s+" + IO_VALUE,          # 表格里：输出文件 | seed.out
    r"输出(?:到|至|入)\s*文件\s*" + IO_VALUE,
    r"(?:output|out)\s*file(?:name)?\s*(?:is)?\s*[:：]\s*" + IO_VALUE,
)


def _io_find(text, patterns):
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.I):
            value = (m.group(1) or "").strip().strip(".,;，。；:：`'\"")
            if not value or value in IO_SKIP_WORDS:
                continue
            # 文件名基本是 ASCII；这样能滤掉「输入文件格式」「输入文件如下」这类中文
            if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,64}", value):
                continue
            if any(word in value for word in IO_SKIP_WORDS):
                continue
            return value
    return ""


def detect_io(markdown=None, html=None):
    """从题面猜输入输出：先看页面 HTML，再看 markdown。

    返回 {'mode': 'file'|'stdin', 'input': ..., 'output': ...}
    """
    sources = [text for text in (html_plain_text(html) if html else "", markdown or "") if text]
    infile = outfile = ""
    for text in sources:
        infile = infile or _io_find(text, IO_IN_PATTERNS)
        outfile = outfile or _io_find(text, IO_OUT_PATTERNS)
        if infile and outfile:
            break

    if infile and not outfile:
        outfile = os.path.splitext(infile)[0] + ".out"
    elif outfile and not infile:
        infile = os.path.splitext(outfile)[0] + ".in"
    if not infile and not outfile:
        return {"mode": "stdin", "input": "", "output": ""}
    # 文件名里不该有「/」以外的路径成分，统一取基名，避免拼到临时目录外
    infile = os.path.basename(infile.replace("\\", "/"))
    outfile = os.path.basename(outfile.replace("\\", "/"))
    return {"mode": "file", "input": infile, "output": outfile}


def io_freopen(io):
    """生成 freopen 片段，供模板占位符 {{freopen}} 使用。"""
    if not io or io.get("mode") != "file":
        return ""
    lines = []
    if io.get("input"):
        lines.append(f'    freopen("{io["input"]}", "r", stdin);')
    if io.get("output"):
        lines.append(f'    freopen("{io["output"]}", "w", stdout);')
    return "\n".join(lines)


def problem_io(folder):
    """读本地题目目录 meta.json 里记录的输入输出方式；旧目录没记录就现场从 statement.md 猜。"""
    fallback = {"mode": "stdin", "input": "", "output": ""}
    if not folder:
        return fallback
    path = os.path.join(folder, "meta.json")
    io = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            io = data.get("io")
        except (OSError, ValueError):
            io = None
    if isinstance(io, dict) and io.get("mode"):
        return io
    statement = os.path.join(folder, "statement.md")
    if os.path.exists(statement):
        try:
            with open(statement, encoding="utf-8") as f:
                return detect_io(f.read())
        except OSError:
            pass
    return fallback


def render_template(text, values):
    """支持 {{id}} {{title}} {{short}} {{url}} {{date}} {{infile}} {{outfile}} {{freopen}} 占位符。"""
    for key, value in values.items():
        text = text.replace("{{%s}}" % key, str(value))
    return text


def default_template_text():
    return CPP_TEMPLATE


# ---------------------------------------------------------------- 题号
NO_PATTERN = re.compile(r"^\s*([A-Za-z]?)(\d+(?:\.\d+)*)\.\s*(.*)$")


def split_problem_name(name):
    """'Q6.5.5.1. 序列' -> ('Q6.5.5.1', '序列')；识别不了返回 ('', name)。"""
    m = NO_PATTERN.match(name or "")
    if not m:
        return "", (name or "").strip()
    prefix, digits, title = m.groups()
    return f"{prefix}{digits}", title.strip()


def no_digits(no):
    """去掉题号前缀字母并小写：'Q6.5.5.1' -> '6.5.5.1'"""
    return re.sub(r"^[A-Za-z]+", "", no or "").strip().lower()


def no_sort_key(no):
    digits = re.findall(r"\d+", no or "")
    return tuple(int(x) for x in digits)


def is_problem_no(token):
    token = (token or "").strip()
    return bool(re.fullmatch(r"[A-Za-z]?\d+(?:\.\d+)+", token))


def search_problems(client, query):
    r = client.get("/api/v2/search/problems/" + requests.utils.quote(str(query)))
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"搜索接口返回异常（HTTP {r.status_code}）")
    if not data.get("success"):
        raise RuntimeError("搜索失败，请确认已登录")
    return data.get("results") or []


def resolve_problem(client, token):
    """把 77425 / Q6.1.1.1 / 6.1.1.1 / 标题关键字 解析成 (题目ID, 显示名)。"""
    token = (token or "").strip()
    if not token:
        raise RuntimeError("题目参数为空")
    if token.isdigit():
        return token, token

    as_no = re.match(r"^([A-Za-z]?)(\d+(?:\.\d+)+)$", token)
    query = as_no.group(2) if as_no else token
    results = search_problems(client, query)
    if not results:
        # 未登录时站点搜索照样返回 success 但 0 条，很容易被误判成「题目不存在」
        logged = True
        try:
            logged, _ = client.whoami()
        except RuntimeError:
            pass
        if not logged:
            raise RuntimeError("未登录（或会话已过期），站点搜索对未登录用户返回空结果；"
                               "先执行 login 再试")
        raise RuntimeError(f"没有匹配的题目：{token}")

    if as_no:
        prefix, digits = (as_no.group(1) or "").upper(), as_no.group(2)
        cands = []
        for item in results:
            no, title = split_problem_name(item.get("name", ""))
            if not no:
                continue
            letters = re.sub(r"[^A-Za-z]", "", no).upper()
            d = no_digits(no)
            if not (d == digits or d.startswith(digits + ".")):
                continue
            if prefix and letters != prefix:
                continue
            cands.append((d == digits, no, title, str(item["value"])))
        exact = [c for c in cands if c[0]]
        chosen = exact or cands
        if len(chosen) == 1:
            _, no, title, pid = chosen[0]
            return pid, f"{no}. {title}"
        if not chosen:
            raise RuntimeError(f"没有匹配的题号：{token}")
        listing = "\n".join(f"  {no}. {title}  ->  {pid}" for _, no, title, pid in chosen[:20])
        raise RuntimeError(f"题号 {token} 匹配到多道题，请写更完整（可加 L/Q/H 前缀）：\n{listing}")

    if len(results) == 1:
        no, title = split_problem_name(results[0]["name"])
        return str(results[0]["value"]), (f"{no}. {title}" if no else results[0]["name"])

    listing = "\n".join(f"  {r['name']}  ->  {r['value']}" for r in results[:15])
    raise RuntimeError(f"关键字 {token} 匹配到多道题，请用题号或更精确的关键字：\n{listing}")


# ---------------------------------------------------------------- 客户端
class Client:
    """会话按站点保存在 config.json 的 sessions.<host>:<port> 里"""

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=15.0):
        self.host = resolve_host(host)
        self.port = port
        self.timeout = timeout
        self.base = f"https://{self.host}:{self.port}"
        self.username = None
        self.session_key = f"{self.host}:{self.port}"
        # 为 False 时请求不会把当前 cookie 写回配置（用于「先验证再保存」的场景）
        self.autosave = True
        # 旧版本的独立会话文件（启动时自动迁移进 config.json）
        self.legacy_session_file = os.path.join(BASE_DIR, f"session_{self.host}_{self.port}.json")
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (7fa4-terminal)",
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
        })

    # ---------- 会话 ----------
    def _put_cookies(self, cookies):
        """按站点域名放 cookie：直接 update(dict) 会生成无域名版本，
        和服务端下发的同名 cookie 并存，请求头里会出现两个 connect.sid（旧的在前）。"""
        for name, value in (cookies or {}).items():
            if name and value:
                self.s.cookies.set(name, value, domain=self.host, path="/")

    def load_session(self):
        entry = (load_config().get("sessions") or {}).get(self.session_key)
        if isinstance(entry, dict) and entry.get("cookies"):
            self.s.cookies.clear()
            self._put_cookies(entry["cookies"])
            self.username = entry.get("username")
            return True

        if os.path.exists(self.legacy_session_file):
            try:
                with open(self.legacy_session_file, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {}
            if data.get("cookies"):
                self.s.cookies.clear()
                self._put_cookies(data["cookies"])
                self.username = data.get("username")
                self.save_session()
                try:
                    os.remove(self.legacy_session_file)
                    print(f"[迁移] {os.path.basename(self.legacy_session_file)} -> config.json")
                except OSError:
                    pass
                return True
        return False

    def save_session(self):
        if not self.s.cookies:
            return
        cfg = load_config()
        sessions = cfg.get("sessions")
        if not isinstance(sessions, dict):
            sessions = {}
        fresh = requests.utils.dict_from_cookiejar(self.s.cookies)
        old = (sessions.get(self.session_key) or {}).get("cookies") or {}
        # 服务端有时会回一个空的 set-cookie（例如 login=;），别用它盖掉本地已有的值
        for name, value in old.items():
            if value and not fresh.get(name):
                fresh[name] = value
        sessions[self.session_key] = {
            "username": self.username or (sessions.get(self.session_key) or {}).get("username"),
            "cookies": fresh,
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        cfg["sessions"] = sessions
        save_config(cfg)

    def clear_session(self):
        self.s.cookies.clear()
        self.username = None
        cfg = load_config()
        sessions = cfg.get("sessions")
        if isinstance(sessions, dict) and sessions.pop(self.session_key, None) is not None:
            if sessions:
                cfg["sessions"] = sessions
            else:
                cfg.pop("sessions", None)
            save_config(cfg)

    # ---------- 请求 ----------
    def request(self, method, path, data=None, params=None, files=None, json=None,
                allow_redirects=True, headers=None):
        url = path if path.startswith("http") else self.base + path
        try:
            r = self.s.request(method.upper(), url, data=data, params=params, files=files, json=json,
                               headers=headers, timeout=self.timeout, allow_redirects=allow_redirects)
        except requests.RequestException as exc:
            raise RuntimeError(f"请求失败: {type(exc).__name__}: {exc}") from exc
        if self.autosave:
            self.save_session()
        return r

    def get(self, path, **kw):
        return self.request("get", path, **kw)

    def post(self, path, data=None, **kw):
        return self.request("post", path, data=data, **kw)

    # ---------- 登录 ----------
    def login(self, username, password):
        digest = hashlib.md5((password + PASSWORD_SALT).encode()).hexdigest()
        r = self.post("/api/login", data={"username": username, "password": digest},
                      headers={
                          "X-Requested-With": "XMLHttpRequest",
                          "Accept": "application/json, text/javascript, */*; q=0.01",
                          "Referer": f"{self.base}/login",
                          "Origin": self.base,
                      })
        self.last_login_response = {
            "status": r.status_code,
            "set_cookie": r.headers.get("Set-Cookie") or "",
            "content_type": r.headers.get("Content-Type") or "",
        }
        try:
            data = r.json()
        except ValueError:
            return False, f"登录响应不是 JSON（HTTP {r.status_code}）：{r.text[:120]}"
        code = data.get("error_code")
        if code in (None, 1, "1"):
            self.username = username
            # 页面登录成功后浏览器会把 data.session_id 存成 login cookie，命令行也得自己写
            session_id = data.get("session_id")
            if session_id:
                self.s.cookies.set("login", str(session_id), domain=self.host, path="/")
            self.last_login_fields = sorted(str(k) for k in data.keys())
            self.save_session()
            return True, "登录成功"
        return False, ERRORS.get(code, f"登录失败，error_code={code}（{data}）")

    def whoami(self):
        r = self.get("/")
        logged = ("/logout" in r.text) or ("退出" in r.text)
        if not logged:
            self.username = None
        return logged, r

    # ---------- 题目 ----------
    def problem_meta(self, pid):
        r = self.get(f"/problem/{pid}")
        html = r.text
        self._last_problem_html = {"pid": str(pid), "html": html}
        if "错误 - 7FA4" in (re.findall(r"<title>(.*?)</title>", html, re.S) or [""])[0]:
            raise RuntimeError(f"题目 {pid} 不存在或无权访问（请确认已登录）")
        title = re.findall(r"<title>(.*?)</title>", html, re.S)[0]
        title = re.sub(r"\s*-\s*题目\s*-\s*7FA4\s*$", "", title).strip()
        meta = {"id": str(pid), "title": title, "url": f"{self.base}/problem/{pid}"}
        patterns = {
            "memory": r"内存限制：\s*([^<\n]*)",
            "time": r"时间限制：\s*([^<\n]*)",
            "type": r"题目类型：\s*([^<\n]*)",
            "judge": r"评测方式：\s*([^<\n]*)",
            "short": r"题目名称：\s*([^<\n]*)",
            "foreign": r"外站题号：\s*([^<\n]*)",
        }
        for key, pat in patterns.items():
            m = re.search(pat, html)
            meta[key] = htmllib.unescape(m.group(1)).strip() if m else ""
        m = re.search(r"<form[^>]*action=\"([^\"]+)\"[^>]*id=\"submit_code\"", html)
        meta["submit_action"] = htmllib.unescape(m.group(1)) if m else f"/problem/{pid}/submit"
        meta["languages"] = []
        for m in re.finditer(r"data-value=\"([^\"]+)\"[^>]*>([\s\S]*?)</a>", html):
            value, label = m.group(1), strip_tags(m.group(2)).split(" GCC")[0].split(" Clang")[0]
            if value and not value.startswith("/"):
                meta["languages"].append({"value": value, "label": label})
        return meta

    def problem_markdown(self, pid):
        r = self.get(f"/problem/{pid}/markdown/html")
        if r.status_code != 200:
            raise RuntimeError(f"获取题面失败（HTTP {r.status_code}）")
        m = re.search(r"<pre[^>]*>([\s\S]*)</pre>", r.text)
        text = htmllib.unescape(m.group(1) if m else r.text)
        return text.replace("\r\n", "\n").strip("\n")

    def problem_html(self, pid):
        """题目页 HTML，problem_meta 取过的就复用，避免重复请求。"""
        cached = getattr(self, "_last_problem_html", None)
        if cached and cached.get("pid") == str(pid):
            return cached["html"]
        html = self.get(f"/problem/{pid}").text
        self._last_problem_html = {"pid": str(pid), "html": html}
        return html

    def problem_rendered_markdown(self, pid, html=None):
        """把渲染后的题面 HTML 转回 markdown（题面源码有误时以它为准）。"""
        page = html or self.problem_html(pid)
        if "错误 - 7FA4" in page and "请登录" in page:
            raise RuntimeError(f"题目 {pid} 需要登录后才能查看")
        text = html_to_text(extract_statement_html(page))
        if len(text) < 40:
            raise RuntimeError("渲染后的题面为空")
        # 容器没定位对时会混进提交表单/统计等信息，这种结果不如直接用源码
        noisy = sum(word in text for word in
                    ("提交代码", "评测记录", "相关文件", "题目信息", "我的提交", "题解"))
        if noisy >= 2:
            raise RuntimeError("HTML 里没定位到题面正文")
        return text

    def problem_additional_zip(self, pid):
        """相关文件 / 样例压缩包，没有则返回 None。"""
        r = self.get(f"/problem/{pid}/download/additional_file")
        if r.status_code != 200 or not r.content.startswith(b"PK"):
            return None
        return r.content

    # ---------- 提交 ----------
    def submit(self, pid, language, code, filename="answer.cpp"):
        meta = self.problem_meta(pid)
        action = meta["submit_action"]
        languages = {item["value"] for item in meta["languages"]}
        if languages and language not in languages:
            raise RuntimeError(f"不支持的语言 {language}，可选：{', '.join(sorted(languages))}")
        files = {
            "language": (None, language),
            "code": (None, code, "text/plain"),
        }
        r = self.request("post", action, files=files, allow_redirects=False)
        return r, meta

    # ---------- 纸面题 ----------
    def paper_current_answer(self, pid):
        """读出当前已提交的答案图片：{'sid', 'content', 'content_type'}"""
        html = self.get(f"/problem/{pid}").text
        m = re.search(r"/problem/%s/answer/(\d+)" % re.escape(str(pid)), html)
        if not m:
            return None
        sid = m.group(1)
        r = self.get(f"/problem/{pid}/answer/{sid}")
        if r.status_code != 200 or not r.content:
            return None
        return {"sid": sid, "content": r.content,
                "content_type": r.headers.get("Content-Type", "")}

    def paper_submit(self, pid, filename, data, content_type="image/png"):
        action = f"/problem/{pid}/submit?contest_id=&limit=true"
        return self.request("post", action, files={"answer": (filename, data, content_type)},
                            allow_redirects=False)

    # ---------- 外站题（vjudge 代理） ----------
    def vjudge_submit(self, pid, language, code):
        r = self.post("/vjudge/submit", data={"problem_id": pid, "code": code, "language": language})
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"vjudge 提交返回异常（HTTP {r.status_code}）：{r.text[:200]}")
        if not data.get("success"):
            raise RuntimeError(f"vjudge 提交失败：{data.get('err') or data}")
        return data.get("task_id")

    def vjudge_task(self, task_id):
        r = self.get(f"/vjudge/task/{task_id}")
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"任务查询返回异常（HTTP {r.status_code}）：{r.text[:200]}")
        if not data.get("success"):
            raise RuntimeError(f"任务查询失败：{data.get('err') or data}")
        return data.get("task") or {}

    def vjudge_captcha(self, task_id, text):
        r = self.post(f"/vjudge/task/{task_id}/submit-captcha", data={"captcha": text})
        try:
            return r.json()
        except ValueError:
            return {"success": False, "err": f"HTTP {r.status_code}"}


# ---------------------------------------------------------------- 输出
def dump_response(r, full=False, limit=4000):
    ctype = r.headers.get("Content-Type", "")
    print(f"[HTTP {r.status_code}] {ctype} {len(r.content)} bytes")
    if "json" in ctype:
        try:
            text = json.dumps(r.json(), ensure_ascii=False, indent=2)
            print(text if full else text[:limit])
            return
        except ValueError:
            pass
    text = r.text
    print(text if full or len(text) <= limit else text[:limit] + f"\n... [已截断，共 {len(text)} 字符]")


def parse_kv(items):
    data = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"参数格式应为 k=v：{item}")
        k, v = item.split("=", 1)
        data[k] = v
    return data


def make_client(args):
    port = args.port
    return Client(pick_host(getattr(args, "host", None), port), port, args.timeout)


# ---------------------------------------------------------------- 题面 / 样例
SAMPLE_SECTION = re.compile(r"^#{1,6}\s*样例\s*(\d+)\s*(输入|输出)\s*$(.*?)(?=^#{1,6}\s|\Z)", re.M | re.S)
CODE_FENCE = re.compile(r"```[^\n]*\n([\s\S]*?)```")


def parse_samples(markdown):
    """返回 {(序号, '输入'|'输出'): 内容}"""
    samples = {}
    for m in SAMPLE_SECTION.finditer(markdown):
        idx, kind, block = int(m.group(1)), m.group(2), m.group(3)
        fence = CODE_FENCE.search(block)
        content = fence.group(1) if fence else block.strip()
        samples[(idx, kind)] = content.rstrip("\n") + "\n"
    return samples


def render_statement(markdown):
    text = re.sub(r"<img[^>]*>", "[图片]", markdown)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[图片]", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------- 外站题
def parse_foreign(text):
    """'luogu#P4597' -> ('luogu', 'P4597')"""
    m = re.match(r"^\s*([A-Za-z0-9_]+)\s*#\s*(\S+)\s*$", text or "")
    if not m:
        return None, None
    return m.group(1).lower(), m.group(2)


def vjudge_key(oj, prob):
    return f"{VJ_OJ_NAMES.get((oj or '').lower(), oj)}-{prob}"


def vjudge_url(oj, prob):
    return f"{VJ_BASE}/problem/{urllib.parse.quote(vjudge_key(oj, prob))}"


def html_to_text(html):
    """把渲染后的题面 HTML 转成 markdown（标题/列表/代码块/表格/公式尽量保留）。"""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html or "")

    # MathJax 会把公式渲染成一大坨 SVG，只保留 <title> 里的原始 TeX
    text = re.sub(r"(?is)<span class=\"mjpage\">[\s\S]*?<title[^>]*>([\s\S]*?)</title>[\s\S]*?</span>",
                  lambda m: "$%s$" % strip_tags(m.group(1)), text)

    # 图片保留成 markdown，方便后面下载成本地文件
    text = re.sub(r"(?is)<img[^>]*src=\"([^\"]+)\"[^>]*>",
                  lambda m: f"\n![图片]({htmllib.unescape(m.group(1))})\n", text)

    # 代码块：内容去掉标签后包进 ``` 栅栏（源码里的换行要保留，先挖出来占位）
    stash = []

    def code_block(match):
        body = re.sub(r"(?is)<br\s*/?>", "\n", match.group(1))
        body = re.sub(r"<[^>]+>", "", body)
        body = htmllib.unescape(body).strip("\n")
        stash.append("```\n%s\n```" % body)
        return "\n\x00CODE%d\x00\n" % (len(stash) - 1)

    text = re.sub(r"(?is)<pre[^>]*>([\s\S]*?)</pre>", code_block, text)

    # 其余部分把源码里的换行/缩进折成空格，否则 SVG 这类多行标签会把一行文字拆散
    text = re.sub(r"[ \t\r\n]+", " ", text)

    # 行内代码
    text = re.sub(r"(?is)<code[^>]*>([\s\S]*?)</code>",
                  lambda m: "`%s`" % strip_tags(m.group(1)), text)

    # 标题：h1 -> #，h2 -> ## …（题面里 h1 一般是题目名，降一级更贴合原来的结构）
    for level in range(1, 7):
        pattern = re.compile(r"(?is)<h%d[^>]*>([\s\S]*?)</h%d>" % (level, level))

        def head(match, lv=level):
            title = strip_tags(match.group(1))
            return "\n%s %s\n" % ("#" * min(lv, 6), title) if title else ""

        text = pattern.sub(head, text)

    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"(?i)</t[dh]>", " | ", text)
    text = re.sub(r"(?i)</tr>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h[1-6]|tr|li|pre|table|blockquote)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = htmllib.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)

    # 把之前挖出来的代码块放回去
    text = re.sub(r"\x00CODE(\d+)\x00", lambda m: "\n" + stash[int(m.group(1))] + "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# 题面正文容器（不同版本模板的写法都试一遍）
STATEMENT_CONTAINERS = (
    r'<div[^>]*id="problem-content"[^>]*>',
    r'<div[^>]*class="[^"]*markdown-body[^"]*"[^>]*>',
    r'<div[^>]*class="[^"]*problem-statement[^"]*"[^>]*>',
    r'<div[^>]*class="[^"]*ui bottom attached segment[^"]*"[^>]*>',
    r'<div[^>]*class="[^"]*\bstatement\b[^"]*"[^>]*>',
)


def extract_balanced_div(html, start):
    """start 指向某个 '<div'，返回该 div 的内部 HTML（自己删掉，嵌套正确配对）。"""
    tag_re = re.compile(r"<div\b[^>]*>|</div\s*>", re.I)
    m = tag_re.match(html, start)
    if not m:
        return ""
    inner_start = m.end()
    depth = 1
    pos = inner_start
    while depth:
        m = tag_re.search(html, pos)
        if not m:
            return html[inner_start:]
        if m.group(0).lower().startswith("</"):
            depth -= 1
            if depth == 0:
                return html[inner_start:m.start()]
        else:
            depth += 1
        pos = m.end()
    return ""


def extract_statement_html(html):
    """从题目页 HTML 里取题面正文；取不到就返回整页（调用方再兜底）。"""
    html = html or ""
    for pattern in STATEMENT_CONTAINERS:
        m = re.search(pattern, html, re.I)
        if not m:
            continue
        fragment = extract_balanced_div(html, m.start())
        if len(strip_tags(fragment)) > 40:
            return fragment

    # 兜底：去掉导航栏、提交表单、脚本，剩下的正文一起转
    body = re.sub(r"(?is)<div[^>]*class=\"[^\"]*\bui menu\b[^\"]*\"[^>]*>[\s\S]*?</div>\s*</div>", " ", html)
    body = re.sub(r"(?is)<form[^>]*id=\"submit_code\"[^>]*>[\s\S]*?</form>", " ", body)
    body = re.sub(r"(?is)<div[^>]*class=\"[^\"]*ui main container[^\"]*\"[^>]*>", " ", body)
    return body


VJ_SECTION_NAMES = {
    "background": "题目背景", "description": "题目描述", "input": "输入格式",
    "output": "输出格式", "hint": "提示", "note": "提示", "notes": "提示",
    "interaction": "交互", "samples": "样例",
}


def _vj_json_textarea(html, name=None, cls=None):
    """vjudge 把数据塞在 <textarea> 里：题目页 name="dataJson"，题面页 class="data-json-container"。"""
    if name:
        pat = r'<textarea[^>]*name="%s"[^>]*>([\s\S]*?)</textarea>' % re.escape(name)
    else:
        pat = r'<textarea[^>]*class="[^"]*%s[^"]*"[^>]*>([\s\S]*?)</textarea>' % re.escape(cls)
    m = re.search(pat, html)
    if not m:
        return None
    try:
        return json.loads(htmllib.unescape(m.group(1)))
    except ValueError:
        return None


def _vj_pick_brief(briefs):
    """优先中文、官方、版本新的题面版本。"""
    def score(b):
        lang = (b.get("lang") or "").lower()
        return (0 if lang.startswith("zh") else 1,
                0 if b.get("official") else 1,
                -int(b.get("version") or 0))
    usable = [b for b in briefs if b.get("publicVisible", True) and b.get("key")]
    return sorted(usable, key=score)[0] if usable else None


def fetch_vjudge_problem(oj, prob, cookie=None, timeout=20):
    """从 vjudge 拿题面（需要登录 cookie），返回 {'markdown','samples','url'}；失败抛 RuntimeError。"""
    key = vjudge_key(oj, prob)
    url = vjudge_url(oj, prob)
    tip = "vjudge 题面需要登录：config set vj_cookie=\"JSESSIONID=...\"（从已登录的浏览器复制）"

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    if cookie:
        sess.headers["Cookie"] = cookie.strip()

    # 1) 题目页：拿到 problemId 和各语言题面版本
    try:
        page = sess.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"访问 vjudge 失败：{exc}") from exc
    if page.status_code == 404:
        raise RuntimeError(f"vjudge 上没有这道题：{key}")
    info = _vj_json_textarea(page.text, name="dataJson")
    if not info:
        raise RuntimeError(f"vjudge 页面没有题目数据（{tip}）")
    if info.get("hasStatementAccess") is False:
        raise RuntimeError("当前 vjudge 账号无权查看这道题的题面")

    brief = _vj_pick_brief(info.get("descBriefs") or [])
    if not brief:
        raise RuntimeError("vjudge 上没有可用的题面版本（可能是爬取失败）")

    # 2) 题面页：/problem/description/<题面 key>，内容仍是 JSON
    try:
        detail = sess.get(f"{VJ_BASE}/problem/description/{brief['key']}", timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"获取 vjudge 题面失败：{exc}") from exc
    doc = _vj_json_textarea(detail.text, cls="data-json-container")
    if not doc:
        raise RuntimeError(f"vjudge 题面接口没返回数据（HTTP {detail.status_code}，{tip}）")

    parts, samples = [], {}
    sample_no = 0
    for section in doc.get("sections") or []:
        title = (section.get("title") or "").strip()
        value = section.get("value") or {}
        content = value.get("content") or ""
        fmt = (value.get("format") or "MD").upper()
        low = title.lower()

        if low.startswith("sample"):
            sample_no += 1
            pres = re.findall(r"<pre[^>]*>([\s\S]*?)</pre>", content)
            pres = [htmllib.unescape(p).replace("\r\n", "\n").strip("\n") for p in pres]
            if len(pres) >= 2:
                samples[(sample_no, "输入")] = pres[0] + "\n"
                samples[(sample_no, "输出")] = pres[1] + "\n"
            body = "\n\n".join(f"```\n{p}\n```" for p in pres)
            parts.append(f"## 样例 {sample_no}\n\n{body}")
            continue

        body = content if fmt == "MD" else html_to_text(content)
        name = VJ_SECTION_NAMES.get(low, title)
        if name and body.strip():
            parts.append(f"## {name}\n\n{body.strip()}")

    markdown = "\n\n".join(parts).strip()
    if not markdown:
        raise RuntimeError("vjudge 题面是空的")
    return {"markdown": markdown, "samples": samples, "url": url, "key": key}


# ---------------------------------------------------------------- 题面图片导出
IMG_TAG_RE = re.compile(r"(?is)<img[^>]*\bsrc=\"([^\"]+)\"[^>]*>")
MD_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


def abs_image_url(src, base):
    src = htmllib.unescape((src or "").strip())
    if not src or src.startswith("data:"):
        return None
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if src.startswith("/../"):          # 7FA4 题面里的 /../problem/show_image/...
        src = src[4:]
    if src.startswith("/"):
        return base + src
    return base + "/" + src.lstrip("./")


def download_statement_images(client, markdown, folder, referer=None):
    """把题面里引用的图片下载到 images/ 并改成本地相对路径。"""
    if not markdown:
        return markdown, []
    cache, saved = {}, []

    def grab(url, index):
        if url in cache:
            return cache[url]
        try:
            if url.startswith(client.base):
                r = client.get(url)
            else:
                r = requests.get(url, timeout=25, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": referer or client.base + "/",
                })
        except (RuntimeError, requests.RequestException):
            cache[url] = None
            return None
        if r.status_code != 200 or not r.content:
            cache[url] = None
            return None
        ext = os.path.splitext(url.split("?")[0].split("#")[0])[1].lower()
        if ext not in IMAGE_EXTS:
            ext = ".png"
        name = f"img{index}{ext}"
        images_dir = os.path.join(folder, "images")
        os.makedirs(images_dir, exist_ok=True)
        try:
            with open(os.path.join(images_dir, name), "wb") as f:
                f.write(r.content)
        except OSError:
            cache[url] = None
            return None
        rel = f"images/{name}"
        cache[url] = rel
        saved.append(rel)
        return rel

    counter = [0]

    def next_index():
        counter[0] += 1
        return counter[0]

    def replace_tag(match):
        url = abs_image_url(match.group(1), client.base)
        if not url:
            return match.group(0)
        local = grab(url, next_index())
        return f"![图片]({local})" if local else match.group(0)

    def replace_md(match):
        alt, src = match.group(1), match.group(2)
        url = abs_image_url(src, client.base)
        if not url:
            return match.group(0)
        local = grab(url, next_index())
        return f"![{alt}]({local})" if local else match.group(0)

    markdown = IMG_TAG_RE.sub(replace_tag, markdown)
    markdown = MD_IMG_RE.sub(replace_md, markdown)
    return markdown, saved


def problem_dir(pid, short):
    name = sanitize_name(short, str(pid))
    if name == str(pid):
        return os.path.join(WORK_DIR, name)
    return os.path.join(WORK_DIR, f"{pid}_{name}")


def find_problem_dir(pid):
    if not os.path.isdir(WORK_DIR):
        return None
    for name in sorted(os.listdir(WORK_DIR)):
        if name == str(pid) or name.startswith(f"{pid}_"):
            path = os.path.join(WORK_DIR, name)
            if os.path.isdir(path):
                return path
    return None


def write_text(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def read_text_any(path):
    """读取文本文件，UTF-8 失败时退回 GBK（两端系统都可能遇到）。"""
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def pick_language(meta, wanted):
    languages = meta.get("languages") or []
    values = [item["value"] for item in languages]
    if not languages:
        return wanted or "cpp"
    if wanted:
        if wanted in values:
            return wanted
        for item in languages:
            if wanted.lower() in item["label"].lower() or wanted.lower() in item["value"].lower():
                return item["value"]
        raise RuntimeError(f"未找到语言 {wanted}，可选：{', '.join(values)}")
    for candidate in ("cpp17", "cpp14", "cpp11", "cpp"):
        if candidate in values:
            return candidate
    return values[0]


# ---------------------------------------------------------------- 命令
def parse_cookie_text(text):
    """解析 Cookie：'a=1; b=2'、多行 a=1，以及「下载当前凭证」的 YAML（key: value）。"""
    cookies = {}
    for raw in (text or "").splitlines() or []:
        line = raw.strip().rstrip(";")
        if not line or line.startswith("#") or line.startswith("---"):
            continue
        if line.lower().startswith("cookie:"):
            line = line.split(":", 1)[1].strip()
        for chunk in line.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            m = re.match(r"^([A-Za-z0-9_.\-]+)\s*[:=]\s*(\S.*)$", chunk)
            if m:
                name = m.group(1).strip()
                value = m.group(2).strip().strip('"\'')
                if name.lower() not in ("cookie", "path", "domain", "expires", "httponly",
                                        "secure", "samesite", "max-age"):
                    cookies[name] = value
    return cookies


def cmd_login(args):
    client = make_client(args)
    client.load_session()

    # 用浏览器里的 Cookie / 「下载当前凭证」导入，绕过密码登录（有验证码时最省事）
    if getattr(args, "cookie", None) or getattr(args, "cookie_file", None):
        if args.cookie_file:
            if not os.path.exists(args.cookie_file):
                print(f"[错误] 文件不存在：{args.cookie_file}")
                return 1
            text = read_text_any(args.cookie_file)
        else:
            text = args.cookie
        cookies = parse_cookie_text(text)
        if not cookies:
            print("[错误] 没解析出 Cookie（需要形如 login=xxx; connect.sid=yyy）")
            return 1
        # 先关掉自动保存：验证失败时绝不覆盖掉现有的有效会话
        client.autosave = False
        client.s.cookies.clear()
        client._put_cookies(cookies)
        print(f"[Cookie] 导入 {len(cookies)} 项：{', '.join(sorted(cookies))}")
        logged, _ = client.whoami()
        client.autosave = True
        if not logged:
            print("[失败] Cookie 无效或已过期（站点会返回 登录 按钮），已保留原会话")
            return 1
        client.save_session()
        print(f"[OK] 已登录（{client.username or cookies.get('login', '')[:8]}）")
        return 0

    user = args.user or input("用户名: ")
    pwd = args.password if args.password is not None else getpass.getpass("密码: ")
    client.autosave = False          # 登录失败时不把响应里的空 cookie 写回配置
    ok, msg = client.login(user, pwd)
    print(("[OK] " if ok else "[失败] ") + msg)
    if not ok:
        print("[保留] 本地会话未改动")
        return 1
    client.autosave = True
    logged, _ = client.whoami()
    if logged:
        print("[校验] 会话有效")
        jar = requests.utils.dict_from_cookiejar(client.s.cookies)
        print("[会话] " + ", ".join(f"{k}({len(v)})" for k, v in sorted(jar.items())))
        # 用「新进程等价」的干净客户端复验一次：能抓住「当前进程有效、下次失效」的情况
        try:
            fresh = make_client(args)
            fresh.load_session()
            relogged, _ = fresh.whoami()
            print(f"[复验] 重新加载配置后：{'有效' if relogged else '无效（cookie 没存好）'}")
        except RuntimeError:
            pass
        if len(jar.get("login") or "") < 16:
            print("[警告] 站点没有下发有效的 login cookie，换个进程可能就不认账了")
            info = getattr(client, "last_login_response", {}) or {}
            print(f"[诊断] /api/login 状态 {info.get('status')}  "
                  f"Set-Cookie: {(info.get('set_cookie') or '（无）')[:160]}")
            fields = getattr(client, "last_login_fields", [])
            if fields:
                print("[诊断] 登录接口返回字段：" + ", ".join(fields))
            try:
                html = client.get("/").text
                print(f"[诊断] 首页标记：/logout={'/logout' in html}  退出={'退出' in html}  "
                      f"登录={'登录' in html}")
            except RuntimeError:
                pass
        return 0
    print("[校验] 会话无效：站点没有下发可用的 login cookie（可能是验证码/风控，或账号被限制）")
    print("[建议] 在浏览器登录后导入 Cookie：")
    print('       login --cookie "login=...; connect.sid=..."')
    print("       站点右上角「下载当前凭证」得到 YAML 的话：login --cookie-file 凭证.yaml")
    return 1


def cmd_logout(args):
    client = make_client(args)
    client.clear_session()
    print(f"[OK] 已清除 {client.base} 的本地会话")
    return 0


def cmd_whoami(args):
    client = make_client(args)
    client.load_session()
    try:
        logged, _ = client.whoami()
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    print(f"[站点] {client.base}")
    print(f"[状态] {'已登录' if logged else '未登录'}" + (f"（{client.username}）" if client.username else ""))
    jar = requests.utils.dict_from_cookiejar(client.s.cookies)
    print("[会话] " + (", ".join(f"{k}({len(v)})" for k, v in sorted(jar.items())) or "（空）"))
    if not jar:
        print("[提示] 本地没有会话，先执行 login")
    elif len(jar.get("login") or "") < 16:
        print("[提示] 缺少有效的 login cookie（站点登录凭证就是它），用 login 重新登录")
    return 0 if logged else 1


def cmd_list(args):
    client = make_client(args)
    client.load_session()

    # 1) 章节号模式：list 6.1.1 / list Q6.1.1
    if args.path and not args.path.startswith("/"):
        query = args.path.strip()
        if query[:1] in "QqHhLl" and is_problem_no(query[1:]):
            query = query[1:]
        try:
            results = search_problems(client, query)
        except RuntimeError as exc:
            print(f"[错误] {exc}")
            return 1
        wanted = query.lower()
        rows = []
        for item in results:
            no, title = split_problem_name(item.get("name", ""))
            low = no_digits(no)
            if low == wanted or low.startswith(wanted + "."):
                rows.append((no, title, str(item["value"])))
        if not rows:
            logged = True
            try:
                logged, _ = client.whoami()
            except RuntimeError:
                pass
            if not logged:
                print("[错误] 未登录（或会话已过期），站点搜索对未登录用户返回空结果；先执行 login")
                return 1
            print(f"[提示] 章节号 {args.path} 下没有题目")
            return 1
        rows.sort(key=lambda x: no_sort_key(x[0]))
        print(f"[列表] 章节 {args.path} 共 {len(rows)} 题")
        no_w = max(len(no) for no, _, _ in rows)
        title_w = max(len(title) for _, title, _ in rows)
        for no, title, pid in rows:
            print(f"  {no.ljust(no_w)}  {title.ljust(title_w)}  {pid}")
        return 0

    # 2) 路径模式：list /problems/tag/1060506
    path = args.path or "/problems/exercises"
    try:
        r = client.get(path)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    if "错误 - 7FA4" in r.text:
        print(f"[错误] {path} 无法访问（HTTP {r.status_code}），请确认已登录")
        return 1
    rows = []
    seen = set()
    for m in re.finditer(r"<a[^>]+href=\"/problem/(\d+)\"[^>]*>([\s\S]*?)</a>", r.text):
        pid, label = m.group(1), strip_tags(m.group(2))
        if pid == "0" or pid in seen or not label:
            continue
        seen.add(pid)
        rows.append((pid, label))
    if not rows:
        print("[提示] 未解析到题目，可用 get <路径> 查看原始页面")
        return 1
    print(f"[列表] {path} 共 {len(rows)} 题")
    width = max(len(pid) for pid, _ in rows)
    for pid, label in rows:
        print(f"  {pid.ljust(width)}  {label}")
    return 0


def cmd_statement(args):
    client = make_client(args)
    client.load_session()
    try:
        pid, label = resolve_problem(client, args.id)
        meta = client.problem_meta(pid)
        page_html = "" if meta.get("foreign") else client.problem_html(pid)
        markdown = client.problem_markdown(pid)
        if meta.get("foreign") and not markdown.strip():
            oj, prob = parse_foreign(meta["foreign"])
            if oj:
                try:
                    vj = fetch_vjudge_problem(oj, prob, load_config().get("vj_cookie"))
                    markdown = vj["markdown"]
                    print(f"[外站] 题面来自 vjudge：{vj['url']}")
                except RuntimeError as exc:
                    print(f"[外站] {exc}")
        if not meta.get("foreign") and not getattr(args, "from_md", False):
            try:
                rendered = client.problem_rendered_markdown(pid, page_html)
                if len(rendered) >= 40:
                    markdown = rendered
            except RuntimeError:
                pass
        print(f"[题目] {meta['title'] if label == str(pid) else label}  ({meta['url']})")
        limits = " / ".join(filter(None, [meta["type"], meta["judge"], meta["time"], meta["memory"]]))
        if limits:
            print(f"[信息] {limits}")
        if meta.get("foreign"):
            print(f"[外站] 外站题号 {meta['foreign']}")
        print("-" * 60)
        print(render_statement(markdown) or "[题面为空] 该题暂无题面，外站题可用 config set vj_cookie=... 后重试")
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    return 0


def cmd_pull(args):
    client = make_client(args)
    client.load_session()
    try:
        pid, label = resolve_problem(client, args.id)
        meta = client.problem_meta(pid)
        page_html = "" if meta.get("foreign") else client.problem_html(pid)
        markdown = client.problem_markdown(pid)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    if label == str(pid):
        label = meta["title"]

    # 题面源码（markdown）可能本身有误：优先用渲染后的 HTML，失败再退回源码
    from_source = "markdown 源码"
    if not meta.get("foreign") and not getattr(args, "from_md", False):
        try:
            rendered = client.problem_rendered_markdown(pid, page_html)
            if len(rendered) >= 40:
                markdown = rendered
                from_source = "渲染后的 HTML"
        except RuntimeError as exc:
            print(f"[题面] 退回 markdown 源码（{exc}）")

    # 外站题：题面从 vjudge 取（需要 vj_cookie）
    vj_samples, vj_url, vj_note = {}, "", ""
    if meta.get("foreign"):
        oj, prob = parse_foreign(meta["foreign"])
        if oj:
            vj_url = vjudge_url(oj, prob)
            cookie = getattr(args, "vj_cookie", None) or load_config().get("vj_cookie")
            try:
                vj = fetch_vjudge_problem(oj, prob, cookie)
                markdown = vj["markdown"]
                vj_samples = vj["samples"]
                print(f"[外站] 题面来自 vjudge：{vj['url']}")
            except RuntimeError as exc:
                vj_note = str(exc)
                print(f"[外站] {exc}")

    short = sanitize_name(meta.get("short"), str(pid))
    if short.isdigit():
        short = str(pid)
    folder = problem_dir(pid, short)
    os.makedirs(folder, exist_ok=True)

    # 1) 题面
    if vj_note and not markdown.strip():
        markdown = (f"外站题 {meta['foreign']}\n\nvjudge: {vj_url}\n\n> {vj_note}\n")
    markdown, images = download_statement_images(client, markdown, folder, referer=meta["url"])
    write_text(os.path.join(folder, "statement.md"), markdown + "\n")
    if meta.get("foreign") and vj_url:
        write_text(os.path.join(folder, "vjudge.txt"),
                   f"外站题号: {meta['foreign']}\nvjudge: {vj_url}\n")
    # 2) 题面里的样例 -> samples/<i>.in / <i>.out
    samples = parse_samples(markdown)
    samples.update(vj_samples)
    sample_dir = os.path.join(folder, "samples")
    for (idx, kind), content in sorted(samples.items()):
        ext = "in" if kind == "输入" else "out"
        write_text(os.path.join(sample_dir, f"sample{idx}.{ext}"), content)
    # 3) 相关文件 zip（样例压缩包）-> 解压到 samples/
    unzipped = []
    try:
        blob = client.problem_additional_zip(pid)
    except RuntimeError:
        blob = None
    if blob:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                target = os.path.join(sample_dir, os.path.basename(name))
                os.makedirs(sample_dir, exist_ok=True)
                with open(target, "wb") as f:
                    f.write(zf.read(name))
                unzipped.append(os.path.basename(name))
    # 4) C++ 文件（用自定义模板，没配置则用内置模板）
    no, title = split_problem_name(label)
    io_info = detect_io(markdown, html=page_html)
    cpp_path = os.path.join(folder, f"{short}.cpp")
    created = False
    if args.force or not os.path.exists(cpp_path):
        tpl_file = resolve_template_file(args.template)
        if tpl_file and not os.path.exists(tpl_file):
            print(f"[错误] 模板文件不存在：{tpl_file}")
            return 1
        if tpl_file:
            tpl_text = read_text_any(tpl_file)
        else:
            tpl_text = default_template_text()
        content = render_template(tpl_text, {
            "id": pid,
            "title": meta["title"],
            "short": short,
            "url": meta["url"],
            "no": no,
            "date": datetime.date.today().isoformat(),
            "infile": io_info.get("input", ""),
            "outfile": io_info.get("output", ""),
            "io_mode": io_info.get("mode", "stdin"),
            "freopen": io_freopen(io_info),
        })
        if io_info.get("mode") == "file" and "{{freopen}}" not in tpl_text:
            print(f"[提示] 这是文件 IO 题，但模板里没有 {{{{freopen}}}} 占位符；"
                  f"手动加一行 freopen(\"{io_info.get('input')}\", \"r\", stdin) 即可")
        write_text(cpp_path, content)
        created = True
        tpl_desc = tpl_file or "内置模板"
    else:
        tpl_desc = ""
        if io_info.get("mode") == "file" and "freopen" not in read_text_any(cpp_path):
            print(f"[提示] 这是文件 IO 题（{io_info.get('input')}），但 {os.path.basename(cpp_path)} 里没有 freopen；"
                  f"用 pull {args.id} -f 可以按模板重新生成")
    # 5) 元信息
    meta_out = dict(meta)
    meta_out.update({"no": no, "short": short, "cpp": os.path.relpath(cpp_path),
                     "folder": os.path.relpath(folder), "io": io_info})
    if vj_url:
        meta_out["vjudge"] = vj_url
    write_text(os.path.join(folder, "meta.json"), json.dumps(meta_out, ensure_ascii=False, indent=2) + "\n")

    if not args.quiet:
        print(f"[题目] {label if label != str(pid) else meta['title']}  ({meta['url']})")
        limits = " / ".join(filter(None, [meta["type"], meta["judge"], meta["time"], meta["memory"]]))
        if limits:
            print(f"[信息] {limits}")
        if meta.get("foreign"):
            print(f"[外站] 外站题号 {meta['foreign']}" + (f"  题面：{vj_url}" if vj_url else ""))
        print("-" * 60)
        print(render_statement(markdown) or "[题面为空] 未取到题面（可 config set vj_cookie=... 后重试）")
        print("-" * 60)

    print(f"[目录] {folder}")
    print(f"[题面] statement.md（来源：{from_source}）")
    if io_info.get("mode") == "file":
        print(f"[输入输出] 文件：{io_info.get('input')} -> {io_info.get('output')}（模板里的 {{{{freopen}}}} 已填好）")
    else:
        print("[输入输出] 标准输入输出")
    if samples:
        print(f"[样例] {len(samples)} 个块 -> samples/sample<i>.in|.out")
    if unzipped:
        print(f"[解压] {len(unzipped)} 个文件 -> samples/：{', '.join(sorted(unzipped))}")
    if images:
        print(f"[图片] {len(images)} 张 -> images/（statement.md 已改成相对路径）")
    if not samples and not unzipped:
        print("[样例] 该题未提供样例（纸面题或外站题）")
    if vj_url:
        print(f"[外站] {meta['foreign']} -> {vj_url}")
    if created:
        print(f"[代码] {os.path.basename(cpp_path)}（新建，模板：{tpl_desc}）")
    else:
        print(f"[代码] {os.path.basename(cpp_path)}（已存在，-f 可覆盖）")
    return 0


def current_submitter(client):
    """当前用户的学号（/submissions 的 submitter 参数），取到后写进 config 缓存。"""
    cfg = load_config()
    if cfg.get("submitter"):
        return str(cfg["submitter"])
    uid = current_user_id(client)
    html = client.get(f"/user/{uid}").text
    m = re.search(r"<title>\s*(\d+)\s*-\s*用户", html) or re.search(r"\b(20\d{8})\b", html)
    if not m:
        raise RuntimeError("没能取到学号，可 config set submitter=你的学号")
    cfg["submitter"] = m.group(1)
    try:
        save_config(cfg)
    except OSError:
        pass
    return m.group(1)


def fetch_submission_items(client, page=1, **params):
    r = client.get("/submissions", params=dict(params, page=page))
    return extract_json_array(r.text, "itemList") or []


def latest_submission_id(client, submitter):
    items = fetch_submission_items(client, submitter=submitter)
    ids = [int((it.get("info") or {}).get("submissionId") or 0) for it in items]
    return max(ids) if ids else 0


PENDING_WORDS = {"judging", "compiling", "running", "waiting", "pending", "queued", "rejudging",
                 "submitted", "captcha required", "等待评测", "评测中", "等待", "排队中"}


def result_state(item):
    """从 /submissions 的一条里取 (状态文字, 是否出结果, 分数, 用时, 内存)，None 一律当没有。"""
    result = (item or {}).get("result") or {}
    running = bool((item or {}).get("running"))
    text = str(result.get("result") or "").strip()
    if not text:
        text = "评测中" if running else "等待评测"
    final = text.lower() not in PENDING_WORDS and text not in PENDING_WORDS
    score = result.get("score")
    score_text = f"{score:g}" if isinstance(score, (int, float)) else "-"
    return text, final, score_text, result.get("time"), result.get("memory")


def follow_submission(client, submitter, baseline, wait=180.0, interval=1.5):
    """提交后跟进：先找到比 baseline 新的提交编号，再轮询它的评测状态。"""
    start = time.time()
    sid = None
    last = None
    while time.time() - start < wait:
        if sid is None:
            fresh = []
            for item in fetch_submission_items(client, submitter=submitter):
                info = item.get("info") or {}
                try:
                    sid_value = int(info.get("submissionId") or 0)
                except (TypeError, ValueError):
                    continue
                if sid_value > baseline:
                    fresh.append(sid_value)
            if fresh:
                sid = max(fresh)
                print(f"[跟进] 新提交 #{sid}  {client.base}/submission/{sid}")
            else:
                time.sleep(interval)
                continue

        item = fetch_submission_item(client, sid)
        status, final, score_text, time_ms, memory_kb = result_state(item)
        if status != last:
            print(f"[状态] {status}")
            last = status
        if final:
            print(f"[评测] {status}  分数 {score_text}  "
                  f"用时 {time_ms or 0} ms  内存 {memory_kb or 0} KB")
            return status
        time.sleep(interval)

    print(f"[跟进] 等了 {wait:g}s 还没出结果，稍后用 submission {sid} 查看" if sid
          else f"[跟进] 等了 {wait:g}s 没找到新提交，稍后用 submissions 查看")
    return None


def cmd_submit(args):
    client = make_client(args)
    client.load_session()

    try:
        pid, label = resolve_problem(client, args.id)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    source = args.file
    if not source:
        source = pick_source_file(find_problem_dir(pid))
    if not source:
        print("[错误] 未指定代码文件，且本地未找到该题目录，请用 -f 指定")
        return 1
    if not os.path.exists(source):
        print(f"[错误] 代码文件不存在：{source}")
        return 1

    code = read_text_any(source)
    if not code.strip():
        print(f"[错误] 代码为空：{source}")
        return 1

    # 提交后跟进：先记住“最新的提交编号”，提交完再找更新的那条
    follow = not getattr(args, "no_watch", False)
    submitter, baseline = None, 0
    if follow:
        try:
            submitter = current_submitter(client)
            baseline = latest_submission_id(client, submitter)
        except RuntimeError as exc:
            print(f"[跟进] 跳过（{exc}）")
            follow = False

    try:
        meta = client.problem_meta(pid)
        language = pick_language(meta, args.lang or default_language())
        if args.dry_run:
            target = f"vjudge（{meta['foreign']}）" if meta.get("foreign") else meta["submit_action"]
            print(f"[预演] {label}")
            print(f"[预演] 提交目标：{target}")
            print(f"[预演] 语言={language}  文件={source}  {len(code)} 字符")
            return 0
        if meta.get("foreign"):
            return submit_foreign(client, pid, label, meta, language, code, args)
        r, meta = client.submit(pid, language, code, os.path.basename(source))
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    print(f"[提交] {label}  语言={language}  文件={os.path.basename(source)} {len(code)} 字符")
    ctype = r.headers.get("Content-Type", "")
    if r.status_code == 200 and "错误 - 7FA4" in r.text:
        msg = strip_tags(r.text.split('ui main container')[-1])[:300]
        print(f"[结果] 提交被拒绝：{msg or '参数不合法或权限不足'}")
        return 1
    if r.is_redirect or (300 <= r.status_code < 400):
        location = r.headers.get("Location", "")
        print(f"[结果] HTTP {r.status_code} -> {location}")
        m = re.search(r"/submission/(\d+)", location)
        if m:
            print(f"[评测] {client.base}/submission/{m.group(1)}")
        elif follow:
            follow_submission(client, submitter, baseline, wait=getattr(args, "wait", 180.0))
        return 0
    if "json" in ctype:
        try:
            data = r.json()
        except ValueError:
            data = {}
        code_ = data.get("error_code")
        if code_ in (None, 1, "1"):
            print(f"[结果] 提交成功 {data if data else ''}")
            if follow:
                follow_submission(client, submitter, baseline, wait=getattr(args, "wait", 180.0))
            return 0
        print(f"[结果] 提交失败：{ERRORS.get(code_, f'error_code={code_}')} {data}")
        return 1
    print(f"[结果] HTTP {r.status_code} {ctype}")
    print(strip_tags(r.text)[:500])
    return 0 if r.status_code == 200 else 1


RESULT_WORDS = ("Accepted", "Wrong Answer", "Time Limit Exceeded", "Memory Limit Exceeded",
                "Runtime Error", "Compile Error", "Output Limit Exceeded", "Partially Correct",
                "System Error", "Judgement Failed", "File Error", "Pending", "Running", "Judging")


def save_task_result(folder, task):
    """把 vjudge 任务的最终状态记到题目目录的 meta.json（vj 字段）。"""
    if not folder:
        return
    path = os.path.join(folder, "meta.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
    data["vj"] = {
        "task_id": task.get("id") or task.get("task_id"),
        "status": task.get("status"),
        "judge_state_id": task.get("judge_state_id"),
        "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        pass


def show_submission_status(client, sid, folder=None):
    """抓 7FA4 提交页，尽量读出评测结果。"""
    try:
        r = client.get(f"/submission/{sid}")
    except RuntimeError:
        return None
    text = strip_tags(r.text)
    for word in RESULT_WORDS:
        if word in text:
            print(f"[评测] 结果：{word}")
            return word
    return None


def open_with_viewer(path):
    """用系统默认看图工具打开文件，跨平台。"""
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def save_captcha_image(img, name):
    """img 可以是 data:image/... base64、http 链接或纯 base64，返回保存路径或 None。"""
    if not isinstance(img, str) or not img.strip():
        return None
    data = None
    if img.startswith("data:image"):
        try:
            data = base64.b64decode(img.split(",", 1)[1])
        except (IndexError, ValueError):
            return None
    elif img.startswith("http"):
        try:
            r = requests.get(img, timeout=15)
            if r.status_code == 200:
                data = r.content
        except requests.RequestException:
            return None
    else:
        try:
            data = base64.b64decode(img)
        except (ValueError, TypeError):
            return None
    if not data:
        return None
    path = os.path.join(BASE_DIR, name)
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError:
        return None
    return path


def decode_png_gray(data):
    """最小 PNG 解码：8bit、非隔行，返回 (w, h, 灰度二维列表)；不支持则 None。"""
    import struct
    import zlib

    if not data or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos, idat, plte = 8, b"", None
    w = h = bit_depth = color_type = interlace = None
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            w, h, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
        elif ctype == b"PLTE":
            plte = chunk
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
    if not w or not h or bit_depth != 8 or interlace:
        return None
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        return None
    try:
        raw = zlib.decompress(idat)
    except zlib.error:
        return None

    stride = w * channels
    prev = bytearray(stride)
    rows = []
    offset = 0
    for _ in range(h):
        if offset >= len(raw):
            return None
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset:offset + stride])
        offset += stride
        if len(line) < stride:
            return None
        if filter_type == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        rows.append(line)
        prev = line

    gray = []
    for line in rows:
        if color_type == 3:
            if not plte:
                return None
            px = [sum(plte[v * 3:v * 3 + 3]) // 3 if (v * 3 + 2) < len(plte) else 0 for v in line]
        elif channels >= 3:
            px = [(line[i * channels] + line[i * channels + 1] + line[i * channels + 2]) // 3
                  for i in range(w)]
        else:
            px = list(line)
        gray.append(px)
    return w, h, gray


def render_gray_ascii(gray, width, height, max_cols=72, threshold=170):
    """把灰度图压成终端字符画（深色用 █）。"""
    if width > max_cols:
        step = width / max_cols
        cols = max_cols
        gray = [[row[min(width - 1, int(x * step))] for x in range(cols)] for row in gray]
        width = cols
    lines = []
    for y in range(0, height, 2):
        top = gray[y]
        bottom = gray[y + 1] if y + 1 < height else top
        chars = []
        for x in range(width):
            v = (top[x] + bottom[x]) // 2
            chars.append("█" if v < threshold else " ")
        lines.append("".join(chars).rstrip())
    return lines


def show_captcha_inline(path, title="验证码"):
    """尝试在终端里画出图片；成功返回 True。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return False
    decoded = decode_png_gray(data)
    if not decoded:
        return False
    w, h, gray = decoded
    art = [line for line in render_gray_ascii(gray, w, h) if line.strip()]
    if not art:
        return False
    print(f"[{title}] 终端预览：")
    for line in art:
        print("   " + line)
    return True


def watch_task(client, task_id, wait=180.0, interval=2.0, folder=None, open_captcha=True):
    """轮询 /vjudge/task/<id>，处理验证码，完成后打印 7FA4 提交记录。"""
    start = time.time()
    last_status = None
    captcha_tries = 0
    while True:
        try:
            task = client.vjudge_task(task_id)
        except RuntimeError as exc:
            print(f"[错误] {exc}")
            return 1

        status = str(task.get("status") or "").upper()

        if status == "SUBMIT_CAPTCHA":
            captcha_tries += 1
            if captcha_tries > 5:
                print("[失败] 验证码尝试次数过多，稍后用 task 命令继续")
                return 1
            print("[验证码] 7FA4 / vjudge 要求输入验证码")
            img = (task.get("captchaImage") or task.get("captcha")
                   or task.get("captchaUrl") or task.get("captcha_url") or "")
            path = save_captcha_image(img, f"captcha_task{task_id}.png")
            if path:
                inline = show_captcha_inline(path)
                print(f"[验证码] 图片：{path}")
                if not inline and open_captcha:
                    if open_with_viewer(path):
                        print("[验证码] 已用系统看图工具打开，输入图中字符")
                    else:
                        print("[验证码] 打开图片失败，请手动打开上面的路径")
            elif img:
                print(f"[验证码] 图片地址：{img[:120]}")
            else:
                print("[验证码] 没有拿到验证码图片，请到 7FA4 的 VJudge 任务页处理")
            try:
                text = input("验证码: ").strip()
            except (EOFError, KeyboardInterrupt):
                text = ""
            if not text:
                print(f"[暂停] 需要验证码，可用 task {task_id} 在交互终端里继续")
                return 1
            res = client.vjudge_captcha(task_id, text)
            if not res.get("success"):
                print(f"[验证码] {res.get('err') or '提交失败，重试'}")
            continue

        if status != last_status:
            print(f"[状态] {status or '未知'}")
            last_status = status

        if status in ("COMPLETED", "DONE", "FINISHED", "SUCCESS"):
            sid = task.get("judge_state_id")
            print(f"[完成] 7FA4 提交记录：{client.base}/submission/{sid}")
            save_task_result(folder, task)
            show_submission_status(client, sid, folder)
            return 0

        if status in ("FAILED", "ERROR", "CANCELED", "CANCELLED", "CANCEL", "DUPLICATE"):
            err = task.get("error_message") or task.get("err") or ""
            print(f"[失败] 任务 #{task_id}：{err or status}")
            if "重新绑定" in err or "验证码" in err:
                print("[提示] 7FA4 里保存的 vjudge 登录态已失效：去站点的 VJudge 账号页重新绑定一次"
                      "（带验证码登录），然后重新提交")
            save_task_result(folder, task)
            return 1

        if time.time() - start > wait:
            print(f"[超时] 任务 #{task_id} 仍在 {status or '处理中'}，可用 task {task_id} 继续查看")
            return 1

        time.sleep(interval)


# ---------------------------------------------------------------- 直连 vjudge
class VJudge:
    """用 vjudge 的登录 cookie 直接提交、查评测状态（不经过 7FA4 代理）。"""

    def __init__(self, cookie, timeout=30):
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": VJ_BASE,
        })
        if cookie:
            self.s.headers["Cookie"] = cookie.strip()

    def _get(self, path, **kw):
        try:
            return self.s.get(VJ_BASE + path, timeout=self.timeout, **kw)
        except requests.RequestException as exc:
            raise RuntimeError(f"访问 vjudge 失败：{exc}") from exc

    def problem_info(self, oj, prob):
        key = vjudge_key(oj, prob)
        r = self._get("/problem/" + urllib.parse.quote(key))
        if r.status_code == 404:
            raise RuntimeError(f"vjudge 上没有这道题：{key}")
        info = _vj_json_textarea(r.text, name="dataJson")
        if not info:
            raise RuntimeError("vjudge 页面没有题目数据，vj_cookie 可能已失效（重新复制 JSESSIONID）")
        return info

    def username(self, oj, prob):
        return (self.problem_info(oj, prob) or {}).get("username") or ""

    def bindings(self, oj_name):
        r = self._get("/user/remoteAccounts/list", params={"oj": oj_name})
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError("读取 vjudge 远程账号失败（cookie 可能已失效）")
        return ((data.get("groups") or {}).get(oj_name) or {}).get("bindings") or []

    def pick_language(self, oj_name, wanted="cpp17"):
        r = self._get("/util/cfg")
        try:
            cfg = r.json()
        except ValueError:
            raise RuntimeError("读取 vjudge 语言配置失败")
        langs = ((cfg.get("remoteOJs") or {}).get(oj_name) or {}).get("languages") or {}
        if not langs:
            raise RuntimeError(f"vjudge 没有返回 {oj_name} 的语言列表")
        want = (wanted or "cpp17").lower()
        num = re.sub(r"\D", "", want)
        want_o2 = "o2" in want

        def score(item):
            label = (item[1] or "").lower()
            is_cpp = "c++" in label
            hit = is_cpp and (not num or num in label)
            o2 = " o2" in label
            return (0 if hit else 1, 0 if is_cpp else 1, 0 if o2 == want_o2 or o2 else 1, len(label))

        key, label = sorted(langs.items(), key=score)[0]
        return key, label

    def submit(self, oj, prob, code, binding_id, language_value, open_code=0):
        key = urllib.parse.quote(vjudge_key(oj, prob))
        try:
            r = self.s.post(f"{VJ_BASE}/problem/submit/{key}", timeout=self.timeout,
                            headers={"Referer": f"{VJ_BASE}/problem/{key}"},
                            data={"method": 1, "language": language_value, "open": open_code,
                                  "source": code, "bindingId": binding_id})
        except requests.RequestException as exc:
            raise RuntimeError(f"提交到 vjudge 失败：{exc}") from exc
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"vjudge 提交返回异常（HTTP {r.status_code}）：{r.text[:200]}")
        if data.get("challenge"):
            raise RuntimeError("vjudge 触发了人机验证（Turnstile），终端里没法输入；"
                               "请在浏览器提交一次，或用 --via 7fa4（可输图片验证码）")
        if not data.get("runId"):
            raise RuntimeError(f"vjudge 提交失败：{data}")
        return data["runId"]

    def status(self, oj_name, prob, username, run_id):
        try:
            r = self.s.get(VJ_BASE + "/status/data", timeout=self.timeout,
                           params={"draw": 1, "start": 0, "length": 30,
                                   "un": username, "OJId": oj_name, "probNum": prob})
        except requests.RequestException as exc:
            raise RuntimeError(f"查询 vjudge 状态失败：{exc}") from exc
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError("查询 vjudge 状态返回异常")
        for item in data.get("data") or []:
            if str(item.get("runId")) == str(run_id):
                return item
        return {}


PENDING_STATUS = {"", "judging", "pending", "waiting", "queued", "running",
                  "captcha required", "submitted", "processing"}


def watch_vjudge(vj, oj_name, prob, username, run_id, wait=180.0, interval=3.0):
    start = time.time()
    last = None
    while True:
        item = vj.status(oj_name, prob, username, run_id)
        if not item:
            print("[状态] 评测记录还没出现，继续等…")
        else:
            text = item.get("status") or ("评测中" if item.get("processing") else "未知")
            if text != last:
                print(f"[状态] {text}")
                last = text
            running = bool(item.get("processing")) or str(text).strip().lower() in PENDING_STATUS
            if not running:
                return item
        if time.time() - start > wait:
            print(f"[超时] vjudge run {run_id} 仍在评测，可稍后用 vjstatus {run_id} 查看")
            return {}
        time.sleep(interval)


def submit_foreign(client, pid, label, meta, language, code, args):
    """外站题：默认直接提交到 vjudge，只有 AC 才把记录同步到 7FA4。"""
    oj_code, prob = parse_foreign(meta["foreign"])
    if not oj_code:
        print(f"[错误] 无法解析外站题号：{meta.get('foreign')}")
        return 1
    oj_name = VJ_OJ_NAMES.get(oj_code.lower(), oj_code)

    if getattr(args, "via", "vjudge") == "7fa4":
        print(f"[外站] {label}  走 7FA4 代理  外站题号 {meta['foreign']}  语言={language}")
        try:
            task_id = client.vjudge_submit(pid, language, code)
        except RuntimeError as exc:
            print(f"[错误] {exc}")
            return 1
        print(f"[任务] vjudge 任务 #{task_id}")
        if getattr(args, "no_wait", False):
            print(f"[提示] 用 task {task_id} 查看进度")
            return 0
        return watch_task(client, task_id, wait=getattr(args, "wait", 180.0),
                          interval=getattr(args, "interval", 2.0), folder=find_problem_dir(pid),
                          open_captcha=not getattr(args, "no_open", False))

    cookie = getattr(args, "vj_cookie", None) or load_config().get("vj_cookie")
    if not cookie:
        print('[错误] 没有 vj_cookie：先 config set vj_cookie="JSESSIONID=..."')
        return 1

    vj = VJudge(cookie)
    print(f"[外站] {label}  外站题号 {meta['foreign']}  ->  vjudge {oj_name}-{prob}")
    try:
        bindings = [b for b in vj.bindings(oj_name) if b.get("runtimeStatus") == "READY"]
        if not bindings:
            print(f"[错误] vjudge 上没有可用的 {oj_name} 绑定账号，"
                  f"去 {VJ_BASE}/user/remoteAccounts 绑定一个")
            return 1
        binding = bindings[0]
        lang_value, lang_label = vj.pick_language(oj_name, args.lang or default_language())
        print(f"[账号] {strip_tags(binding.get('accountDisplay') or '') or binding.get('accountId')}"
              f"  语言={lang_label}")
        run_id = vj.submit(oj_code, prob, code, binding["id"], lang_value,
                           open_code=1 if getattr(args, "share", False) else 0)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    print(f"[提交] vjudge run {run_id}  {VJ_BASE}/solution/{run_id}")
    username = ""
    try:
        username = vj.username(oj_code, prob)
    except RuntimeError:
        pass
    item = watch_vjudge(vj, oj_name, prob, username, run_id, wait=getattr(args, "wait", 180.0))
    if not item:
        return 1

    status_text = item.get("status") or ""
    accepted = status_text == "Accepted"
    print(f"[结果] {status_text}  时间 {item.get('runtime')} ms  内存 {item.get('memory')} KB")
    save_vj_record(find_problem_dir(pid), run_id, item, oj_code, prob)

    if not accepted:
        print("[同步] 非 AC，按设置不同步到 7FA4（省服务器）")
        return 0 if getattr(args, "no_push", False) else 1
    if getattr(args, "no_push", False):
        print("[同步] --no-push，未同步到 7FA4")
        return 0

    ok, msg = push_record(client, oj_code, prob, code, run_id, item)
    print(f"[同步] {'已交到 7FA4：' + msg if ok else msg}")
    return 0 if ok else 1


def push_record(client, oj_code, prob, code, run_id, item, score=100, language=None):
    """把一次 vjudge 通过记录交给 7FA4（插件用的 /foreign_oj 接口）。"""
    payload = {
        "code": code,
        "pid": prob,
        "rid": str(run_id),
        "oj": oj_code,
        "language": language or default_language(),
        "status": item.get("status") or "",
        "total_time": int(item.get("runtime") or 0),
        "max_memory": int(item.get("memory") or 0),
        "score": score,
    }
    try:
        r = client.request("post", "/foreign_oj", json=payload)
    except RuntimeError as exc:
        return False, f"同步失败：{exc}"
    try:
        data = r.json()
    except ValueError:
        data = None
    if isinstance(data, dict) and data.get("success"):
        return True, str(data.get("info") or "OK")
    err = (data or {}).get("err") if isinstance(data, dict) else r.text[:200]
    return False, f"7FA4 拒绝（HTTP {r.status_code}）：{err}"


def vjudge_login_session(username, password):
    """用账号密码登录 vjudge，返回 JSESSIONID；失败抛 RuntimeError。"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": VJ_BASE,
        "Referer": VJ_BASE + "/",
    })
    try:
        s.get(VJ_BASE, timeout=25)
        r = s.post(VJ_BASE + "/user/login", timeout=30,
                   data={"username": username, "password": password, "token": ""})
    except requests.RequestException as exc:
        raise RuntimeError(f"访问 vjudge 失败：{exc}") from exc

    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200 or data.get("i18nKey"):
        reason = data.get("i18nKey") or (r.text[:120] if not data else data)
        raise RuntimeError(f"vjudge 登录失败：{reason}")

    sid = s.cookies.get("JSESSIONID")
    if not sid:
        raise RuntimeError("vjudge 登录没有返回 JSESSIONID")
    try:
        chk = s.get(VJ_BASE + "/user/checkLogInStatus", timeout=25)
        valid = chk.text.strip().lower() in ("true", "1")
    except requests.RequestException:
        valid = False
    if not valid:
        raise RuntimeError("vjudge 登录后会话仍无效（可能触发了人机验证）")
    return sid


def cmd_vjlogin(args):
    user = args.user or input("vjudge 用户名: ")
    pwd = args.password if args.password is not None else getpass.getpass("vjudge 密码: ")
    print(f"[vjudge] 登录 {user} ...")
    try:
        sid = vjudge_login_session(user, pwd)
    except RuntimeError as exc:
        print(f"[失败] {exc}")
        print('[提示] 也可在浏览器登录 vjudge 后 F12 复制 JSESSIONID，'
              '再 config set vj_cookie="JSESSIONID=..."')
        return 1
    cfg = load_config()
    cfg["vj_cookie"] = f"JSESSIONID={sid}"
    cfg["vj_user"] = user
    save_config(cfg)
    print(f"[OK] 已保存 vjudge 会话（{user}），后续 pull/submit 自动使用")
    return 0


def cmd_vjcheck(args):
    cookie = getattr(args, "vj_cookie", None) or load_config().get("vj_cookie")
    if not cookie:
        print('[未配置] config set vj_cookie="JSESSIONID=..." 或 vjlogin -u 用户名')
        return 1
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Cookie": cookie.strip(),
        "X-Requested-With": "XMLHttpRequest",
    })
    try:
        r = s.get(VJ_BASE + "/user/checkLogInStatus", timeout=25)
    except requests.RequestException as exc:
        print(f"[错误] 访问 vjudge 失败：{exc}")
        return 1
    print(f"[vjudge] checkLogInStatus -> {r.text.strip()[:20]}")
    if r.text.strip().lower() in ("true", "1"):
        user = load_config().get("vj_user") or ""
        print(f"[OK] vj_cookie 有效{f'（{user}）' if user else ''}")
        return 0
    print('[失效] vj_cookie 已过期，重新 vjlogin 或重新复制 JSESSIONID')
    return 1


def cmd_push(args):
    """把已经在 vjudge 上 AC 的记录同步到 7FA4（不再重复提交）。"""
    client = make_client(args)
    client.load_session()
    try:
        pid, label = resolve_problem(client, args.id)
        meta = client.problem_meta(pid)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    if not meta.get("foreign"):
        print(f"[错误] {label} 不是外站题")
        return 1
    oj_code, prob = parse_foreign(meta["foreign"])
    if not oj_code:
        print(f"[错误] 无法解析外站题号：{meta.get('foreign')}")
        return 1
    oj_name = VJ_OJ_NAMES.get(oj_code.lower(), oj_code)

    cookie = getattr(args, "vj_cookie", None) or load_config().get("vj_cookie")
    if not cookie:
        print('[错误] 没有 vj_cookie：先 config set vj_cookie="JSESSIONID=..."')
        return 1

    source = args.file
    if not source:
        source = pick_source_file(find_problem_dir(pid))
    if not source or not os.path.exists(source):
        print("[错误] 找不到代码文件，用 -f 指定")
        return 1

    vj = VJudge(cookie)
    try:
        username = vj.username(oj_code, prob)
        item = vj.status(oj_name, prob, username, args.rid)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    if not item:
        print(f"[错误] 在 vjudge 最近的提交里没找到 run {args.rid}")
        return 1

    status_text = item.get("status") or ""
    print(f"[记录] vjudge run {args.rid}  {status_text}  "
          f"{item.get('runtime')} ms / {item.get('memory')} KB")
    if status_text != "Accepted" and not args.force:
        print("[同步] 只有 Accepted 才同步到 7FA4（--force 可强制）")
        return 1

    code = read_text_any(source)
    ok, msg = push_record(client, oj_code, prob, code, args.rid, item, language=args.lang or default_language())
    print(f"[同步] {'已交到 7FA4：' + msg if ok else msg}")
    if ok:
        save_vj_record(find_problem_dir(pid), args.rid, item, oj_code, prob)
    return 0 if ok else 1


def save_vj_record(folder, run_id, item, oj_code, prob):
    if not folder:
        return
    path = os.path.join(folder, "meta.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
    data["vj"] = {
        "run_id": run_id,
        "status": item.get("status"),
        "time_ms": item.get("runtime"),
        "memory_kb": item.get("memory"),
        "oj": oj_code,
        "prob": prob,
        "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        pass


def cmd_tasks(args):
    client = make_client(args)
    client.load_session()
    try:
        r = client.get("/vjudge/tasks")
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    rows = []
    for m in re.finditer(r"<tr[^>]*data-id=\"(\d+)\"[^>]*data-status=\"([^\"]*)\"[^>]*>([\s\S]*?)</tr>",
                         r.text):
        tid, status, body = m.group(1), m.group(2), m.group(3)
        cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", body)]
        rows.append((tid, status, cells))
    if not rows:
        print("[任务] 没有 VJudge 任务")
        return 0
    print(f"[任务] 共 {len(rows)} 条（最近在前）")
    for tid, status, cells in rows[: args.limit]:
        cells = cells[1:] if cells and cells[0] == tid else cells  # 第一列是 #
        info = "  ".join(c for c in cells if c)
        print(f"  #{tid:<5} {status:<10} {info[:120]}")
        for c in cells:
            if "重新绑定" in c or "过期" in c:
                print(f"          → {c}")
    print("查看详情：task <编号> [--problem <题号>]")
    return 0


def cmd_task(args):
    client = make_client(args)
    client.load_session()
    folder = None
    if args.problem:
        try:
            pid, _ = resolve_problem(client, args.problem)
            folder = find_problem_dir(pid)
        except RuntimeError:
            folder = None
    return watch_task(client, args.task_id, wait=args.wait, interval=args.interval, folder=folder,
                      open_captcha=not args.no_open)


def cmd_config(args):
    cfg = load_config()
    action = (args.action or "show").lower()
    print(f"[配置] {CONFIG_FILE}")

    if action == "set":
        if not args.items:
            print("用法: config set k=v [k=v ...]")
            return 1
        for item in args.items:
            if "=" not in item:
                print(f"[错误] 参数格式应为 k=v：{item}")
                return 1
            key, value = item.split("=", 1)
            cfg[key] = value
        save_config(cfg)
        print(f"[OK] 已写入 {CONFIG_FILE}")
    elif action == "get":
        if not args.items:
            print("用法: config get <键> [键 ...]")
            return 1
        for key in args.items:
            if key not in cfg:
                print(f"[缺失] {key}")
                continue
            value = cfg[key]
            if not args.raw and key in ("vj_cookie", "sftp_password", "sftp_user"):
                print(f"{key} = ***")
            elif isinstance(value, (dict, list)):
                print(f"{key} = {json.dumps(value, ensure_ascii=False)}")
            else:
                print(f"{key} = {value}")
        return 0
    elif action == "unset":
        for key in args.items:
            cfg.pop(key, None)
        save_config(cfg)
        print(f"[OK] 已移除 {', '.join(args.items) or '（无）'}")

    shown = cfg if args.raw else mask_config(cfg)
    print("-" * 60)
    print(json.dumps(shown, ensure_ascii=False, indent=2) if shown else "（空）")
    print("-" * 60)
    if not args.raw:
        print("（会话与 token 已打码，--raw 查看原文）")
    print("可用键：host（站点）、language（默认提交语言，如 cpp17）、"
          "vj_cookie / vj_user（vjudge）、template（代码模板）、sessions（各站点登录态，自动维护）、"
          "sftp_host / sftp_port / sftp_user / sftp_password / sftp_key / "
          "sftp_cwd（远程当前目录）/ sftp_local（本地 sftp 目录）、"
          "update_url / auto_update（off|check|apply）/ update_interval（秒）")
    return 0


def pick_source_file(folder):
    """挑题目目录里的代码文件：优先 pull 时生成的那个（meta.json 的 cpp），否则取最早创建的。

    同一题目录里常常有好几份代码（正解、暴力、对拍），默认应该跑当初 pull 生成的那份。
    """
    if not folder or not os.path.isdir(folder):
        return None

    meta_path = os.path.join(folder, "meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                rel = (json.load(f).get("cpp") or "").strip()
        except (OSError, ValueError):
            rel = ""
        if rel:
            for cand in (os.path.join(BASE_DIR, rel), os.path.join(folder, os.path.basename(rel))):
                if os.path.exists(cand) and cand.lower().endswith((".cpp", ".cc", ".cxx")):
                    return cand

    files = [os.path.join(folder, name) for name in os.listdir(folder)
             if name.lower().endswith((".cpp", ".cc", ".cxx"))]
    if not files:
        return None

    def born(path):
        try:
            st = os.stat(path)
        except OSError:
            return (float("inf"), float("inf"), os.path.basename(path))
        # Windows 的 st_ctime 是创建时间；Linux 上它是 inode 变更时间，近似即可
        return (st.st_ctime, st.st_mtime, os.path.basename(path))

    return sorted(files, key=born)[0]


def collect_samples(folder):
    """扫描 samples/，返回 [(显示名, 输入路径, 期望输出路径或 None)]，相同输入只保留一份。"""
    sample_dir = os.path.join(folder, "samples")
    if not os.path.isdir(sample_dir):
        return []
    files = os.listdir(sample_dir)
    cases, seen = [], set()
    for name in sorted(files):
        if not name.lower().endswith(".in"):
            continue
        in_path = os.path.join(sample_dir, name)
        try:
            with open(in_path, "rb") as f:
                digest = hashlib.md5(f.read()).hexdigest()
        except OSError:
            digest = name
        if digest in seen:
            continue
        seen.add(digest)
        stem = name[:-3]
        expected = None
        for ext in (".ans", ".exp", ".answer", ".out"):
            cand = os.path.join(sample_dir, stem + ext)
            if os.path.exists(cand):
                expected = cand
                break
        cases.append((name, in_path, expected))
    return cases


def normalize_output(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).rstrip()


EXE_SUFFIX = ".exe" if os.name == "nt" else ""


def compile_cpp(source, exe_path, std="c++17"):
    cmd = ["g++", f"-std={std}", "-O2", "-pipe", source, "-o", exe_path]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False, "未找到 g++，请先安装 MinGW（Windows）或 build-essential（Linux）"
    return p.returncode == 0, (p.stderr or "") + (p.stdout or "")


def cmd_run(args):
    client = make_client(args)
    client.load_session()

    # 1) 找代码文件与题目目录
    source = args.file
    folder = None
    if source is None and os.path.isfile(args.id) and args.id.lower().endswith((".cpp", ".cc", ".cxx")):
        source = args.id
        folder = os.path.dirname(os.path.abspath(source))
    if folder is None:
        pid = args.id
        if not pid.isdigit():
            try:
                pid, _ = resolve_problem(client, pid)
            except RuntimeError as exc:
                print(f"[错误] {exc}")
                return 1
        folder = find_problem_dir(pid)
        if not folder:
            print(f"[错误] 本地没有题目目录，先执行 pull {args.id}")
            return 1
        if not source:
            source = pick_source_file(folder)
            if source:
                print(f"[代码] 自动选择 {os.path.basename(source)}（pull 时创建的那份，可用 -f 指定其它）")
    if not source or not os.path.exists(source):
        print(f"[错误] 找不到代码文件，请用 -f 指定：{source}")
        return 1

    # 2) 样例
    cases = collect_samples(folder)
    if not cases:
        print(f"[错误] {os.path.join(folder, 'samples')} 下没有 .in 样例，先执行 pull")
        return 1

    # 3) 编译
    if args.keep:
        exe_path = os.path.join(folder, os.path.splitext(os.path.basename(source))[0] + EXE_SUFFIX)
        tmp_dir = None
    else:
        tmp_dir = tempfile.mkdtemp(prefix="7fa4_run_")
        exe_path = os.path.join(tmp_dir, "main" + EXE_SUFFIX)
    print(f"[编译] {source}  (g++ -std={args.std} -O2)")
    ok, log = compile_cpp(source, exe_path, args.std)
    if not ok:
        print("[编译失败]")
        print(log.strip()[:3000] or "(无输出)")
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return 1
    if os.name != "nt":
        try:
            os.chmod(exe_path, 0o755)
        except OSError:
            pass
    print("[编译] 通过")

    # 4) 跑样例
    io_info = problem_io(folder)
    file_io = io_info.get("mode") == "file" and bool(io_info.get("input") or io_info.get("output"))
    if file_io:
        print(f"[输入输出] 文件模式：{io_info.get('input') or '(不给输入文件)'} -> "
              f"{io_info.get('output') or '(写到 stdout)'}（每组样例会先复制到该文件）")
    passed = 0
    print(f"[样例] 共 {len(cases)} 组")
    for idx, (name, in_path, expected) in enumerate(cases, 1):
        with open(in_path, "rb") as f:
            in_data = f.read()

        workdir = None
        stdin_data = in_data
        if file_io:
            workdir = tempfile.mkdtemp(prefix="7fa4_io_")
            if io_info.get("input"):
                with open(os.path.join(workdir, io_info["input"]), "wb") as f:
                    f.write(in_data)
                stdin_data = b""
        start = time.perf_counter()
        try:
            p = subprocess.run([os.path.abspath(exe_path)], input=stdin_data, capture_output=True,
                               timeout=args.time_limit, cwd=workdir)
            elapsed = time.perf_counter() - start
            stdout_bytes = p.stdout
            if workdir and io_info.get("output"):
                produced = os.path.join(workdir, io_info["output"])
                if os.path.exists(produced):
                    with open(produced, "rb") as f:
                        stdout_bytes = f.read()
            out = stdout_bytes.decode("utf-8", "replace")
            err = p.stderr.decode("utf-8", "replace")
            rc = p.returncode
        except subprocess.TimeoutExpired:
            if workdir:
                shutil.rmtree(workdir, ignore_errors=True)
            print(f"  [{idx}/{len(cases)}] {name}  TLE  >{args.time_limit:g}s")
            continue
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)

        # 用户输出 / 错误落到样例同目录：<名>.out、<名>.err
        sample_dir = os.path.dirname(in_path)
        stem = os.path.splitext(name)[0]
        out_file = os.path.join(sample_dir, stem + ".out")
        if expected and os.path.abspath(out_file) == os.path.abspath(expected):
            out_file = os.path.join(sample_dir, stem + ".user.out")
        err_file = os.path.join(sample_dir, stem + ".err")
        try:
            with open(out_file, "wb") as f:
                f.write(stdout_bytes)
            with open(err_file, "wb") as f:
                f.write(p.stderr)
        except OSError as exc:
            print(f"      [警告] 写入输出失败：{exc}")

        if rc != 0:
            print(f"  [{idx}/{len(cases)}] {name}  RE  退出码 {rc}  {elapsed:.3f}s")
            if err.strip():
                print("      stderr: " + err.strip().splitlines()[0][:200])
            continue

        if expected is None:
            print(f"  [{idx}/{len(cases)}] {name}  运行完成  {elapsed:.3f}s（无期望输出）")
            print("      输出: " + (out.strip().splitlines()[0][:120] if out.strip() else "(空)"))
            continue

        with open(expected, encoding="utf-8", errors="replace") as f:
            want = f.read()
        if normalize_output(out) == normalize_output(want):
            passed += 1
            print(f"  [{idx}/{len(cases)}] {name}  AC  {elapsed:.3f}s")
        else:
            print(f"  [{idx}/{len(cases)}] {name}  WA  {elapsed:.3f}s")
            want_lines = normalize_output(want).split("\n")
            got_lines = normalize_output(out).split("\n")
            for i in range(max(len(want_lines), len(got_lines))):
                w = want_lines[i] if i < len(want_lines) else "<无>"
                g = got_lines[i] if i < len(got_lines) else "<无>"
                if w != g:
                    print(f"      第 {i + 1} 行  期望: {w[:120]}")
                    print(f"      第 {i + 1} 行  实际: {g[:120]}")
                    break
            if err.strip():
                print("      stderr: " + err.strip().splitlines()[0][:200])

    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"[输出] 每组用户输出/错误写到样例同目录：<名>.out（无期望输出时）/ <名>.user.out / <名>.err")
    print(f"[结果] 通过 {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


STRESS_HINTS = {
    "brute": ("brute", "baoli", "bf", "暴力", "wrong", "naive"),
    "gen": ("gen", "maker", "make", "rand", "data"),
}


def find_stress_file(folder, explicit, kind, exclude=()):
    """找对拍用的文件：显式指定优先，否则按关键字猜（brute/baoli/bf、gen/maker…）。"""
    if explicit:
        for path in (explicit, os.path.join(folder, explicit)):
            if os.path.exists(path):
                return os.path.abspath(path)
        return None
    files = [n for n in sorted(os.listdir(folder))
             if n.lower().endswith((".cpp", ".cc", ".cxx")) and n not in exclude]
    for hint in STRESS_HINTS[kind]:
        for name in files:
            if hint in name.lower():
                return os.path.join(folder, name)
    return None


def run_cpp(exe, in_data, timeout, argv=None, cwd=None):
    """跑一次程序，返回 (stdout, stderr, 耗时, 错误类型或 None)。"""
    start = time.perf_counter()
    try:
        p = subprocess.run([exe] + list(argv or []), input=in_data,
                           capture_output=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        return b"", b"", time.perf_counter() - start, "TLE"
    except OSError as exc:
        return b"", str(exc).encode(), time.perf_counter() - start, "RE"
    return p.stdout, p.stderr, time.perf_counter() - start, (None if p.returncode == 0 else f"RE {p.returncode}")


def run_with_io(exe, in_data, timeout, io=None, argv=None, produce_input=False):
    """跑程序并处理文件 IO：输入写进 .in 文件、输出从 .out 文件读回。

    produce_input=True 用于数据生成器：不给它输入，改从它写出的输入文件里取结果。
    """
    if not io or io.get("mode") != "file":
        return run_cpp(exe, in_data, timeout, argv)
    workdir = tempfile.mkdtemp(prefix="7fa4_io_")
    try:
        if not produce_input and io.get("input"):
            with open(os.path.join(workdir, io["input"]), "wb") as f:
                f.write(in_data)
        stdin_data = b"" if io.get("input") else in_data
        stdout, stderr, elapsed, etype = run_cpp(exe, stdin_data, timeout, argv, cwd=workdir)
        target = io.get("input") if produce_input else io.get("output")
        if target:
            produced = os.path.join(workdir, target)
            if os.path.exists(produced):
                with open(produced, "rb") as f:
                    stdout = f.read()
        return stdout, stderr, elapsed, etype
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def first_diff_line(text_a, text_b):
    """返回第一处不同的行号与内容，用于快速定位。"""
    a = normalize_output(text_a).split("\n")
    b = normalize_output(text_b).split("\n")
    for i in range(max(len(a), len(b))):
        left = a[i] if i < len(a) else "<无>"
        right = b[i] if i < len(b) else "<无>"
        if left != right:
            return i + 1, left, right
    return 0, "", ""


def cmd_stress(args):
    """对拍：生成随机数据，跑正解与暴力，输出不一致就停下来保存用例。"""
    client = make_client(args)
    client.load_session()

    folder = None
    if args.id:
        if os.path.isdir(args.id):
            folder = os.path.abspath(args.id)
        else:
            pid = args.id
            if not pid.isdigit():
                try:
                    pid, _ = resolve_problem(client, pid)
                except RuntimeError as exc:
                    print(f"[错误] {exc}")
                    return 1
            folder = find_problem_dir(pid)
            if not folder:
                print(f"[错误] 本地没有题目目录，先执行 pull {args.id}")
                return 1
    else:
        print("[错误] 需要题目（或直接给目录）：stress Q6.4.6.1 -g gen.cpp -b brute.cpp")
        return 1

    solution = None
    if args.solution:
        for path in (args.solution, os.path.join(folder, args.solution)):
            if os.path.exists(path):
                solution = os.path.abspath(path)
                break
    else:
        solution = pick_source_file(folder)
    if not solution or not os.path.exists(solution):
        print("[错误] 找不到正解代码，用 -s 指定（相对路径按题目目录解析）")
        return 1
    brute = find_stress_file(folder, args.brute, "brute", exclude=(os.path.basename(solution),))
    if not brute:
        print("[错误] 找不到暴力代码，用 -b 指定（文件名带 brute/baoli/bf 可自动识别）")
        return 1
    gen = find_stress_file(folder, args.gen, "gen")
    if not gen:
        print("[错误] 找不到数据生成器，用 -g 指定（文件名带 gen/maker/rand 可自动识别）")
        print('      生成器写法：读 argv[1] 当随机种子，把数据输出到 stdout，例如')
        print('        int main(int argc, char** argv) { srand(atoi(argv[1])); ... cout << n << "\\n"; }')
        return 1

    tmp_dir = tempfile.mkdtemp(prefix="7fa4_stress_")
    exes = {}
    for key, source in (("sol", solution), ("brute", brute), ("gen", gen)):
        exe = os.path.join(tmp_dir, key + EXE_SUFFIX)
        ok, log = compile_cpp(source, exe, args.std)
        if not ok:
            print(f"[编译失败] {os.path.basename(source)}")
            print(log.strip()[:2000] or "(无输出)")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return 1
        if os.name != "nt":
            try:
                os.chmod(exe, 0o755)
            except OSError:
                pass
        exes[key] = exe

    io_info = problem_io(folder)
    print(f"[对拍] 正解={os.path.basename(solution)}  暴力={os.path.basename(brute)}  "
          f"生成器={os.path.basename(gen)}")
    if io_info.get("mode") == "file":
        print(f"[对拍] 文件 IO：{io_info.get('input')} -> {io_info.get('output')}")
    print(f"[对拍] {args.times} 轮，单次限时 {args.tl:g}s")

    fail_dir = args.dir or os.path.join(folder, "stress")
    started = time.time()
    max_sol = 0.0

    for i in range(1, args.times + 1):
        # 生成器把轮次当随机种子传进 argv[1]；文件 IO 的题从它写出的输入文件取数据
        out, err, _, etype = run_with_io(exes["gen"], b"", args.tl, io_info, argv=[str(i)],
                                         produce_input=True)
        if etype:
            print(f"[错误] 生成器第 {i} 轮失败：{etype}")
            print(normalize_output(err.decode("utf-8", "replace"))[:500])
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return 1

        got, gerr, elapsed, etype = run_with_io(exes["sol"], out, args.tl, io_info)
        max_sol = max(max_sol, elapsed)
        if etype:
            print(f"  [{i}] 正解 {etype}（{elapsed:.3f}s），保存用例")
            _save_stress_case(fail_dir, i, out, got, b"", f"正解 {etype}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return 1

        want, _, _, betype = run_with_io(exes["brute"], out, args.tl, io_info)
        if betype:
            print(f"  [{i}] 暴力 {betype}，跳过（可能是暴力太慢或数据超范围）")
            continue

        if normalize_output(got.decode("utf-8", "replace")) != normalize_output(want.decode("utf-8", "replace")):
            line_no, left, right = first_diff_line(want.decode("utf-8", "replace"),
                                                   got.decode("utf-8", "replace"))
            print(f"  [{i}] 发现差异（第 {line_no} 行）")
            print(f"      暴力: {left[:200]}")
            print(f"      正解: {right[:200]}")
            path = _save_stress_case(fail_dir, i, out, got, want, f"第 {line_no} 行不同")
            print(f"[保存] 用例 -> {path}")
            print("[失败] 正解与暴力输出不一致，可先用 run 复现")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return 1

        if i % 50 == 0 or i == args.times:
            print(f"  [{i}/{args.times}] 一致  正解耗时最大 {max_sol:.3f}s")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"[通过] {args.times} 轮全部一致，用时 {time.time() - started:.1f}s")
    return 0


def _save_stress_case(fail_dir, index, in_data, sol_out, brute_out, note):
    """把出错的那组数据落盘：1.in / sol.out / brute.out / note.txt"""
    case_dir = os.path.join(fail_dir, f"fail{index}")
    os.makedirs(case_dir, exist_ok=True)
    with open(os.path.join(case_dir, "1.in"), "wb") as f:
        f.write(in_data)
    with open(os.path.join(case_dir, "sol.out"), "wb") as f:
        f.write(sol_out)
    if brute_out:
        with open(os.path.join(case_dir, "brute.out"), "wb") as f:
            f.write(brute_out)
    write_text(os.path.join(case_dir, "note.txt"), note + "\n")
    return case_dir


def guess_image_type(path):
    ext = os.path.splitext(path)[1].lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
            ".webp": "image/webp", ".bmp": "image/bmp"}.get(ext, "image/png")


def save_paper_meta(folder, sid, path):
    """记录备份位置；原始备份只保留第一次的那份，避免后续 get 把还原源覆盖掉。"""
    meta_path = os.path.join(folder, "meta.json")
    data = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
    paper = data.get("paper") or {}
    rel = os.path.relpath(path, folder)
    current = paper.get("file")
    if not current or not os.path.exists(os.path.join(folder, current)):
        paper["file"] = rel
        paper["sid"] = sid
        paper["saved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    paper["last_seen_sid"] = sid
    data["paper"] = paper
    try:
        write_text(meta_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        pass


def find_paper_backup(folder):
    meta_path = os.path.join(folder, "meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                rel = ((json.load(f).get("paper") or {}).get("file"))
            if rel:
                path = os.path.join(folder, rel)
                if os.path.exists(path):
                    return path
        except (OSError, ValueError):
            pass
    answer_dir = os.path.join(folder, "answer")
    if os.path.isdir(answer_dir):
        files = [os.path.join(answer_dir, n) for n in sorted(os.listdir(answer_dir))
                 if n.lower().startswith("original-")]
        if files:
            return files[-1]
    return None


def report_paper_response(client, r, label):
    if 300 <= r.status_code < 400:
        print(f"[OK] 已提交 {label} -> {r.headers.get('Location')}")
        return 0
    if r.status_code == 200 and "错误 - 7FA4" in r.text:
        msg = strip_tags(r.text.split("ui main container")[-1])[:200]
        print(f"[失败] 7FA4 拒绝：{msg or '参数不合法或权限不足'}")
        return 1
    print(f"[结果] HTTP {r.status_code} {r.headers.get('Content-Type')}")
    print(strip_tags(r.text)[:300])
    return 1


def cmd_paper(args):
    """纸面题：get 备份当前答案图 / submit 上传测试图 / restore 还原。"""
    client = make_client(args)
    client.load_session()
    try:
        pid, label = resolve_problem(client, args.id)
        meta = client.problem_meta(pid)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    qtype = meta.get("type") or ""
    if "纸面" not in qtype:
        print(f"[警告] {label} 的题目类型是「{qtype or '未知'}」，不像是纸面题（仍继续）")

    short = sanitize_name(meta.get("short"), str(pid))
    if short.isdigit():
        short = str(pid)
    folder = find_problem_dir(pid) or problem_dir(pid, short)
    os.makedirs(folder, exist_ok=True)
    answer_dir = os.path.join(folder, "answer")

    if args.action == "get":
        try:
            info = client.paper_current_answer(pid)
        except RuntimeError as exc:
            print(f"[错误] {exc}")
            return 1
        if not info:
            print("[提示] 这题还没有已提交的答案图片")
            return 1
        ext = ".jpg" if "jpeg" in info["content_type"] or "jpg" in info["content_type"] else ".png"
        os.makedirs(answer_dir, exist_ok=True)
        path = os.path.join(answer_dir, f"original-{info['sid']}{ext}")
        with open(path, "wb") as f:
            f.write(info["content"])
        save_paper_meta(folder, info["sid"], path)
        print(f"[备份] 当前答案（提交 #{info['sid']}，{len(info['content'])} 字节）")
        print(f"[备份] -> {path}")
        return 0

    if args.action == "submit":
        source = args.file
        if not source or not os.path.exists(source):
            print(f"[错误] 找不到图片：{source}")
            return 1
        with open(source, "rb") as f:
            data = f.read()
        if not data:
            print(f"[错误] 图片是空的：{source}")
            return 1
        try:
            r = client.paper_submit(pid, os.path.basename(source), data, guess_image_type(source))
        except RuntimeError as exc:
            print(f"[错误] {exc}")
            return 1
        print(f"[提交] {label}  图片={os.path.basename(source)}  {len(data)} 字节")
        return report_paper_response(client, r, label)

    if args.action == "restore":
        path = find_paper_backup(folder)
        if not path:
            print(f"[错误] 没有备份，先执行 paper get {args.id}")
            return 1
        with open(path, "rb") as f:
            data = f.read()
        try:
            r = client.paper_submit(pid, os.path.basename(path), data, guess_image_type(path))
        except RuntimeError as exc:
            print(f"[错误] {exc}")
            return 1
        print(f"[还原] {label}  <- {path}（{len(data)} 字节）")
        return report_paper_response(client, r, label)

    print(f"[错误] 未知操作：{args.action}")
    return 1


# ---------------------------------------------------------------- 计划 / 复盘 / 提交详情
def parse_home_plan(html):
    """从首页解析「今日计划」：自由文本 + 表格（题号/题目/评价/期限）。"""
    text = ""
    m = re.search(r'<div class="user_plan_item">([\s\S]*?)</div>', html)
    if m:
        text = strip_tags(m.group(1))
    rows = []
    tbody = html.split('id="announces"', 1)
    if len(tbody) > 1:
        for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", tbody[1].split("</tbody>")[0]):
            pid = re.search(r"/problem/(\d+)", tr)
            if not pid:
                continue
            cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr)]
            rows.append({"id": pid.group(1), "cells": cells})
    return text, rows


PLAN_DATE_WORDS = {
    "today": 0, "今天": 0, "今晚": 0,
    "tomorrow": 1, "明天": 1, "明早": 1,
    "后天": 2, "大后天": 3,
    "yesterday": -1, "昨天": -1,
}


def parse_plan_date(text, base=None):
    """today / 明天 / 后天 / 2026-10-28 / 10-28 / +3 都能解析成 date。"""
    base = base or datetime.date.today()
    raw = (text or "").strip().lower()
    if not raw:
        return base
    if raw in PLAN_DATE_WORDS:
        return base + datetime.timedelta(days=PLAN_DATE_WORDS[raw])
    m = re.fullmatch(r"([+-]?\d+)", raw)
    if m:
        return base + datetime.timedelta(days=int(m.group(1)))
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", raw)
    if m:
        return datetime.date(base.year, int(m.group(1)), int(m.group(2)))
    raise RuntimeError(f"看不懂的日期：{text}（可用 today/tomorrow/后天/2026-10-28/+3）")


def plan_timestamp(day):
    return int(datetime.datetime.combine(day, datetime.time()).timestamp())


def current_user_id(client):
    """从首页导航里的 /user_plans/<uid> 拿用户 id，顺带缓存到 config。"""
    cfg = load_config()
    if cfg.get("user_id"):
        return int(cfg["user_id"])
    html = client.get("/").text
    m = re.search(r"/user_plans/(\d+)", html)
    if not m:
        raise RuntimeError("没能从首页取到用户 ID（请确认已登录）")
    cfg["user_id"] = int(m.group(1))
    try:
        save_config(cfg)
    except OSError:
        pass
    return int(m.group(1))


def fetch_user_plan(client, user_id, day, ptype="day"):
    """GET /user_plan?format=json -> (user_plan 字典, 时间戳)"""
    ts = plan_timestamp(day)
    r = client.get("/user_plan", params={"format": "json", "user_id": user_id,
                                         "date": ts, "type": ptype})
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"计划接口返回异常（HTTP {r.status_code}）：{r.text[:120]}")
    if not data.get("success"):
        raise RuntimeError(f"读取计划失败：{data.get('err') or data}")
    return (data.get("user_plan") or {}), ts


def page_body_text(html):
    """去掉导航/弹窗这些公共部分，只留正文文本。"""
    text = strip_tags(re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html))
    marker = "跳转到页面"
    if marker in text:
        text = text.split(marker)[-1]
    return text.strip()


# ---------------------------------------------------------------- 好友 / 聊天
def chat_info(client):
    """GET /chat/info -> {user, limit, groups, friends}"""
    r = client.get("/chat/info")
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"聊天接口返回异常（HTTP {r.status_code}）")
    if not data.get("success"):
        err = data.get("err") or {}
        raise RuntimeError(str(err.get("message") if isinstance(err, dict) else err) or "读取联系人失败")
    return data


def friend_relation(item):
    watcher, watchee = item.get("watcher"), item.get("watchee")
    if watcher and watchee:
        return "双向"
    if watcher:
        return "我关注"
    if watchee:
        return "关注我"
    return ""


def friend_label(item):
    name = item.get("nickname") or item.get("username") or str(item.get("id"))
    real = item.get("real_name") or ""
    return f"{name}（{real}）" if real and real != name else name


def cmd_friends(args):
    """好友/关注列表：默认只看有关系的，--all 看全部。"""
    client = make_client(args)
    client.load_session()
    try:
        data = chat_info(client)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    friends = data.get("friends") or []
    groups = data.get("groups") or []
    keyword = (args.search or "").strip().lower()

    pool = friends if args.all else [f for f in friends if friend_relation(f)]
    if keyword:
        pool = [f for f in pool
                if keyword in " ".join(str(f.get(k) or "") for k in
                                       ("username", "nickname", "real_name", "grade")).lower()]
    if not args.groups:
        counts = {}
        for item in friends:
            key = friend_relation(item)
            counts[key] = counts.get(key, 0) + 1
        order = {"双向": 0, "我关注": 1, "关注我": 2, "": 3}
        pool.sort(key=lambda f: (order.get(friend_relation(f), 3),
                                 str(f.get("nickname") or f.get("username") or "")))
        print(f"[好友] 双向 {counts.get('双向', 0)}  关注我 {counts.get('关注我', 0)}  "
              f"我关注 {counts.get('我关注', 0)}  显示 {min(len(pool), args.limit)} 条")
        for item in pool[: args.limit]:
            print(f"  {pad(str(item.get('id')), 6)} {pad(friend_label(item), 24)} "
                  f"{pad(item.get('grade') or '', 6)} {friend_relation(item)}")
    if groups and (args.groups or not args.groups):
        if not args.groups:
            print()
        print(f"[群] {len(groups)} 个")
        for group in groups:
            members = len(group.get("users") or [])
            print(f"  {pad(str(group.get('id')), 6)} {pad(group.get('title') or '', 24)} "
                  f"{members} 人")
    if pool and not args.groups and len(pool) > args.limit:
        print(f"[提示] 还有 {len(pool) - args.limit} 条，用 -n 调大或 --search 过滤")
    return 0


def resolve_chat_target(data, token, self_id=None):
    """把 昵称/账号/群名/ID 解析成 (type, id, 显示名)。"""
    token = (token or "").strip()
    friends = data.get("friends") or []
    groups = data.get("groups") or []

    if token in ("自己", "me", "self") and self_id:
        return "user", self_id, "我自己"
    if token.isdigit():
        for item in friends:
            if str(item.get("id")) == token:
                return "user", item["id"], friend_label(item)
        for group in groups:
            if str(group.get("id")) == token:
                return "group", group["id"], group.get("title") or token
        if self_id and str(self_id) == token:
            return "user", self_id, "我自己"
        raise RuntimeError(f"没有 id 为 {token} 的联系人或群")

    low = token.lower()

    def hit(items, keys):
        return [i for i in items
                if any(low in str(i.get(k) or "").lower() for k in keys)]

    found = hit(friends, ("username", "nickname", "real_name"))
    if len(found) == 1:
        item = found[0]
        return "user", item["id"], friend_label(item)
    if len(found) > 1:
        print(f"[错误] 「{token}」匹配到 {len(found)} 个人，用 id 或更精确的昵称：")
        for item in found[:10]:
            print(f"  {item.get('id')}  {friend_label(item)}  @{item.get('username')}")
        raise RuntimeError("目标不唯一")

    found = hit(groups, ("title",))
    if len(found) == 1:
        return "group", found[0]["id"], found[0].get("title") or token
    if len(found) > 1:
        print(f"[错误] 「{token}」匹配到 {len(found)} 个群：")
        for group in found[:10]:
            print(f"  {group.get('id')}  {group.get('title')}")
        raise RuntimeError("目标不唯一")
    raise RuntimeError(f"找不到联系人/群：{token}")


def parse_chat_content(raw):
    """content 是 JSON 字符串：{type: text/image/pat/...}"""
    try:
        payload = json.loads(raw or "")
    except ValueError:
        return "text", str(raw or "")
    if not isinstance(payload, dict):
        return "text", str(payload)
    kind = payload.get("type") or "text"
    if kind == "text":
        return kind, payload.get("content") or ""
    if kind == "image":
        return kind, "[图片]"
    if kind == "pat":
        target = payload.get("target")
        return kind, f"[拍一拍 {target}]" if target else "[拍一拍]"
    return kind, f"[{kind}]"


def cmd_chat(args):
    """聊天：列表 / 看消息 / 发消息 / 发求助 / 同意求助。"""
    client = make_client(args)
    client.load_session()
    try:
        data = chat_info(client)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    if not args.target:
        friends = data.get("friends") or []
        groups = data.get("groups") or []
        limit = data.get("limit") or {}
        counts = {}
        for item in friends:
            key = friend_relation(item)
            counts[key] = counts.get(key, 0) + 1
        print(f"[聊天] 好友 {len(friends)}（双向 {counts.get('双向', 0)} / "
              f"关注我 {counts.get('关注我', 0)} / 我关注 {counts.get('我关注', 0)}）  "
              f"群 {len(groups)}")
        if limit:
            print(f"[限制] 每 {limit.get('time_limit')} 秒最多 {limit.get('count_limit')} 条，"
                  f"单条上限 {limit.get('length_limit')} 字符")
        print("看消息：chat <昵称/群名> [-n 20]")
        print("发消息：chat <昵称> -m \"内容\"")
        print("发求助：chat <昵称> --ask \"哪道题/什么问题\"")
        print("同意求助：chat <昵称> --accept [-m \"说明\"]")
        return 0

    uid = (data.get("user") or {}).get("id")
    try:
        ttype, tid, name = resolve_chat_target(data, args.target, uid)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    names = {item.get("id"): friend_label(item) for item in (data.get("friends") or [])}

    if args.message is not None or args.ask is not None or args.accept:
        if args.ask is not None:
            content = f"【求助】{args.ask.strip()}"
        elif args.accept:
            content = "【同意求助】" + (f"\n{args.message.strip()}" if args.message else "")
        else:
            content = args.message or ""
        if not content.strip():
            print("[错误] 内容为空")
            return 1
        print(f"[发送] {name}（{ttype}#{tid}）")
        print(f"       {content}")
        if args.dry_run:
            print("[预演] 未发送")
            return 0
        try:
            r = client.request("post", "/chat/chat",
                               data={"type": ttype, "target_id": tid, "content": content})
            ret = r.json()
        except (RuntimeError, ValueError) as exc:
            print(f"[错误] 发送失败：{exc}")
            return 1
        if not ret.get("success"):
            err = ret.get("err") or {}
            print(f"[失败] {err.get('message') if isinstance(err, dict) else err}")
            return 1
        print("[OK] 已发送")
        return 0

    try:
        r = client.get("/chat/chat", params={"type": ttype, "target_id": tid, "take": args.limit})
        ret = r.json()
    except (RuntimeError, ValueError) as exc:
        print(f"[错误] 拉取消息失败：{exc}")
        return 1
    if not ret.get("success"):
        err = ret.get("err") or {}
        print(f"[失败] {err.get('message') if isinstance(err, dict) else err}")
        return 1

    chats = ret.get("chats") or []
    print(f"[聊天] {name}（{ttype}#{tid}）最近 {len(chats)} 条")
    for msg in chats:
        kind, body = parse_chat_content(msg.get("content"))
        when = datetime.datetime.fromtimestamp(msg.get("send_time") or 0).strftime("%m-%d %H:%M")
        sender = "我" if msg.get("sender_id") == uid else names.get(msg.get("sender_id"), f"#{msg.get('sender_id')}")
        body = body.replace("\n", " ⏎ ")
        print(f"  {when}  {pad(sender, 14)} {body[:160]}")
    if not chats:
        print("  （还没有消息）")
    return 0


def cmd_contest(args):
    """模测：不给参数列最近几场，给编号/名称看详情与我的成绩。"""
    client = make_client(args)
    client.load_session()

    html = client.get("/contests").text
    rows = []
    for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html):
        m = re.search(r'href="/contest/(\d+)"[^>]*>([\s\S]*?)</a>', tr)
        if not m:
            continue
        cid = m.group(1)
        name = re.sub(r"\s*(已结束|未开始|进行中)\s*$", "", strip_tags(m.group(2))).strip()
        cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr)]
        head = cells[0] if cells else ""
        status = ("已结束" if "已结束" in head else "未开始" if "未开始" in head
                  else "进行中" if "进行中" in head else "")
        rows.append({"id": cid, "name": name, "status": status,
                     "start": cells[1] if len(cells) > 1 else "",
                     "duration": cells[2] if len(cells) > 2 else ""})

    if not args.id:
        show = rows[: args.limit]
        print(f"[模测] 共 {len(rows)} 场（显示最近 {len(show)} 场）")
        for row in show:
            print(f"  {pad(row['id'], 7)} {pad(row['name'], 24)} {pad(row['status'], 6)} "
                  f"{pad(row['start'], 20)} {row['duration']}")
        print("[提示] 详情：contest <编号或名称>")
        return 0

    token = str(args.id).strip()
    target = None
    if token.isdigit():
        target = next((r for r in rows if r["id"] == token), None)
    else:
        hit = [r for r in rows if token.lower() in r["name"].lower()]
        if len(hit) > 1:
            print(f"[错误] 匹配到 {len(hit)} 场，用编号更准：")
            for r in hit[:10]:
                print(f"  {r['id']}  {r['name']}  {r['status']}")
            return 1
        target = hit[0] if hit else None
    if not target:
        print(f"[错误] 没有匹配的模测：{token}")
        return 1

    cid = target["id"]
    detail = client.get(f"/contest/{cid}").text
    problems = []
    seen = set()
    for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", detail):
        m = re.search(r'href="/contest/%s/problem/(\d+)"[^>]*>([\s\S]*?)</a>' % cid, tr)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        problems.append((m.group(1), strip_tags(m.group(2))))
    problems.sort(key=lambda x: int(x[0]) if x[0].isdigit() else 0)

    print(f"[模测] {target['name']}  {target['status']}  {target['start']}  {target['duration']}")
    print(f"[链接] {client.base}/contest/{cid}")
    if problems:
        print(f"[题目] {len(problems)} 道")
        for no, label in problems:
            print(f"  {pad(label, 28)} {client.base}/contest/{cid}/problem/{no}")

    try:
        me = client.get(f"/contest/{cid}/ranklist").text
    except RuntimeError:
        me = ""
    uid = load_config().get("user_id")
    mine = None
    if me and uid:
        for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", me):
            if f"/user/{uid}" not in tr:
                continue
            tds = re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr)
            if len(tds) < 4:
                continue

            def score_of(cell):
                m = re.search(r'class="score[^"]*"[^>]*>\s*([\d.]+)', cell)
                return m.group(1) if m else "-"

            mine = {"rank": re.sub(r"[^\d]", "", strip_tags(tds[0])) or "-",
                    "per": [score_of(td) for td in tds[3:-1]],
                    "total": score_of(tds[-1])}
            break
    if mine:
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        detail_scores = " ".join(
            f"{letters[i] if i < len(letters) else i + 1}{score}"
            for i, score in enumerate(mine["per"]))
        print(f"[我的] 排名 {mine['rank']}  总分 {mine['total']}  各题 {detail_scores}")
    else:
        print("[我的] 排行榜里没有你的成绩（可能没参加）")
    print(f"[排行] {client.base}/contest/{cid}/ranklist")
    return 0


def cmd_progress(args):
    """进度排行：/ranklist?default=1 的表格。"""
    client = make_client(args)
    client.load_session()
    html = client.get("/ranklist", params={"default": 1}).text
    rows = []
    for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html):
        cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr)]
        if len(cells) >= 6 and cells[0].isdigit():
            rows.append(cells)
    if not rows:
        print("[错误] 没能解析进度表")
        return 1

    submitter = ""
    try:
        submitter = current_submitter(client)
    except RuntimeError:
        pass
    if args.me:
        rows = [r for r in rows if submitter and submitter in r]
        if not rows:
            print("[进度] 这张表里没有你的记录")
            return 1

    show = rows[: args.limit] if not args.me else rows
    print(f"[进度] 共 {len(rows)} 人（显示 {len(show)} 人）")
    for cells in show:
        mark = " *" if submitter and submitter in cells else ""
        print(f"  {pad(cells[0], 5)} {pad(cells[2], 16)} {pad(cells[5] if len(cells) > 5 else '', 6)} "
              f"通过 {pad(cells[6] if len(cells) > 6 else '-', 6)} "
              f"积分 {pad(cells[7] if len(cells) > 7 else '-', 6)}{mark}")
    return 0


def cmd_article(args):
    """读帖子/帮助：article <编号或 URL>。"""
    client = make_client(args)
    client.load_session()
    token = str(args.id).strip()
    m = re.search(r"/article/(\d+)", token)
    aid = m.group(1) if m else (token if token.isdigit() else None)
    if not aid:
        print(f"[错误] 需要文章编号：article 124")
        return 1
    html = client.get(f"/article/{aid}").text
    if "错误 - 7FA4" in html:
        print(f"[错误] 文章 {aid} 不存在或无权查看")
        return 1
    body = page_body_text(html)
    for tail in ("蜀ICP备", "Powered by"):
        if tail in body:
            body = body.split(tail)[0]
    print(f"[文章] #{aid}  {client.base}/article/{aid}")
    print("-" * 60)
    print(body.strip()[:6000])
    print("-" * 60)
    return 0


def cmd_prints(args):
    """提交打印队列：/prints/html。"""
    client = make_client(args)
    client.load_session()
    html = client.get("/prints/html").text
    rows = []
    for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html):
        cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr)]
        if len(cells) >= 6 and cells[0] and cells[0] not in ("姓名", "提交"):
            rows.append(cells)
    if not rows:
        print("[打印] 队列是空的")
        return 0
    print(f"[打印] 共 {len(rows)} 条（显示最近 {min(len(rows), args.limit)} 条）")
    print(f"  {pad('姓名', 8)} {pad('后缀', 6)} {pad('提交时间', 20)} "
          f"{pad('审核时间', 20)} {pad('打印时间', 20)} 结果")
    for cells in rows[: args.limit]:
        name, suffix, sent, checked, printed, status = cells[:6]
        print(f"  {pad(name, 8)} {pad(suffix, 6)} {pad(sent, 20)} "
              f"{pad(checked, 20)} {pad(printed, 20)} {status}")
    return 0


def problem_titles(client, pids):
    """批量取题目名：抓题目页 <title>（比 problem_meta 轻），结果缓存进 config。"""
    cfg = load_config()
    cache = cfg.get("problem_titles")
    cache = cache if isinstance(cache, dict) else {}
    out, changed = {}, False
    for pid in pids:
        pid = str(pid)
        cached = cache.get(pid) or ""
        if re.match(r"^[A-Za-z]*\d[\d.]*\.?\s", cached):    # 带题号的才认
            out[pid] = cached
            continue

        name = ""
        try:
            data = client.get(f"/api/v2/search/problems/{pid}").json()
            for item in data.get("results") or []:
                if str(item.get("value")) == pid:
                    name = (item.get("name") or "").strip()
                    break
        except (RuntimeError, ValueError):
            name = ""
        if not name:
            try:
                html = client.get(f"/problem/{pid}").text
            except RuntimeError:
                continue
            m = re.search(r"<title>(.*?)</title>", html, re.S)
            if m:
                name = re.sub(r"\s*-\s*题目\s*-\s*7FA4\s*$", "", m.group(1).strip())
        if name and "错误" not in name:
            out[pid] = name
            cache[pid] = name
            changed = True
    if changed:
        cfg["problem_titles"] = cache
        try:
            save_config(cfg)
        except OSError:
            pass
    return out


def cmd_plan(args):
    """计划：home 看首页概览，show 看某天计划（默认今天），add 新建/修改某天计划。"""
    client = make_client(args)
    client.load_session()
    action = (args.action or "show").lower()
    ptype = (args.type or "day").lower()

    if action == "home":
        try:
            html = client.get("/").text
        except RuntimeError as exc:
            print(f"[错误] {exc}")
            return 1
        text, rows = parse_home_plan(html)
        print("[计划] 今日计划")
        if text:
            for line in text.splitlines() or [text]:
                if line.strip():
                    print(f"  {line.strip()}")
        else:
            print("  （还没有填写计划）")
        if rows:
            print(f"\n[计划] 作业 {len(rows)} 项")
            for row in rows:
                no = row["cells"][0] if row["cells"] else row["id"]
                title = row["cells"][1] if len(row["cells"]) > 1 else ""
                deadline = row["cells"][3] if len(row["cells"]) > 3 else ""
                print(f"  {no:<12} {title:<18} 截止 {deadline}  ({row['id']})")
        return 0

    try:
        day = parse_plan_date(args.date)
        user_id = args.user or current_user_id(client)
        existing, ts = fetch_user_plan(client, user_id, day, ptype)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    weekday = "一二三四五六日"[day.weekday()]
    if action == "show":
        print(f"[计划] {day.isoformat()} 周{weekday}  {ptype}  用户 {user_id}")
        if not existing:
            print("  （这一天还没有计划）")
            return 0
        print(f"[编号] {existing.get('id')}")
        plan = (existing.get("plan") or "").strip()
        print("[描述] " + (plan.replace("\r\n", "\n").replace("\n", " / ") if plan else "（空）"))
        pids = (existing.get("problem_ids") or "").split("|")
        pids = [p for p in pids if p]
        if pids:
            print(f"[题目] {len(pids)} 道")
            titles = {} if args.no_titles else problem_titles(client, pids)
            rows = []
            for pid in pids:
                name = titles.get(pid) or ""
                no, title = split_problem_name(name) if name else ("", "")
                rows.append((pid, no, title or name))
            width = max((len(no) for _, no, _ in rows), default=0)
            for pid, no, title in rows:
                if no:
                    print(f"  {pad(pid, 8)} {pad(no, width)}  {title}".rstrip())
                else:
                    print(f"  {pad(pid, 8)} {title}".rstrip())
        else:
            print("[题目] （无）")
        for key, label in (("teacher_plan", "教师"), ("result", "完成"), ("tweak", "调整")):
            value = (existing.get(key) or "").strip()
            if value:
                print(f"[{label}] {value.replace(chr(10), ' / ')}")
        if existing.get("comment"):
            print(f"[评语] {existing['comment']}")
        return 0

    if action in ("add", "edit"):
        plan_text = args.message
        if plan_text is None and args.file:
            if not os.path.exists(args.file):
                print(f"[错误] 文件不存在：{args.file}")
                return 1
            plan_text = read_text_any(args.file)
        if plan_text is None:
            print('用法: plan add [明天] -m "计划描述" [-p "71354 Q3.3.6.4"] [-r 完成情况] [-t 调整]')
            return 1

        # 站点要求 problem_ids 用 | 分隔（空格/逗号也帮你换掉）
        problems = args.problems if args.problems is not None else (existing.get("problem_ids") or "")
        problems = re.sub(r"[\s,，、]+", "|", problems.strip()).strip("|")

        payload = {
            "id": existing.get("id") or 0,
            "type": ptype,
            "date": ts,
            "user_id": user_id,
            "problem_ids": problems,
            "plan": plan_text.strip(),
            "result": (args.result if args.result is not None else existing.get("result") or ""),
            "tweak": (args.tweak if args.tweak is not None else existing.get("tweak") or ""),
        }
        verb = "修改" if payload["id"] else "新建"
        print(f"[计划] {verb} {day.isoformat()} 周{weekday}  {ptype}")
        print(f"[计划] 题目：{payload['problem_ids'] or '（无）'}")
        print(f"[计划] 描述：{payload['plan'][:80] or '（空）'}")
        if args.dry_run:
            print("[预演] 仅显示，不提交")
            return 0
        try:
            r = client.request("post", "/user_plan", json=payload)
        except RuntimeError as exc:
            print(f"[错误] {exc}")
            return 1
        try:
            data = r.json()
        except ValueError:
            print(f"[失败] HTTP {r.status_code}：{strip_tags(r.text)[:200]}")
            return 1
        if not data.get("success"):
            print(f"[失败] {data.get('err') or data}")
            return 1
        print(f"[OK] 已{'修改' if payload['id'] else '创建'}计划 #{data.get('id') or payload['id']}")
        return 0

    print(f"[错误] 未知操作：{action}")
    return 1


def cmd_submissions(args):
    """提交记录查询：/submissions 的筛选参数 + 分页（服务端内嵌 itemList）。"""
    client = make_client(args)
    client.load_session()

    base_params = {}
    if args.problem:
        base_params["problem_id"] = args.problem
    if args.submitter:
        base_params["submitter"] = args.submitter
    if args.status:
        base_params["status"] = args.status
    if args.language:
        base_params["language"] = args.language
    if args.min_score is not None:
        base_params["min_score"] = args.min_score
    if args.max_score is not None:
        base_params["max_score"] = args.max_score

    page = max(1, args.page)
    total_pages = None
    for _ in range(max(1, args.pages)):
        params = dict(base_params, page=page)
        try:
            r = client.get("/submissions", params=params)
        except RuntimeError as exc:
            print(f"[错误] {exc}")
            return 1
        items = extract_json_array(r.text, "itemList") or []
        if total_pages is None:
            pages = [int(x) for x in re.findall(r"/submissions\?[^\"]*page=(\d+)", r.text)]
            total_pages = max(pages) if pages else 1
            filt = " ".join(f"{k}={v}" for k, v in base_params.items())
            print(f"[提交] 第 {page}/{total_pages} 页  共 {len(items)} 条"
                  + (f"  筛选：{filt}" if filt else ""))
        else:
            print(f"[提交] 第 {page}/{total_pages} 页  共 {len(items)} 条")
        if not items:
            print("  （没有更多记录）")
            return 0
        for item in items:
            info = item.get("info") or {}
            result = item.get("result") or {}
            no = info.get("problemEid") or info.get("problemId") or "-"
            title = info.get("problemName") or ""
            who = info.get("nickname") or info.get("user") or ""
            status = result.get("result") or ("评测中" if item.get("running") else "等待")
            score = result.get("score")
            score_txt = f"{score:.0f}" if isinstance(score, (int, float)) else "-"
            print(f"  #{info.get('submissionId')}  {pad(no, 11)} {pad(title, 18)} {pad(who, 12)} "
                  f"{pad(info.get('language') or '', 8)} {pad(status, 22)} "
                  f"{pad(score_txt, 3, 'right')}  "
                  f"{pad(str(result.get('time') or 0) + 'ms', 7, 'right')} "
                  f"{pad(str(result.get('memory') or 0) + 'KB', 9, 'right')}  "
                  f"{info.get('submitTime')}")
        if args.pages > 1:
            page += 1
            if total_pages and page > total_pages:
                break
    return 0


# ---------------------------------------------------------------- 复盘（站点 tag）
REVIEW_EDIT_URL = "/review/user_tag/edit"


def parse_tag_arg(text):
    """从 tag_id 或整条编辑页 URL 里取 (tag_id, user_id)。"""
    text = (text or "").strip()
    tid = re.search(r"tag_id=(\d+)", text)
    uid = re.search(r"user_id=(\d+)", text)
    if tid:
        return tid.group(1), (uid.group(1) if uid else None)
    if text.isdigit():
        return text, (uid.group(1) if uid else None)
    raise RuntimeError(f"看不懂的复盘参数：{text}（给 tag_id，或直接粘编辑页 URL）")


def fetch_review_tag(client, tag_id, user_id):
    """GET /review/user_tag/edit?format=json -> {tag_review, problems, ...}"""
    r = client.get(REVIEW_EDIT_URL, params={"format": "json", "user_id": user_id, "tag_id": tag_id})
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"复盘接口返回异常（HTTP {r.status_code}）：{r.text[:120]}")
    if not data.get("success"):
        raise RuntimeError(f"读取复盘失败：{data.get('err') or data}")
    return data


def review_payload(data):
    """GET 的结构 -> POST 需要的结构（原样保留已写内容）。"""
    def as_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value

    keys = ("normal", "subtasks", "rethink", "other", "guess_score", "mistakes")
    problem_review = {}
    for prob in data.get("problems") or []:
        review = prob.get("review") or {}
        item = {k: review[k] for k in keys if k in review}
        # 子任务四项前端读的是输入框 .val()（字符串），数字 0 会被站点当成“没填”
        subs = []
        for sub in item.get("subtasks") or []:
            subs.append({k: ("" if sub.get(k) is None else str(sub.get(k)))
                         for k in ("actual", "expected", "total", "description")})
        if "subtasks" in item:
            item["subtasks"] = subs
        problem_review[str(prob.get("id"))] = item
    return {
        "user_id": as_int(data.get("user_id")),
        "tag_id": as_int(data.get("tag_id")),
        "tag_review": data.get("tag_review") or [],
        "problem_review": problem_review,
    }


def upload_review(client, payload):
    """POST /review/user_tag/edit，表单字段 data = JSON 字符串（站点就是这么传的）。"""
    r = client.request("post", REVIEW_EDIT_URL,
                       data={"data": json.dumps(payload, ensure_ascii=False)})
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"上传失败（HTTP {r.status_code}）：{r.text[:160]}")
    if not data.get("success"):
        raise RuntimeError(f"上传失败：{data.get('err') or data}")
    return data


def print_review(problems, tag_review, title=""):
    if title:
        print(f"[复盘] {title}")
    if tag_review:
        print("[时间线]")
        for line in tag_review:
            print(f"  {line.get('time') or '--:--'}  {line.get('plan') or ''}")
            for extra in (line.get("achieve") or "").splitlines():
                if extra.strip():
                    print(f"           {extra.strip()}")
    if problems:
        print(f"\n[题目] {len(problems)} 道")
    for prob in problems:
        rev = prob.get("review") or {}
        print(f"  {prob.get('exercise_name')}. {prob.get('title')}   "
              f"估分 {rev.get('guess_score')}  实际 {rev.get('sum_actual')}")
        normal = rev.get("normal") or {}
        if normal:
            print("    常规：" + "  ".join(f"{k}={v}" for k, v in normal.items()))
        for sub in rev.get("subtasks") or []:
            print(f"    子任务：得 {sub.get('actual')}/{sub.get('total')}"
                  f"（估 {sub.get('expected')}） {sub.get('description') or ''}")
        for key, label in (("rethink", "反思"), ("other", "其他")):
            val = (rev.get(key) or "").strip()
            if val:
                print(f"    {label}：" + val.replace("\n", " / "))
        if rev.get("mistakes"):
            print("    错误：" + " ".join(rev["mistakes"]))


REVIEW_DIR = os.path.join(BASE_DIR, "reviews")


def review_md_path(tag_id):
    return os.path.join(REVIEW_DIR, f"{tag_id}.md")


def review_to_markdown(data, title="", blank=False):
    """把站点复盘转成可编辑的 markdown；blank=True 只留空结构（从零开始写）。"""
    problems = data.get("problems") or []
    tag_review = data.get("tag_review") or []
    lines = [f"# 复盘 {title}".rstrip(), "",
             "<!-- 改完执行: 7fa4 review import <tag> -f 本文件 -->",
             "<!-- 时间线行数固定（站点按行校验），题目块数量也要对应，别删条目 -->", ""]

    def block(text):
        """多行内容用 ~~~ 围栏包住，避免内容里出现「反思：」之类被误认成字段。"""
        body = "" if blank else (text or "").strip("\n")
        return ["~~~", body, "~~~"]

    lines += ["## 时间线", ""]
    for entry in tag_review:
        lines += [f"### {entry.get('time') or '00:00'}", ""]
        lines += ["计划：", *block(entry.get("plan")), ""]
        lines += ["完成：", *block(entry.get("achieve")), ""]

    lines += ["## 题目", ""]
    for prob in problems:
        review = prob.get("review") or {}
        head = f"{prob.get('exercise_name') or ''} {prob.get('title') or ''}".strip()
        lines += [f"### {head}", ""]
        guess = "" if blank or review.get("guess_score") is None else review["guess_score"]
        lines += [f"估分：{guess}", ""]
        normal = {} if blank else (review.get("normal") or {})
        lines += ["常规：" + ", ".join(f"{k}={v}" for k, v in normal.items()), ""]
        lines += ["子任务："]
        for sub in ([] if blank else (review.get("subtasks") or [])):
            desc = (sub.get("description") or "").strip()
            lines.append(f"- {sub.get('actual')}/{sub.get('total')} "
                         f"期望{sub.get('expected')} {desc}".rstrip())
        lines += ["", "反思：", *block(review.get("rethink")), ""]
        lines += ["其他：", *block(review.get("other")), ""]
        lines += ["错误：" + ("" if blank else " ".join(review.get("mistakes") or [])), ""]
    return "\n".join(lines).rstrip() + "\n"


def parse_review_markdown(md):
    """解析 review_to_markdown 的格式，返回 {'timeline': [...], 'problems': [...]}。"""
    timeline, problems = [], []
    section = None
    item = None
    field = None
    buf = []
    subtasks = []

    def flush_field():
        nonlocal buf, field
        if item is not None and field:
            item[field] = "\n".join(buf).strip("\n").strip()
        buf, field = [], None

    def flush_item():
        nonlocal item, subtasks
        flush_field()
        if item is not None:
            if subtasks:
                item["subtasks"] = subtasks
            (timeline if section == "timeline" else problems).append(item)
        item, subtasks = None, []

    in_fence = False
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.strip() == "~~~":
            in_fence = not in_fence
            continue
        if in_fence:
            if item is not None and field:
                buf.append(line)
            continue
        if line.startswith("## "):
            flush_item()
            name = line[3:].strip()
            section = "timeline" if "时间线" in name else "problems" if "题目" in name else None
            continue
        if line.startswith("# "):
            flush_item()
            section = None
            continue
        if line.startswith("### "):
            flush_item()
            head = line[4:].strip()
            if section == "timeline":
                item = {"time": head, "plan": "", "achieve": ""}
            elif section == "problems":
                item = {"head": head}
            continue
        if item is None or section is None:
            continue

        if section == "timeline":
            matched = False
            for key, label in (("plan", "计划："), ("achieve", "完成：")):
                if line.startswith(label):
                    flush_field()
                    field = key
                    rest = line[len(label):].strip()
                    buf = [rest] if rest else []
                    matched = True
                    break
            if not matched and field:
                buf.append(line)
            continue

        if line.startswith("估分："):
            flush_field()
            item["guess_score"] = line[3:].strip()
        elif line.startswith("常规："):
            flush_field()
            pairs = {}
            for chunk in line[3:].replace("，", ",").split(","):
                if "=" in chunk:
                    key, value = chunk.split("=", 1)
                    pairs[key.strip()] = value.strip()
            item["normal"] = pairs
        elif line.startswith("子任务："):
            flush_field()
            field = None
        elif line.startswith("- "):
            m = re.match(r"^-\s*(\S+)/(\S+)\s*(?:期望\s*(\S+))?\s*(.*)$", line)
            if m:
                subtasks.append({"actual": m.group(1), "total": m.group(2),
                                 "expected": m.group(3) or "0",
                                 "description": m.group(4).strip()})
        elif line.startswith("反思："):
            flush_field()
            field = "rethink"
            rest = line[3:].strip()
            buf = [rest] if rest else []
        elif line.startswith("其他："):
            flush_field()
            field = "other"
            rest = line[3:].strip()
            buf = [rest] if rest else []
        elif line.startswith("错误："):
            flush_field()
            item["mistakes"] = line[3:].replace("，", " ").split()
        elif field:
            buf.append(line)
    flush_item()
    return {"timeline": timeline, "problems": problems}


def apply_review_markdown(payload, parsed, problems):
    """把 markdown 内容写进上传用的 payload（站点行数固定，逐条对应）。"""
    timeline = payload["tag_review"]
    for i, entry in enumerate(parsed["timeline"]):
        if i >= len(timeline):
            print(f"[警告] md 里时间线多了 {len(parsed['timeline']) - len(timeline)} 条，已忽略（站点行数固定）")
            break
        for key in ("time", "plan", "achieve"):
            if key in entry:
                timeline[i][key] = entry[key]

    for entry in parsed["problems"]:
        head = entry.get("head") or ""
        target = None
        for prob in problems:
            name = f"{prob.get('exercise_name') or ''} {prob.get('title') or ''}".strip()
            if head == name or (prob.get("exercise_name") and prob["exercise_name"] in head) \
                    or (prob.get("title") and prob["title"] in head):
                target = prob
                break
        if not target:
            print(f"[警告] md 里的题目「{head}」在站点上没找到，已跳过")
            continue
        review = payload["problem_review"].setdefault(str(target["id"]), {})
        if "guess_score" in entry:
            value = entry["guess_score"]
            review["guess_score"] = value if value != "" else None
        if entry.get("normal"):
            review["normal"] = entry["normal"]
        if "subtasks" in entry:
            review["subtasks"] = entry["subtasks"]
        for key in ("rethink", "other"):
            if key in entry:
                review[key] = entry[key]
        if "mistakes" in entry:
            review["mistakes"] = entry["mistakes"]
    return payload


def cmd_review(args):
    """站点复盘（tag）：show / html / export 导出 md / new 空模板 / import 上传 md。"""
    client = make_client(args)
    client.load_session()
    action = (args.action or "show").lower()
    try:
        tag_id, uid_in_url = parse_tag_arg(getattr(args, "tag", ""))
        user_id = getattr(args, "user", None) or uid_in_url or current_user_id(client)
        data = fetch_review_tag(client, tag_id, user_id)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    problems = data.get("problems") or []
    tag_review = data.get("tag_review") or []
    prefix = ""
    for prob in problems:
        name = prob.get("exercise_name") or ""
        if name:
            prefix = name.rsplit(".", 1)[0]
            break
    title = prefix or f"tag {tag_id}"

    if action == "show":
        print_review(problems, tag_review, title)
        print(f"[链接] {client.base}/review/user_tags/html?tag_id={tag_id}")
        return 0

    if action == "html":
        r = client.get("/review/user_tags/html", params={"tag_id": tag_id})
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", r.text)
        print(strip_tags(text)[:4000])
        print(f"[链接] {client.base}/review/user_tags/html?tag_id={tag_id}")
        return 0

    if action in ("export", "new"):
        blank = action == "new"
        md = review_to_markdown(data, title, blank=blank)
        path = args.file or args.output or review_md_path(tag_id)
        write_text(path, md)
        print(f"[{'模板' if blank else '导出'}] {path}  {len(md)} 字符")
        print(f"[提示] 改完执行 review import {tag_id} -f \"{path}\" 上传")
        return 0

    payload = review_payload(data)

    if action == "import":
        if not args.file:
            print(f"[错误] 用 -f 指定 md（先 review export {tag_id} 或 review new {tag_id}）")
            return 1
        if not os.path.exists(args.file):
            print(f"[错误] 文件不存在：{args.file}")
            return 1
        parsed = parse_review_markdown(read_text_any(args.file))
        apply_review_markdown(payload, parsed, problems)
        print(f"[导入] {os.path.basename(args.file)}：时间线 {len(parsed['timeline'])} 条，"
              f"题目 {len(parsed['problems'])} 道")

    if action == "add":
        print("[提示] 站点不支持给复盘表增加时间线（行数固定，服务端按行校验）")
        print("       改已有行用: review timeline <tag> -i <行号> -p \"计划\" -a \"完成\"")
        print("       改某道题用: review set <tag> -q <题目> --rethink \"...\"")
        return 1

    if action == "timeline":
        lines = payload["tag_review"]
        idx = args.index or 0
        if not (1 <= idx <= len(lines)):
            print(f"[错误] 行号要在 1~{len(lines)} 之间（当前复盘共 {len(lines)} 行）")
            for i, line in enumerate(lines, 1):
                print(f"  {i}. {line.get('time') or '--:--'}  {line.get('plan') or ''}")
            return 1
        line = lines[idx - 1]
        if args.time:
            line["time"] = args.time
        if args.plan is not None:
            line["plan"] = args.plan
        if args.achieve is not None:
            line["achieve"] = args.achieve
        print(f"[时间线] 第 {idx} 行 -> {line.get('time')}  {line.get('plan') or ''}")
    elif action == "set":
        key = (args.problem or "").lower()
        hit = [p for p in problems
               if key and (key in str(p.get("title", "")).lower()
                           or key == str(p.get("exercise_name", "")).lower()
                           or key == str(p.get("id")))]
        if len(hit) != 1:
            print(f"[错误] 题目匹配到 {len(hit)} 个，用题目名/编号/id 精确指定：")
            for prob in problems:
                print(f"  {prob.get('id')}  {prob.get('exercise_name')}  {prob.get('title')}")
            return 1
        rev = payload["problem_review"].setdefault(str(hit[0]["id"]), {})
        if args.rethink is not None:
            rev["rethink"] = args.rethink
        if args.other is not None:
            rev["other"] = args.other
        if args.guess is not None:
            rev["guess_score"] = args.guess
        if args.normal:
            for pair in args.normal.split(","):
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    rev.setdefault("normal", {})[name.strip()] = value.strip()
    elif action == "import":
        pass                     # 上面已经解析并写进 payload
    else:
        print(f"[错误] 未知操作：{action}")
        return 1

    if args.dry_run:
        if payload["tag_review"]:
            print(f"[预演] 时间线 {len(payload['tag_review'])} 条，最后一条："
                  f"{json.dumps(payload['tag_review'][-1], ensure_ascii=False)}")
        print(f"[预演] 题目 {len(payload['problem_review'])} 道")
        return 0
    try:
        upload_review(client, payload)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    print(f"[OK] 已上传 tag {tag_id}：时间线 {len(payload['tag_review'])} 条，"
          f"题目 {len(payload['problem_review'])} 道")
    print(f"[链接] {client.base}/review/user_tag/edit?user_id={user_id}&tag_id={tag_id}")
    return 0


def extract_js_json(text, key):
    """从 JS 源码里取 `key: {...}` 的 JSON（字符串感知地配对花括号）。"""
    i = text.find(key + ":")
    if i < 0:
        return None
    start = text.find("{", i)
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for j in range(start, len(text)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:j + 1])
                except ValueError:
                    return None
    return None


def extract_json_array(text, marker):
    """从 JS 源码里取 `marker:` 之后的 JSON 数组（字符串感知配对方括号）。"""
    i = text.find(marker)
    if i < 0:
        return None
    start = text.find("[", i)
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for j in range(start, len(text)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:j + 1])
                except ValueError:
                    return None
    return None


def extract_js_string(text, name):
    m = re.search(r'const %s = ("(?:[^"\\]|\\.)*")' % re.escape(name), text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def fetch_submission_item(client, sid):
    """状态走 /submissions/?id=xxx（页面里内嵌 itemList，只有一条）。"""
    r = client.get("/submissions/", params={"id": sid})
    items = extract_json_array(r.text, "itemList") or []
    for item in items:
        info = item.get("info") or {}
        if str(info.get("submissionId")) == str(sid):
            return item
    return None


def ask_continue(prompt):
    """问用户继续还是停止；非交互环境按“停止”处理。"""
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes", "1")


def cmd_submission(args):
    """看某次提交：状态走 /submissions/?id=，代码走 /submission/<id>（必要时问是否继续）。"""
    sid = str(args.sid or "").strip()
    m = re.search(r"id=(\d+)", sid)
    if m:
        sid = m.group(1)
    if not sid.isdigit():
        print(f"[错误] 提交编号不合法：{args.sid}")
        return 1

    client = make_client(args)
    client.load_session()
    try:
        item = fetch_submission_item(client, sid)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    info = (item or {}).get("info") or {}
    result = (item or {}).get("result") or {}
    if info:
        print(f"[提交] #{info.get('submissionId')}  {info.get('problemEid', '')} {info.get('problemName', '')}")
        print(f"[信息] 题目 {info.get('problemId')}   {info.get('language')}   "
              f"{info.get('codeSize')} 字符   提交 {info.get('submitTime')}")
        print(f"[提交者] {info.get('nickname') or info.get('uid') or info.get('user')}"
              f"（{info.get('user') or info.get('userId')}）")
        status, final, score_text, time_ms, memory_kb = result_state(item)
        if final:
            print(f"[状态] {status}  分数 {score_text}  "
                  f"用时 {time_ms or 0} ms  内存 {memory_kb or 0} KB")
        else:
            print(f"[状态] {status}（还没出结果）")
        print(f"[链接] {client.base}/submission/{sid}")
    else:
        print(f"[提示] /submissions/?id={sid} 里没有这条记录（可能是比赛内提交）")

    # 作废 / 删除 / 重新评测（页面上的 href-post 按钮就是这三个地址）
    actions = [("revoke", "作废", getattr(args, "revoke", False)),
               ("deleted", "删除", getattr(args, "delete", False)),
               ("rejudge", "重新评测", getattr(args, "rejudge", False))]
    chosen = [(path, label) for path, label, flag in actions if flag]
    if chosen:
        path, label = chosen[0]
        if not args.yes:
            tip = "作废只是评测作废，删除后记录无法再访问" if path != "rejudge" else "会重新排队评测"
            print(f"[确认] 即将{label}提交 #{sid}（{tip}）")
            if not ask_continue(f"确认{label}？"):
                print("[停止] 已取消")
                return 0
        url = f"{client.base}/submission/{sid}/{path}"
        try:
            r = client.s.post(url, timeout=client.timeout, allow_redirects=False,
                              headers={"X-Requested-With": "XMLHttpRequest"})
        except requests.RequestException as exc:
            print(f"[错误] 请求失败：{exc}")
            return 1
        if 300 <= r.status_code < 400:
            print(f"[OK] 已{label} #{sid} -> {r.headers.get('Location')}")
            return 0
        if r.status_code == 200:
            if "错误 - 7FA4" in r.text:
                msg = strip_tags(r.text.split("ui main container")[-1])[:200]
                print(f"[失败] {label}被拒绝：{msg or '权限不足或状态不允许'}")
                return 1
            print(f"[OK] 已{label} #{sid}")
            return 0
        print(f"[结果] HTTP {r.status_code} {strip_tags(r.text)[:200]}")
        return 1

    if not (args.code or args.save):
        print(f"[代码] 加 --code 显示，或 --save <文件> 保存")
        return 0

    # 看代码要走 /submission/<id>：别人的提交站点会报错，先问一句
    my_uid = None
    try:
        my_uid = current_user_id(client)
    except RuntimeError:
        pass
    owner = info.get("userId")
    if owner and my_uid and str(owner) != str(my_uid) and not args.yes:
        print(f"[提示] 这是 {info.get('nickname') or info.get('uid')} 的提交，"
              f"代码页可能打不开（站点对他人提交会报错）")
        if not ask_continue("仍要继续尝试读取代码？"):
            print("[停止] 已取消")
            return 0

    try:
        r = client.get(f"/submission/{sid}")
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    code = extract_js_string(r.text, "unformattedCode")
    if code is None:
        if "错误 - 7FA4" in r.text:
            msg = strip_tags(r.text.split("ui main container")[-1])[:200]
            print(f"[失败] 代码页返回错误：{msg or '站点报错（他人提交或权限不足）'}")
            if not args.yes and ask_continue("换个方式再试一次（重新请求）？"):
                try:
                    r = client.get(f"/submission/{sid}")
                except RuntimeError as exc:
                    print(f"[错误] {exc}")
                    return 1
                code = extract_js_string(r.text, "unformattedCode")
        if code is None:
            print("[代码] 取不到代码（他人提交 / 比赛内提交 / 纸面题答案图）")
            return 1

    if args.save:
        path = args.save
        if os.path.isdir(path):
            path = os.path.join(path, f"submission{sid}.cpp")
        write_text(path, code)
        print(f"[代码] 已保存 -> {path}（{len(code)} 字符）")
        return 0

    if len(code) > args.max_chars and not args.yes:
        if not ask_continue(f"代码有 {len(code)} 字符，继续显示？"):
            print("[代码] 已跳过")
            return 0

    print("-" * 60)
    print("\n".join(f"{i:>4}  {line}" for i, line in enumerate(code.splitlines(), 1)))
    print("-" * 60)
    return 0


def cmd_help(args):
    """分级帮助：help 看总览，help <命令> 看该命令的详细参数。"""
    parser = build_parser()
    topics = [t for t in (args.topic or []) if t]
    if not topics:
        parser.print_help()
        return 0
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            sub = action.choices.get(topics[0])
            if not sub:
                print(f"[错误] 没有命令：{topics[0]}")
                print("可用：" + " / ".join(sorted(action.choices)))
                return 1
            sub.print_help()
            if len(topics) > 1:
                print(f"\n（{topics[0]} 没有更深的子命令，用 {topics[0]} --help 看参数）")
            return 0
    return 0


# ---------------------------------------------------------------- SFTP 存储（5307）
def sftp_endpoint(args):
    """SFTP 默认跟随当前 7FA4 站点、端口 5307，可用 config 里的 sftp_host/sftp_port 覆盖。"""
    cfg = load_config()
    host = str(cfg.get("sftp_host") or "").strip()
    if not host:
        port = getattr(args, "port", None) or DEFAULT_PORT
        host = pick_host(getattr(args, "host", None), port)
    return cfg, host, int(cfg.get("sftp_port") or 5307)


def sftp_local_dir(cfg):
    """本地暂存目录：默认项目下的 sftp/，可用 config 的 sftp_local 覆盖。"""
    path = cfg.get("sftp_local") or os.path.join(BASE_DIR, "sftp")
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    os.makedirs(path, exist_ok=True)
    return os.path.abspath(path)


def sftp_remote_path(cfg, path):
    """相对路径按 sftp_cwd 解析，绝对路径原样规范化。"""
    if not path:
        return cfg.get("sftp_cwd") or "/"
    if path.startswith(("/", "~")):
        return posixpath.normpath(path)
    return posixpath.normpath(posixpath.join(cfg.get("sftp_cwd") or "/", path))


def sftp_local_path(cfg, path):
    """本地路径：绝对路径/./开头按当前目录，其它相对路径落到 sftp/ 暂存目录。"""
    if os.path.isabs(path) or path.startswith("." + os.sep) or path.startswith("./"):
        return os.path.abspath(path)
    return os.path.join(sftp_local_dir(cfg), os.path.basename(path.rstrip("/\\")))


def sftp_connect(args, save=False):
    """建立 SFTP 连接，返回 (ssh, sftp, 描述)；save=True 时把账号密码写进 config.json。"""
    try:
        import paramiko
    except ImportError:
        raise RuntimeError("SFTP 需要 paramiko：pip install paramiko")

    cfg, host, port = sftp_endpoint(args)
    user = getattr(args, "user", None) or cfg.get("sftp_user") or input("SFTP 用户名: ")
    password = cfg.get("sftp_password") or getattr(args, "password", None)
    if not password:
        password = getpass.getpass("SFTP 密码: ")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, port=port, username=user, password=password or None,
                    key_filename=cfg.get("sftp_key") or None, timeout=20,
                    allow_agent=False, look_for_keys=False)
    except paramiko.AuthenticationException:
        raise RuntimeError(f"SFTP 认证失败（{user}@{host}:{port}）")
    except Exception as exc:
        raise RuntimeError(f"连接 SFTP {host}:{port} 失败：{exc}")

    if save:
        cfg.update({"sftp_host": host, "sftp_port": port,
                    "sftp_user": user, "sftp_password": password})
        save_config(cfg)
    return ssh, ssh.open_sftp(), f"{user}@{host}:{port}"


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}B" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.0f}B"


def cmd_sftp(args):
    """SFTP 存储：login / ls / pwd / cd / lcd / get / put / mkdir / rmdir / rm。"""
    action, paths = args.action, args.paths or []
    cfg = load_config()
    cwd = cfg.get("sftp_cwd") or "/"

    if action == "lcd":
        target = paths[0] if paths else os.path.join(BASE_DIR, "sftp")
        os.makedirs(target, exist_ok=True)
        cfg["sftp_local"] = os.path.abspath(target)
        save_config(cfg)
        print(f"[本地] {cfg['sftp_local']}")
        return 0
    if action == "lpwd":
        print(sftp_local_dir(cfg))
        return 0

    try:
        ssh, sftp, who = sftp_connect(args, save=(action == "login"))
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    try:
        if action == "login":
            print(f"[OK] 已连接 {who}，账号密码已存入 config.json")
            print(f"[远程] {sftp.normalize('.')}")
            print(f"[本地] {sftp_local_dir(cfg)}")
            return 0

        if action == "pwd":
            print(cwd)
            return 0

        if action == "cd":
            target = sftp_remote_path(cfg, paths[0] if paths else "/")
            try:
                attr = sftp.stat(target)
            except IOError:
                print(f"[错误] 远程目录不存在：{target}")
                return 1
            if not (attr.st_mode or 0) & 0o40000:
                print(f"[错误] 不是目录：{target}")
                return 1
            cfg["sftp_cwd"] = target
            save_config(cfg)
            print(f"[CD] {target}")
            return 0

        if action == "ls":
            remote = sftp_remote_path(cfg, paths[0] if paths else "")
            entries = sorted(sftp.listdir_attr(remote),
                             key=lambda x: (not (x.st_mode or 0) & 0o40000, x.filename.lower()))
            print(f"[SFTP] {who}  {remote}  共 {len(entries)} 项")
            for item in entries:
                is_dir = (item.st_mode or 0) & 0o40000
                when = (datetime.datetime.fromtimestamp(item.st_mtime).strftime("%Y-%m-%d %H:%M")
                        if item.st_mtime else "")
                size = "<DIR>" if is_dir else fmt_size(item.st_size or 0)
                print(f"  {size:>9}  {when:<16}  {item.filename}{'/' if is_dir else ''}")
            return 0

        if not paths:
            print(f"用法: sftp {action} <路径> [目标]")
            return 1

        if action == "get":
            remote = sftp_remote_path(cfg, paths[0])
            if len(paths) > 1:
                local = sftp_local_path(cfg, paths[1])
            else:
                local = os.path.join(sftp_local_dir(cfg), os.path.basename(remote.rstrip("/")) or "download")
            if os.path.isdir(local):
                local = os.path.join(local, os.path.basename(remote.rstrip("/")))
            os.makedirs(os.path.dirname(local) or ".", exist_ok=True)
            sftp.get(remote, local)
            print(f"[下载] {remote} -> {local}  {fmt_size(os.path.getsize(local))}")
            return 0

        if action == "put":
            local = sftp_local_path(cfg, paths[0])
            if not os.path.exists(local):
                print(f"[错误] 本地文件不存在：{local}")
                return 1
            remote = sftp_remote_path(cfg, paths[1]) if len(paths) > 1 else posixpath.join(cwd, os.path.basename(local))
            try:
                if (sftp.stat(remote).st_mode or 0) & 0o40000:
                    remote = posixpath.join(remote, os.path.basename(local))
            except IOError:
                pass
            sftp.put(local, remote)
            print(f"[上传] {local} -> {remote}  {fmt_size(os.path.getsize(local))}")
            return 0

        if action == "mkdir":
            target = sftp_remote_path(cfg, paths[0])
            sftp.mkdir(target)
            print(f"[OK] 已创建目录 {target}")
            return 0

        if action == "rmdir":
            target = sftp_remote_path(cfg, paths[0])
            sftp.rmdir(target)
            print(f"[OK] 已删除目录 {target}")
            return 0

        if action == "rm":
            target = sftp_remote_path(cfg, paths[0])
            sftp.remove(target)
            print(f"[OK] 已删除 {target}")
            return 0

        print(f"[错误] 未知操作：{action}")
        return 1
    except FileNotFoundError:
        print("[错误] 远程路径不存在")
        return 1
    except PermissionError:
        print("[错误] 没有权限")
        return 1
    except OSError as exc:
        print(f"[错误] SFTP 操作失败：{exc}")
        return 1
    finally:
        try:
            sftp.close()
            ssh.close()
        except Exception:
            pass


# ---------------------------------------------------------------- Markdown -> PNG
CJK_FONTS = [
    r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhl.ttc",
    r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]
MONO_FONTS = [
    r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\SimSun.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]


def _find_font(candidates):
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _strip_inline(text):
    """去掉行内 markdown 标记，保留文字与 $公式$。"""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?<!\\)\*(?!\s)", "", text)
    return text.strip()


def _wrap_text(text, font, max_width):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if font.getlength(cur + ch) <= max_width:
            cur += ch
        else:
            if cur.endswith(" "):
                lines.append(cur.rstrip())
                cur = ch
            elif ch == " ":
                lines.append(cur)
                cur = ""
            else:
                lines.append(cur)
                cur = ch
    lines.append(cur)
    return lines or [""]


def markdown_to_png(md_text, out_path, base_dir=".", width=1000):
    """把 markdown 渲染成 PNG（标题分级、代码块底色、本地图片嵌入）。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise RuntimeError("导出 PNG 需要 Pillow：pip install pillow")

    cjk_path = _find_font(CJK_FONTS)
    mono_path = _find_font(MONO_FONTS) or cjk_path

    def load(path, size):
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
        return ImageFont.load_default()

    f_h1, f_h2, f_h3 = load(cjk_path, 34), load(cjk_path, 28), load(cjk_path, 23)
    f_body, f_code = load(cjk_path, 19), load(mono_path, 16)
    PAD = 36
    content_w = width - PAD * 2
    BG, FG, CODE_BG, MUTED = (255, 255, 255), (33, 37, 41), (245, 245, 245), (110, 110, 110)

    blocks = []      # (font, lines, color, bg, extra_gap)

    def add_text(text, font, color=FG, bg=None, indent=0):
        for line in _wrap_text(text, font, content_w - indent):
            blocks.append([font, line, color, bg, indent])

    def add_image(title, src):
        path = src if os.path.isabs(src) else os.path.join(base_dir, src)
        if not os.path.exists(path):
            add_text(f"[图片缺失] {src}", f_body, MUTED)
            return
        try:
            img = Image.open(path)
            img.load()
        except Exception:
            add_text(f"[图片无法读取] {src}", f_body, MUTED)
            return
        if img.width > content_w:
            ratio = content_w / img.width
            img = img.resize((content_w, max(1, int(img.height * ratio))))
        blocks.append(["image", img, None, None, 0])

    lines = md_text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        if line.startswith("```"):                     # 代码块
            i += 1
            code = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            for code_line in code or [""]:
                add_text(code_line or " ", f_code, (40, 44, 52), CODE_BG)
            blocks.append([None, "", None, None, 0])
            continue
        if not line.strip():
            blocks.append([None, "", None, None, 0])
            i += 1
            continue
        img = MD_IMG_RE.search(line)
        if img:
            add_image(img.group(1), img.group(2))
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level, text = len(m.group(1)), _strip_inline(m.group(2))
            font = f_h1 if level == 1 else f_h2 if level == 2 else f_h3
            add_text(text, font)
            blocks.append([None, "", None, None, 0])
            i += 1
            continue
        if re.match(r"^([-*_])\1{2,}$", line.strip()):   # 分隔线
            blocks.append(["hr", "", None, None, 0])
            i += 1
            continue
        if line.lstrip().startswith("|"):                # 表格行
            if re.match(r"^\s*\|[\s:\-|]+\|\s*$", line):
                i += 1
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            add_text("  ".join(_strip_inline(c) for c in cells), f_body)
            i += 1
            continue
        if line.lstrip().startswith(">"):
            add_text(_strip_inline(line.lstrip()[1:]), f_body, MUTED, indent=24)
            i += 1
            continue
        m = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if m:
            indent = 24 + len(m.group(1)) * 12
            add_text(m.group(2) + " " + _strip_inline(m.group(3)), f_body, indent=indent)
            i += 1
            continue
        add_text(_strip_inline(line), f_body)
        i += 1

    # 计算高度
    heights, total = [], PAD
    for font, content, _color, bg, indent in blocks:
        if font is None:
            h = 12
        elif font == "hr":
            h = 16
        elif font == "image":
            h = content.height + 16
        elif bg:
            h = 26
        else:
            h = int(font.size * 1.75)
        heights.append(h)
        total += h
    total += PAD

    canvas = Image.new("RGB", (width, max(total, PAD * 2)), BG)
    draw = ImageDraw.Draw(canvas)
    y = PAD
    for (font, content, color, bg, indent), h in zip(blocks, heights):
        if font is None:
            y += h
        elif font == "hr":
            draw.line([(PAD, y + h // 2), (width - PAD, y + h // 2)], fill=(220, 220, 220))
            y += h
        elif font == "image":
            canvas.paste(content, (PAD, y + 8))
            y += h
        elif bg:
            draw.rectangle([PAD, y, width - PAD, y + h], fill=bg)
            draw.text((PAD + 10, y + 4), content, font=font, fill=color)
            y += h
        else:
            draw.text((PAD + indent, y + 4), content, font=font, fill=color)
            y += h

    canvas.save(out_path)
    return out_path, canvas.size


def cmd_export(args):
    """把题面（或任意 md）导出成一张 PNG。"""
    client = make_client(args)
    client.load_session()

    md_path = args.file
    folder = None
    if not md_path:
        pid, label = None, None
        if args.id.lower().endswith(".md") and os.path.exists(args.id):
            md_path = args.id
            folder = os.path.dirname(os.path.abspath(md_path))
        else:
            try:
                pid, label = resolve_problem(client, args.id)
            except RuntimeError as exc:
                print(f"[错误] {exc}")
                return 1
            folder = find_problem_dir(pid)
            if not folder:
                print(f"[错误] 本地没有题目目录，先执行 pull {args.id}")
                return 1
            md_path = os.path.join(folder, "statement.md")
    if not md_path or not os.path.exists(md_path):
        print(f"[错误] 找不到 markdown：{md_path}")
        return 1

    base_dir = folder or os.path.dirname(os.path.abspath(md_path))
    out_path = args.output or os.path.join(base_dir, "statement.png")
    try:
        with open(md_path, encoding="utf-8") as f:
            md_text = f.read()
        path, size = markdown_to_png(md_text, out_path, base_dir, width=args.width)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    except OSError as exc:
        print(f"[错误] 写入失败：{exc}")
        return 1

    print(f"[导出] {md_path} -> {path}")
    print(f"[尺寸] {size[0]}x{size[1]}  {os.path.getsize(path)} 字节")
    if args.preview:
        show_captcha_inline(path, "预览")
    return 0


def cmd_template(args):
    cfg = load_config()
    action = (args.action or "show").lower()

    if action == "set":
        src = args.file
        if not src:
            print("用法: template set <模板文件路径>")
            return 1
        if not os.path.exists(src):
            print(f"[错误] 模板文件不存在：{src}")
            return 1
        os.makedirs(TEMPLATE_DIR, exist_ok=True)
        dst = os.path.join(TEMPLATE_DIR, os.path.basename(src))
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copyfile(src, dst)
        cfg["template"] = os.path.relpath(dst, BASE_DIR)
        save_config(cfg)
        print(f"[OK] 已设置模板：{cfg['template']}")
        print("     pull 生成 cpp 时会使用它，占位符：{{id}} {{no}} {{title}} {{short}} {{url}} {{date}}")
        return 0

    if action == "reset":
        cfg.pop("template", None)
        save_config(cfg)
        print("[OK] 已恢复内置模板")
        return 0

    path = resolve_template_file()
    print(f"[模板] {path}" if path else "[模板] 未设置，使用内置模板")
    print("-" * 60)
    if path:
        print(read_text_any(path).rstrip("\n"))
    else:
        print(default_template_text().rstrip("\n"))
    print("-" * 60)
    print("可用占位符：{{id}} {{no}} {{title}} {{short}} {{url}} {{date}} "
          "{{infile}} {{outfile}} {{io_mode}} {{freopen}}")
    print("设置：template set <文件>；恢复：template reset")
    return 0


def cmd_get(args):
    client = make_client(args)
    client.load_session()
    try:
        dump_response(client.get(args.path), full=args.full)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    return 0


def cmd_post(args):
    client = make_client(args)
    client.load_session()
    try:
        dump_response(client.post(args.path, data=parse_kv(args.data)), full=args.full)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    return 0


def cmd_raw(args):
    client = make_client(args)
    client.load_session()
    try:
        dump_response(client.request(args.method, args.path, data=parse_kv(args.data)), full=args.full)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    return 0


def cmd_shell(args):
    client = make_client(args)
    if client.load_session() and client.whoami()[0]:
        print(f"[已登录] {client.base}（{client.username or '未知用户'}）")
    else:
        print(f"[未登录] {client.base}，可用 login 命令登录")

    parser = build_parser()
    host = client.host
    print("输入 help 查看命令，quit 退出。")
    while True:
        try:
            line = input(f"{host}> ").strip().lstrip("\ufeff")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            return 0
        try:
            argv = shlex.split(line)
        except ValueError as exc:
            print(f"[错误] {exc}")
            continue
        if argv[0] in ("shell",):
            print("[提示] 已在交互终端中")
            continue
        if argv[0] in ("help", "?"):
            parser.print_help()
            continue
        try:
            ns = parser.parse_args(argv)
        except SystemExit:
            continue
        if "--host" in argv:
            host = pick_host(ns.host, client.port)
        ns.host = host
        if "--port" not in argv:
            ns.port = client.port
        if "--timeout" not in argv:
            ns.timeout = client.timeout
        try:
            ns.func(ns)
        except (RuntimeError, requests.RequestException) as exc:
            print(f"[错误] {exc}")


# ---------------------------------------------------------------- argparse
# ---------------------------------------------------------------- 自动更新
DEFAULT_UPDATE_URL = "http://localhost:9080/terminal.py"


def self_file():
    return os.path.abspath(__file__)


def read_self_bytes():
    try:
        with open(self_file(), "rb") as f:
            return f.read()
    except OSError:
        return b""


def fetch_remote_script(url, timeout=8.0):
    try:
        r = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"拉取失败：{type(exc).__name__}: {exc}") from exc
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    if not r.content.strip():
        raise RuntimeError("远端文件是空的")
    return r.content


def apply_update(content):
    """语法校验后原子替换自身，旧文件留 .bak 备份。"""
    path = self_file()
    tmp = path + ".new"
    with open(tmp, "wb") as f:
        f.write(content)
    try:
        compile(content, path, "exec")
    except SyntaxError as exc:
        os.remove(tmp)
        raise RuntimeError(f"新版本语法错误（第 {exc.lineno} 行）：{exc.msg}")
    backup = path + ".bak"
    try:
        shutil.copyfile(path, backup)
    except OSError:
        backup = ""
    os.replace(tmp, path)
    return backup


def update_url_of(args=None):
    return (getattr(args, "url", None)
            or load_config().get("update_url")
            or DEFAULT_UPDATE_URL)


def cmd_update(args):
    url = update_url_of(args)
    print(f"[更新] 源：{url}")
    try:
        remote = fetch_remote_script(url, args.timeout)
    except RuntimeError as exc:
        print(f"[更新] {exc}")
        return 1
    local = read_self_bytes()
    if remote == local:
        print("[更新] 已是最新版本")
        return 0
    print(f"[更新] 发现新版本：远端 {len(remote)} 字节，本地 {len(local)} 字节")
    if args.check:
        print("[更新] 去掉 --check 即可应用")
        return 0
    try:
        backup = apply_update(remote)
    except (RuntimeError, OSError) as exc:
        print(f"[更新] 应用失败：{exc}")
        return 1
    print(f"[更新] 已更新 {self_file()}" + (f"，备份 {backup}" if backup else ""))
    print("[更新] 重新执行命令即生效")
    return 0


def auto_update_check():
    """按 config 的 auto_update 策略检查：off / check（默认，只提示）/ apply。"""
    cfg = load_config()
    mode = str(cfg.get("auto_update") or "check").strip().lower()
    if mode in ("off", "0", "false", "no", "none"):
        return
    try:
        interval = float(cfg.get("update_interval") or 21600)
    except (TypeError, ValueError):
        interval = 21600
    now = time.time()
    try:
        last = float(cfg.get("update_checked_at") or 0)
    except (TypeError, ValueError):
        last = 0
    if now - last < interval:
        return
    cfg["update_checked_at"] = int(now)
    try:
        save_config(cfg)
    except OSError:
        pass
    url = cfg.get("update_url") or DEFAULT_UPDATE_URL
    try:
        remote = fetch_remote_script(url, 2.0)
    except RuntimeError:
        return
    if remote == read_self_bytes():
        return
    if mode == "apply":
        try:
            apply_update(remote)
            print("[更新] 已自动更新到新版本，重新执行命令生效")
        except (RuntimeError, OSError) as exc:
            print(f"[更新] 自动更新失败：{exc}")
    else:
        print(f"[更新] 有新版本（{len(remote)} 字节），运行 update 应用")


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default=None,
                        help=f"in / jx / auto 或完整域名（默认自动探测并记住可用站点，优先 {DEFAULT_HOST}）")
    common.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"端口（默认 {DEFAULT_PORT}）")
    common.add_argument("--timeout", type=float, default=15.0, help="请求超时秒数（默认 15）")

    output = argparse.ArgumentParser(add_help=False)
    output.add_argument("--full", action="store_true", help="输出完整内容，不截断")

    cfgopt = argparse.ArgumentParser(add_help=False)
    cfgopt.add_argument("--config", metavar="PATH",
                        help="配置文件路径（默认 %%APPDATA%%/7fa4_terminal/config.json，"
                             "也可用环境变量 7FA4_CONFIG）")

    parser = argparse.ArgumentParser(
        prog="7fa4_terminal.py",
        description="7FA4 OJ 终端客户端：登录、拉题、显示题面、提交代码",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python 7fa4_terminal.py login -u 用户名 -p 密码\n"
               "  python 7fa4_terminal.py list 6.5.5\n"
               "  python 7fa4_terminal.py pull Q6.4.6.1\n"
               "  python 7fa4_terminal.py template set my_template.cpp\n"
               "  python 7fa4_terminal.py run Q6.4.6.1\n"
               "  python 7fa4_terminal.py submit 6.4.6.1 -l cpp17\n"
               "  python 7fa4_terminal.py shell\n",
    )
    sub = parser.add_subparsers(dest="action", metavar="<命令>")

    p = sub.add_parser("login", parents=[common, cfgopt],
                       help="登录并保存会话（也可用 --cookie 导入浏览器 Cookie）")
    p.add_argument("-u", "--user", help="用户名（不填则提示输入）")
    p.add_argument("-p", "--password", help="密码（不填则安全输入）")
    p.add_argument("--cookie", help='直接给 Cookie 串，如 "login=xxx; connect.sid=yyy"')
    p.add_argument("--cookie-file", help="从文件读 Cookie（支持站点「下载当前凭证」的 YAML）")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("logout", parents=[common, cfgopt], help="清除本地会话")
    p.set_defaults(func=cmd_logout)

    p = sub.add_parser("whoami", parents=[common, cfgopt], help="查看登录状态")
    p.set_defaults(func=cmd_whoami)

    p = sub.add_parser("list", parents=[common, cfgopt], help="题目列表")
    p.add_argument("path", nargs="?", help="列表页路径（默认 /problems/exercises）")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("pull", parents=[common, cfgopt], help="获取题目：题面+样例解压+生成 cpp")
    p.add_argument("id", help="题目 ID（72874）或题号（Q6.4.6.1 / 6.4.6.1）")
    p.add_argument("-f", "--force", action="store_true", help="覆盖已存在的 cpp 文件")
    p.add_argument("-q", "--quiet", action="store_true", help="不打印题面，只下载文件")
    p.add_argument("-t", "--template", help="本次使用的模板文件（默认用 config.json 里设置的）")
    p.add_argument("--vj-cookie", help="vjudge 的 Cookie（拉外站题面用，默认读 config.json 的 vj_cookie）")
    p.add_argument("--from-md", action="store_true", help="题面用 markdown 源码（默认用渲染后的 HTML）")
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("statement", parents=[common, cfgopt], help="只显示题面")
    p.add_argument("id", help="题目 ID 或题号（Q6.4.6.1 / 6.4.6.1）")
    p.add_argument("--from-md", action="store_true", help="题面用 markdown 源码（默认用渲染后的 HTML）")
    p.set_defaults(func=cmd_statement)

    p = sub.add_parser("run", parents=[common, cfgopt], help="编译并在样例上运行（本地对拍）")
    p.add_argument("id", help="题目 ID / 题号，或 .cpp 文件路径")
    p.add_argument("-f", "--file", help="代码文件（默认取本地题目目录里的 .cpp）")
    p.add_argument("--std", default="c++17", help="编译标准，默认 c++17")
    p.add_argument("-t", "--time-limit", type=float, default=5.0, help="单组样例超时秒数，默认 5")
    p.add_argument("-k", "--keep", action="store_true", help="保留可执行文件")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("stress", parents=[common, cfgopt],
                       help="对拍：随机数据跑正解 vs 暴力，不一致就保存用例")
    p.add_argument("id", nargs="?", help="题目 ID / 题号，或直接给目录")
    p.add_argument("-s", "--solution", help="正解代码（默认 pick 就是 pull 那份）")
    p.add_argument("-b", "--brute", help="暴力代码（文件名含 brute/baoli/bf 可自动识别）")
    p.add_argument("-g", "--gen", help="数据生成器（文件名含 gen/maker/rand 可自动识别）")
    p.add_argument("-n", "--times", type=int, default=200, help="对拍轮数，默认 200")
    p.add_argument("--tl", type=float, default=5.0, help="单次限时秒数，默认 5")
    p.add_argument("--std", default="c++17", help="编译标准，默认 c++17")
    p.add_argument("--dir", help="失败用例保存目录（默认 <题目目录>/stress）")
    p.set_defaults(func=cmd_stress)

    p = sub.add_parser("paper", parents=[common, cfgopt], help="纸面题：get 备份答案图 / submit 上传 / restore 还原")
    p.add_argument("action", choices=["get", "submit", "restore"],
                   help="get=下载当前答案图片，submit=上传图片，restore=把备份图传回去")
    p.add_argument("id", help="题目 ID / 题号")
    p.add_argument("-f", "--file", help="submit 时的图片文件（png/jpg）")
    p.set_defaults(func=cmd_paper)

    p = sub.add_parser("export", parents=[common, cfgopt], help="把题面 markdown 导出成 PNG")
    p.add_argument("id", help="题目 ID / 题号，或 .md 文件路径")
    p.add_argument("-f", "--file", help="指定 markdown 文件")
    p.add_argument("-o", "--output", help="输出 PNG 路径（默认题目目录 statement.png）")
    p.add_argument("--width", type=int, default=1000, help="画布宽度，默认 1000")
    p.add_argument("--preview", action="store_true", help="导出后在终端画个粗略预览")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("friends", parents=[common, cfgopt], help="好友/关注列表（含群）")
    p.add_argument("-n", "--limit", type=int, default=30, help="显示条数，默认 30")
    p.add_argument("--all", action="store_true", help="连没有关注关系的也列出来")
    p.add_argument("--search", help="按账号/昵称/姓名/年级过滤")
    p.add_argument("--groups", action="store_true", help="只看群")
    p.set_defaults(func=cmd_friends)

    p = sub.add_parser("chat", parents=[common, cfgopt],
                       help="聊天：看消息 / 发消息 / 发求助 / 同意求助")
    p.add_argument("target", nargs="?", help="昵称 / 账号 / 群名 / id（不填则显示概览）")
    p.add_argument("-n", "--limit", type=int, default=20, help="拉取最近多少条，默认 20")
    p.add_argument("-m", "--message", help="发送的内容")
    p.add_argument("--ask", help="发求助：内容自动加【求助】前缀")
    p.add_argument("--accept", action="store_true", help="同意求助：发送【同意求助】")
    p.add_argument("--dry-run", action="store_true", help="只显示要发的内容，不提交")
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("contest", parents=[common, cfgopt], help="模测：列表 / 详情（题目 + 我的成绩）")
    p.add_argument("id", nargs="?", help="比赛编号或名称关键字（不给则列最近几场）")
    p.add_argument("-n", "--limit", type=int, default=15, help="列表显示场次，默认 15")
    p.set_defaults(func=cmd_contest)

    p = sub.add_parser("progress", parents=[common, cfgopt], help="进度排行（/ranklist，通过数/积分）")
    p.add_argument("-n", "--limit", type=int, default=30, help="显示前多少名，默认 30")
    p.add_argument("--me", action="store_true", help="只看自己那一行")
    p.set_defaults(func=cmd_progress)

    p = sub.add_parser("article", parents=[common, cfgopt], help="读帖子/帮助（article 124）")
    p.add_argument("id", help="文章编号或 .../article/<id> 的 URL")
    p.set_defaults(func=cmd_article)

    p = sub.add_parser("prints", parents=[common, cfgopt], help="提交打印队列（/prints/html）")
    p.add_argument("-n", "--limit", type=int, default=20, help="显示条数，默认 20")
    p.set_defaults(func=cmd_prints)

    p = sub.add_parser("plan", parents=[common, cfgopt],
                       help="计划：show 看某天 / add 写某天（today/明天/后天）")
    p.add_argument("action", nargs="?", default="show", choices=["show", "add", "edit", "home"])
    p.add_argument("date", nargs="?", help="today / 明天 / 后天 / 2026-10-28 / +3，默认今天")
    p.add_argument("-m", "--message", help="计划描述（add）")
    p.add_argument("-f", "--file", help="从文件读计划描述（add）")
    p.add_argument("-p", "--problems", help='计划题目，空格或 | 分隔，如 "71354 Q3.3.6.4"')
    p.add_argument("-r", "--result", help="完成情况")
    p.add_argument("-t", "--tweak", help="调整和补充")
    p.add_argument("--type", choices=["day", "week"], default="day", help="day 日计划（默认）/ week 周计划")
    p.add_argument("--user", type=int, help="用户 ID（默认自己）")
    p.add_argument("--no-titles", action="store_true", help="show 时不查题目名（省几次请求）")
    p.add_argument("-n", "--dry-run", action="store_true", help="只显示将要提交的内容")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("submissions", parents=[common, cfgopt],
                       help="提交记录查询：分页 + 题目/提交者/状态/语言/分数筛选")
    p.add_argument("--page", type=int, default=1, help="页码，默认 1")
    p.add_argument("--pages", type=int, default=1, help="连续看多少页，默认 1")
    p.add_argument("--problem", help="题目 ID，如 77425")
    p.add_argument("--submitter", help="提交者（学号或用户名）")
    p.add_argument("--status", help="状态，如 Accepted / Wrong Answer")
    p.add_argument("--language", help="语言，如 cpp17")
    p.add_argument("--min-score", type=int, dest="min_score", help="最低分")
    p.add_argument("--max-score", type=int, dest="max_score", help="最高分")
    p.set_defaults(func=cmd_submissions)

    p = sub.add_parser("review", parents=[common, cfgopt],
                       help="站点复盘（tag）：show / export 导出 md / new 空模板 / import 上传 md")
    p.add_argument("action", nargs="?", default="show",
                   choices=["show", "html", "export", "new", "import", "timeline", "set", "add"])
    p.add_argument("tag", help="tag_id，或直接粘 .../review/user_tag/edit?user_id=..&tag_id=.. 的 URL")
    p.add_argument("-i", "--index", type=int, help="timeline：第几行（从 1 开始）")
    p.add_argument("-o", "--output", help="export/new：保存的 md 路径（默认 reviews/<tag>.md）")
    p.add_argument("-f", "--file", help="import：要上传的 md 文件；export/new 也可用它指定路径")
    p.add_argument("--user", type=int, help="用户 ID（默认自己，URL 里有就用 URL 的）")
    p.add_argument("-t", "--time", help="时间线时间，如 14:30（默认当前时间）")
    p.add_argument("-p", "--plan", help="时间线：计划")
    p.add_argument("-a", "--achieve", help="时间线：完成情况")
    p.add_argument("-q", "--problem", help="set：题目名 / Sxx 编号 / 题目 id")
    p.add_argument("--rethink", help="set：数据、探索和反思")
    p.add_argument("--other", help="set：其他情况")
    p.add_argument("--guess", type=int, help="set：赛后估分")
    p.add_argument("--normal", help='set：常规检查，逗号分隔，如 "time=done,test=skip"')
    p.add_argument("-n", "--dry-run", action="store_true", help="只打印将要上传的 JSON")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("help", parents=[cfgopt], help="查看帮助（help 总览 / help <命令>）")
    p.add_argument("topic", nargs="*", help="命令名，如 help sftp")
    p.set_defaults(func=cmd_help, action="help")

    p = sub.add_parser("submission", parents=[common, cfgopt],
                       help="查看提交：状态走 /submissions/?id=，代码走 /submission/<id>")
    p.add_argument("sid", help="提交编号，也接受 /submissions?id=123 这种写法")
    p.add_argument("-c", "--code", action="store_true", help="显示代码（他人提交会先问是否继续）")
    p.add_argument("-s", "--save", help="把代码保存到文件或目录")
    p.add_argument("-y", "--yes", action="store_true", help="不再询问，直接尝试（他人提交/长代码）")
    p.add_argument("--max-chars", type=int, default=2000, help="超过多少字符先确认，默认 2000")
    p.add_argument("-r", "--revoke", action="store_true", help="作废这条提交（POST /submission/<id>/revoke）")
    p.add_argument("-d", "--delete", action="store_true", help="删除这条提交（POST /submission/<id>/deleted）")
    p.add_argument("--rejudge", action="store_true", help="重新评测（POST /submission/<id>/rejudge）")
    p.set_defaults(func=cmd_submission)

    p = sub.add_parser("sftp", parents=[common, cfgopt],
                       help="SFTP 存储（5307 端口）：login/ls/pwd/cd/lcd/get/put/mkdir/rm/rmdir")
    p.add_argument("action",
                   choices=["login", "ls", "pwd", "cd", "lcd", "lpwd", "get", "put", "mkdir", "rm", "rmdir"])
    p.add_argument("paths", nargs="*", help="get: 远程 [本地]；put: 本地 [远程]；其它: 相对当前远程目录的路径")
    p.add_argument("-u", "--user", help="SFTP 用户名（默认读 config 里的 sftp_user）")
    p.add_argument("-p", "--password", help="SFTP 密码（默认读 config，或交互输入）")
    p.set_defaults(func=cmd_sftp)

    p = sub.add_parser("template", parents=[cfgopt], help="查看/设置代码模板")
    p.add_argument("action", nargs="?", default="show", choices=["show", "set", "reset"],
                   help="show 查看（默认）/ set 设置模板文件 / reset 恢复内置")
    p.add_argument("file", nargs="?", help="set 时的模板文件路径")
    p.set_defaults(func=cmd_template)

    p = sub.add_parser("submit", parents=[common, cfgopt], help="提交代码")
    p.add_argument("id", help="题目 ID 或题号（Q6.4.6.1 / 6.4.6.1）")
    p.add_argument("-f", "--file", help="代码文件路径（默认取本地题目目录里的 .cpp）")
    p.add_argument("-l", "--lang", help="语言，如 cpp17 / cpp14 / cpp；默认用 config.json 的 language")
    p.add_argument("-n", "--dry-run", action="store_true", help="只显示将要提交的内容，不真正提交")
    p.add_argument("--no-wait", action="store_true", help="外站题提交后不等待结果，直接返回")
    p.add_argument("--no-watch", action="store_true", help="提交后不跟进评测状态（默认会跟进）")
    p.add_argument("--wait", type=float, default=180.0, help="等待结果/跟进的秒数，默认 180")
    p.add_argument("--via", choices=["vjudge", "7fa4"], default="vjudge",
                   help="外站题提交路径：vjudge=直连 vjudge（AC 才同步到 7FA4，默认），7fa4=走站点代理")
    p.add_argument("--no-push", action="store_true", help="外站题即使 AC 也不同步到 7FA4")
    p.add_argument("--share", action="store_true", help="外站题同步时公开代码（默认不公开）")
    p.add_argument("--vj-cookie", help="vjudge 的 Cookie（默认读 config.json 的 vj_cookie）")
    p.add_argument("--no-open", action="store_true", help="验证码图片不自动用看图工具打开")
    p.set_defaults(func=cmd_submit, interval=2.0)

    p = sub.add_parser("vjlogin", parents=[cfgopt], help="用 vjudge 账号密码登录并保存会话（免手抠 cookie）")
    p.add_argument("-u", "--user", help="vjudge 用户名")
    p.add_argument("-p", "--password", help="vjudge 密码（不填则安全输入）")
    p.set_defaults(func=cmd_vjlogin)

    p = sub.add_parser("vjcheck", parents=[cfgopt], help="检查 vj_cookie 是否有效")
    p.add_argument("--vj-cookie", help="临时指定 cookie")
    p.set_defaults(func=cmd_vjcheck)

    p = sub.add_parser("push", parents=[common, cfgopt], help="把 vjudge 上已 AC 的记录同步到 7FA4")
    p.add_argument("id", help="题目 ID / 题号")
    p.add_argument("--rid", required=True, help="vjudge 的 run 编号（提交时打印的那个）")
    p.add_argument("-f", "--file", help="代码文件（默认取本地题目目录里的 .cpp）")
    p.add_argument("--force", action="store_true", help="非 Accepted 也强制同步")
    p.add_argument("-l", "--lang", help="同步时上报的语言，默认用 config.json 的 language")
    p.add_argument("--vj-cookie", help="vjudge 的 Cookie")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("tasks", parents=[common, cfgopt], help="列出我的 vjudge 任务")
    p.add_argument("-n", "--limit", type=int, default=10, help="最多显示多少条，默认 10")
    p.set_defaults(func=cmd_tasks)

    p = sub.add_parser("task", parents=[common, cfgopt], help="查看/继续轮询 vjudge 任务")
    p.add_argument("task_id", help="任务编号（提交外站题时打印的 #编号）")
    p.add_argument("-p", "--problem", help="题目 ID / 题号，用于把结果写回本地目录")
    p.add_argument("--wait", type=float, default=180.0, help="等待秒数，默认 180")
    p.add_argument("--interval", type=float, default=2.0, help="轮询间隔秒数，默认 2")
    p.add_argument("--no-open", action="store_true", help="验证码图片不自动打开")
    p.set_defaults(func=cmd_task)

    p = sub.add_parser("config", parents=[cfgopt], help="查看/修改本地配置（host、vj_cookie、template、sessions）")
    p.add_argument("action", nargs="?", default="show", choices=["show", "get", "set", "unset"])
    p.add_argument("items", nargs="*", metavar="k=v", help="get 的键名；set 的 k=v；unset 的键名")
    p.add_argument("--raw", action="store_true", help="显示未打码的原文")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("update", parents=[cfgopt],
                       help="检查并更新自身（默认 http://localhost:9080/terminal.py）")
    p.add_argument("--check", action="store_true", help="只检查不应用")
    p.add_argument("--url", help="更新源地址（默认读 config 的 update_url）")
    p.add_argument("--timeout", type=float, default=8.0, help="下载超时秒数，默认 8")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("get", parents=[common, output, cfgopt], help="发送 GET 请求")
    p.add_argument("path", help="请求路径，如 /problems")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("post", parents=[common, output, cfgopt], help="发送 POST 表单请求")
    p.add_argument("path", help="请求路径")
    p.add_argument("data", nargs="*", metavar="k=v", help="表单字段，形如 a=1 b=2")
    p.set_defaults(func=cmd_post)

    p = sub.add_parser("raw", parents=[common, output, cfgopt], help="自定义方法请求")
    p.add_argument("method", help="HTTP 方法，如 PUT / DELETE")
    p.add_argument("path", help="请求路径")
    p.add_argument("data", nargs="*", metavar="k=v", help="表单字段")
    p.set_defaults(func=cmd_raw)

    p = sub.add_parser("shell", parents=[common, cfgopt], help="进入交互式终端")
    p.set_defaults(func=cmd_shell)

    return parser


def main(argv=None):
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    override = getattr(args, "config", None) or os.environ.get("7FA4_CONFIG")
    if override:
        set_config_path(override)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    if getattr(args, "action", None) != "update":
        auto_update_check()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n[已退出]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
