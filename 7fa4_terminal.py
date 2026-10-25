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
    submit    提交代码（外站题直连 vjudge，AC 才把记录同步到 7FA4；
              --via 7fa4 时会把验证码图片在终端画出来并保存/打开）
    push      把 vjudge 上已 AC 的记录同步到 7FA4（不重复提交）
    vjlogin   用 vjudge 账号密码登录并保存会话（替代手抠 JSESSIONID）
    vjcheck   检查 vj_cookie 是否还有效
    task      继续查看某个 vjudge 任务（--via 7fa4 代理提交时会给任务号）
    tasks     列出 7FA4 上的 vjudge 任务
    run       编译并在样例上运行（本地对拍，Windows / Linux 通用）
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

    return 0;
}
"""


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


def render_template(text, values):
    """支持 {{id}} {{title}} {{short}} {{url}} {{date}} 占位符。"""
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
        # 旧版本的独立会话文件（启动时自动迁移进 config.json）
        self.legacy_session_file = os.path.join(BASE_DIR, f"session_{self.host}_{self.port}.json")
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (7fa4-terminal)",
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
        })

    # ---------- 会话 ----------
    def load_session(self):
        entry = (load_config().get("sessions") or {}).get(self.session_key)
        if isinstance(entry, dict) and entry.get("cookies"):
            self.s.cookies.update(entry["cookies"])
            self.username = entry.get("username")
            return True

        if os.path.exists(self.legacy_session_file):
            try:
                with open(self.legacy_session_file, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {}
            if data.get("cookies"):
                self.s.cookies.update(data["cookies"])
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
        sessions[self.session_key] = {
            "username": self.username,
            "cookies": requests.utils.dict_from_cookiejar(self.s.cookies),
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
    def request(self, method, path, data=None, params=None, files=None, json=None, allow_redirects=True):
        url = path if path.startswith("http") else self.base + path
        try:
            r = self.s.request(method.upper(), url, data=data, params=params, files=files, json=json,
                               timeout=self.timeout, allow_redirects=allow_redirects)
        except requests.RequestException as exc:
            raise RuntimeError(f"请求失败: {type(exc).__name__}: {exc}") from exc
        self.save_session()
        return r

    def get(self, path, **kw):
        return self.request("get", path, **kw)

    def post(self, path, data=None, **kw):
        return self.request("post", path, data=data, **kw)

    # ---------- 登录 ----------
    def login(self, username, password):
        digest = hashlib.md5((password + PASSWORD_SALT).encode()).hexdigest()
        r = self.post("/api/login", data={"username": username, "password": digest})
        try:
            data = r.json()
        except ValueError:
            return False, f"登录响应不是 JSON（HTTP {r.status_code}）：{r.text[:120]}"
        code = data.get("error_code")
        if code in (None, 1, "1"):
            self.username = username
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
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html or "")
    # 图片保留成 markdown，方便后面下载成本地文件
    text = re.sub(r"(?is)<img[^>]*src=\"([^\"]+)\"[^>]*>",
                  lambda m: f"\n![图片]({htmllib.unescape(m.group(1))})\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h[1-6]|tr|li|pre)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = htmllib.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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
def cmd_login(args):
    client = make_client(args)
    client.load_session()
    user = args.user or input("用户名: ")
    pwd = args.password if args.password is not None else getpass.getpass("密码: ")
    ok, msg = client.login(user, pwd)
    print(("[OK] " if ok else "[失败] ") + msg)
    if not ok:
        return 1
    logged, _ = client.whoami()
    print(f"[校验] 会话{'有效' if logged else '无效（可能被风控/需要验证码）'}")
    return 0


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
        markdown = client.problem_markdown(pid)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    if label == str(pid):
        label = meta["title"]

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
        })
        write_text(cpp_path, content)
        created = True
        tpl_desc = tpl_file or "内置模板"
    else:
        tpl_desc = ""
    # 5) 元信息
    meta_out = dict(meta)
    meta_out.update({"no": no, "short": short, "cpp": os.path.relpath(cpp_path),
                     "folder": os.path.relpath(folder)})
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
    print(f"[题面] statement.md")
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
        folder = find_problem_dir(pid)
        if folder:
            cpps = [f for f in sorted(os.listdir(folder)) if f.endswith((".cpp", ".cc", ".cxx"))]
            if cpps:
                source = os.path.join(folder, cpps[0])
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
        return 0
    if "json" in ctype:
        try:
            data = r.json()
        except ValueError:
            data = {}
        code_ = data.get("error_code")
        if code_ in (None, 1, "1"):
            print(f"[结果] 提交成功 {data if data else ''}")
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
        folder = find_problem_dir(pid)
        if folder:
            cpps = [f for f in sorted(os.listdir(folder)) if f.lower().endswith((".cpp", ".cc", ".cxx"))]
            if cpps:
                source = os.path.join(folder, cpps[0])
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
        for ext in (".out", ".ans", ".exp", ".answer"):
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
            cpps = [f for f in sorted(os.listdir(folder)) if f.lower().endswith((".cpp", ".cc", ".cxx"))]
            if cpps:
                source = os.path.join(folder, cpps[0])
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
    passed = 0
    print(f"[样例] 共 {len(cases)} 组")
    for idx, (name, in_path, expected) in enumerate(cases, 1):
        with open(in_path, "rb") as f:
            in_data = f.read()
        start = time.perf_counter()
        try:
            p = subprocess.run([exe_path], input=in_data, capture_output=True, timeout=args.time_limit)
            elapsed = time.perf_counter() - start
            out = p.stdout.decode("utf-8", "replace")
            err = p.stderr.decode("utf-8", "replace")
            rc = p.returncode
        except subprocess.TimeoutExpired:
            print(f"  [{idx}/{len(cases)}] {name}  TLE  >{args.time_limit:g}s")
            continue

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

    print(f"[结果] 通过 {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


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
    print("可用占位符：{{id}} {{no}} {{title}} {{short}} {{url}} {{date}}")
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

    p = sub.add_parser("login", parents=[common, cfgopt], help="登录并保存会话")
    p.add_argument("-u", "--user", help="用户名（不填则提示输入）")
    p.add_argument("-p", "--password", help="密码（不填则安全输入）")
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
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("statement", parents=[common, cfgopt], help="只显示题面")
    p.add_argument("id", help="题目 ID 或题号（Q6.4.6.1 / 6.4.6.1）")
    p.set_defaults(func=cmd_statement)

    p = sub.add_parser("run", parents=[common, cfgopt], help="编译并在样例上运行（本地对拍）")
    p.add_argument("id", help="题目 ID / 题号，或 .cpp 文件路径")
    p.add_argument("-f", "--file", help="代码文件（默认取本地题目目录里的 .cpp）")
    p.add_argument("--std", default="c++17", help="编译标准，默认 c++17")
    p.add_argument("-t", "--time-limit", type=float, default=5.0, help="单组样例超时秒数，默认 5")
    p.add_argument("-k", "--keep", action="store_true", help="保留可执行文件")
    p.set_defaults(func=cmd_run)

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
    p.add_argument("--wait", type=float, default=180.0, help="外站题等待结果的秒数，默认 180")
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
