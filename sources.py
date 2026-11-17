# -*- coding: utf-8 -*-
"""数据源抓取模块。

每个 fetch_xxx 函数返回 list[Item]，解析不到任何内容时抛 RuntimeError，
由主流程记录为"该数据源失败"，统一进统计和报错邮件。
"""
from __future__ import annotations

import datetime
import html
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

RETRIES = int(os.environ.get("FETCH_RETRIES", "3"))
TIMEOUT = int(os.environ.get("FETCH_TIMEOUT", "20"))
BASE_DIR = Path(__file__).resolve().parent


@dataclass
class Item:
    source: str
    title: str
    url: str
    desc: str = ""
    heat: str = ""                      # 展示用热度文本，如 "⭐ 1,234（今日+56）"
    stars: Optional[int] = None         # 可排序/过滤的数值热度，None 表示无此指标
    extra: dict = field(default_factory=dict)


def gh_headers() -> dict:
    """GitHub API 请求头；Actions 里注入 GITHUB_TOKEN 可提升限流额度。"""
    h = {"Accept": "application/vnd.github+json"}
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if token:
        h["Authorization"] = "Bearer " + token
    return h


def http_request(url: str, method: str = "GET", **kwargs) -> requests.Response:
    """带超时重试的请求。"""
    headers = {**UA, **kwargs.pop("headers", {})}
    last_err = None
    for attempt in range(RETRIES):
        try:
            resp = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
            if resp.status_code == 200:
                return resp
            last_err = RuntimeError(f"HTTP {resp.status_code}")
        except requests.RequestException as e:
            last_err = e
        if attempt < RETRIES - 1:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"请求失败 {url}: {last_err}")


def _to_int(text) -> Optional[int]:
    m = re.search(r"[\d,]+", str(text))
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def clean_text(text) -> str:
    """清理空白/控制字符/HTML实体，压成单行。"""
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r"<[^>]+>", " ", text)
    text = "".join(ch for ch in text if ch == "\n" or ord(ch) >= 32)
    text = re.sub(r"[ \t\r\n\u00a0\u3000]+", " ", text)
    return text.strip()


def _soup(resp: requests.Response):
    return BeautifulSoup(resp.text, "html.parser")


# ---------------------------------------------------------------- GitHub Trending
def fetch_github_trending(limit: int) -> list:
    url = "https://github.com/trending?since=daily"
    soup = _soup(http_request(url))
    items = []
    for art in soup.select("article.Box-row"):
        a = art.select_one("h2 a")
        if not a:
            continue
        path = a.get("href", "").strip("/")
        parts = path.split("/")
        if len(parts) != 2:
            continue
        desc_el = art.select_one("p")
        lang_el = art.select_one('[itemprop="programmingLanguage"]')
        stars = None
        s_el = art.select_one('a[href$="/stargazers"]')
        if s_el:
            stars = _to_int(s_el.get_text())
        today = None
        m = re.search(r"([\d,]+)\s*(?:stars?\s+today|今日|本日)", art.get_text(" ", strip=True))
        if m:
            today = _to_int(m.group(1))
        heat = f"⭐ {stars:,}" if stars else ""
        if today:
            heat += f"（今日 +{today}）" if heat else f"今日 +{today}"
        items.append(Item(
            source="github",
            title=f"{parts[0]}/{parts[1]}",
            url=f"https://github.com/{path}",
            desc=clean_text(desc_el.get_text()) if desc_el else "",
            heat=heat,
            stars=stars,
            extra={"language": lang_el.get_text(strip=True) if lang_el else "", "today": today},
        ))
        if len(items) >= limit:
            break
    if not items:
        raise RuntimeError("GitHub Trending 解析结果为空，页面结构可能已变化")
    return items


# ---------------------------------------------------------------- GitHub 单HTML精选
def fetch_github_single_html(limit: int) -> list:
    """GitHub 官方搜索 API：定向搜索可套壳打包的纯 HTML 项目。

    分组查询：热门HTML / 单文件 / 播放器 / 黄历日历 / webview，
    全部标注【单HTML】，合并去重后按 star 排序。
    """
    since = (datetime.date.today() - datetime.timedelta(days=45)).isoformat()
    # stars 上限 5000：排除"主语言恰好是 HTML"的文档/awesome 巨仓；size 限小仓库
    queries = [
        f"language:html stars:20..5000 pushed:>{since} size:1..5000",
        "单文件 language:html stars:<5000",
        '"single html" language:html stars:10..5000',
        '"single file" html stars:10..5000',
        "音乐播放器 language:html stars:<5000",
        "播放器 language:html stars:10..5000",
        "黄历 language:html stars:<5000",
        "日历 language:html stars:10..5000",
        "webview language:html stars:10..5000",
    ]
    items, seen, errors = [], set(), 0
    for q in queries:
        try:
            data = http_request(
                "https://api.github.com/search/repositories",
                params={"q": q, "sort": "stars", "order": "desc", "per_page": min(limit, 30)},
                headers=gh_headers(),
            ).json()
        except RuntimeError:
            errors += 1
            time.sleep(3)
            continue
        for r in data.get("items") or []:
            full = r.get("full_name") or ""
            if not full or full in seen:
                continue
            seen.add(full)
            stars = r.get("stargazers_count") or 0
            items.append(Item(
                source="ghhtml",
                title=full,
                url=r.get("html_url") or f"https://github.com/{full}",
                desc=clean_text(r.get("description") or ""),
                heat=f"⭐ {stars:,}",
                stars=stars,
                extra={"language": "HTML", "single_html": True},
            ))
        time.sleep(3)  # 搜索接口限流严格，主动放慢
    if not items:
        if errors:
            raise RuntimeError(f"GitHub 搜索 API 查询全部失败（{errors} 组，限流或网络）")
        raise RuntimeError("GitHub 单HTML精选搜索返回为空")
    items.sort(key=lambda it: -(it.stars or 0))
    return items[:limit]


# ---------------------------------------------------------------- 关注名单
def fetch_watch(limit: int) -> list:
    """关注名单：抓取 config.json watch_repos / watch_users 近 3 天的新版本与新提交。

    未配置名单时返回空列表（不算失败）。所有条目带 watch_pinned 标记，主流程置顶。
    """
    try:
        cfg = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cfg = {}
    repos = [str(x).strip() for x in cfg.get("watch_repos", []) if str(x).strip()]
    users = [str(x).strip() for x in cfg.get("watch_users", []) if str(x).strip()]
    if not repos and not users:
        return []

    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    items, seen = [], set()

    def add(it: Item):
        key = it.url.lower()
        if it.url and key not in seen:
            seen.add(key)
            items.append(it)

    for repo in repos[:20]:
        try:
            rels = http_request(
                f"https://api.github.com/repos/{repo}/releases?per_page=5",
                headers=gh_headers()).json()
        except RuntimeError:
            rels = []
        for r in rels if isinstance(rels, list) else []:
            if r.get("draft") or not r.get("published_at") or r["published_at"] < since:
                continue
            add(Item(
                source="watch",
                title=f"{repo} 发布 {r.get('tag_name', '')}".strip(),
                url=r.get("html_url") or f"https://github.com/{repo}/releases",
                desc=clean_text(r.get("body") or "")[:150],
                heat="👀 关注更新 · 新版本",
                extra={"watch_pinned": True},
            ))
        try:
            commits = http_request(
                f"https://api.github.com/repos/{repo}/commits?since={since}&per_page=10",
                headers=gh_headers()).json()
        except RuntimeError:
            commits = []
        for c in commits if isinstance(commits, list) else []:
            info = c.get("commit") or {}
            msg = clean_text((info.get("message") or "").splitlines()[0]) if info.get("message") else ""
            url = c.get("html_url") or ""
            if not msg or not url:
                continue
            author = ((info.get("author") or {}).get("name")
                      or (c.get("author") or {}).get("login") or "")
            add(Item(
                source="watch",
                title=f"{repo}: {msg}",
                url=url,
                desc=f"提交者 {author}",
                heat="👀 关注更新",
                extra={"watch_pinned": True},
            ))
        time.sleep(1)

    for user in users[:20]:
        try:
            events = http_request(
                f"https://api.github.com/users/{user}/events/public?per_page=60",
                headers=gh_headers()).json()
        except RuntimeError:
            events = []
        for ev in events if isinstance(events, list) else []:
            if (ev.get("created_at") or "") < since:
                continue
            et = ev.get("type")
            repo_name = (ev.get("repo") or {}).get("name") or ""
            payload = ev.get("payload") or {}
            if et == "PushEvent" and repo_name:
                cs = payload.get("commits") or []
                head = payload.get("head") or ""
                first = clean_text((cs[0].get("message") or "").splitlines()[0]) if cs else ""
                url = (f"https://github.com/{repo_name}/commit/{head}" if head
                       else f"https://github.com/{repo_name}")
                add(Item(
                    source="watch",
                    title=f"{user} 更新 {repo_name}（{len(cs)} 个提交）" + (f"：{first}" if first else ""),
                    url=url,
                    desc="关注的人推送了新代码",
                    heat="👀 关注更新",
                    extra={"watch_pinned": True},
                ))
            elif et == "ReleaseEvent" and repo_name:
                r = payload.get("release") or {}
                if not r.get("draft"):
                    add(Item(
                        source="watch",
                        title=f"{user} 发布 {repo_name} {r.get('tag_name', '')}".strip(),
                        url=r.get("html_url") or f"https://github.com/{repo_name}/releases",
                        desc=clean_text(r.get("body") or "")[:150],
                        heat="👀 关注更新 · 新版本",
                        extra={"watch_pinned": True},
                    ))
        time.sleep(1)

    return items[:limit]


# ---------------------------------------------------------------- Gitee
def fetch_gitee_hot(limit: int) -> list:
    """Gitee 官方 Atom 订阅源（推荐项目/热榜），无网页反爬限制。"""
    import xml.etree.ElementTree as ET
    resp = http_request("https://gitee.com/explore.atom")
    root = ET.fromstring(resp.content)
    ns = {"a": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/"}
    items = []
    for e in root.findall("a:entry", ns):
        link_el = e.find("a:link", ns)
        url = link_el.get("href", "") if link_el is not None else ""
        title = clean_text(e.findtext("a:title", default="", namespaces=ns))
        if not url or not title:
            continue
        stars = _to_int(e.findtext("a:stars_count", default="", namespaces=ns))
        forks = _to_int(e.findtext("a:forked_count", default="", namespaces=ns))
        lang = e.findtext("a:language", default="", namespaces=ns) or ""
        cat = ""
        cat_el = e.find("a:category/a:name", ns)
        if cat_el is not None:
            cat = clean_text(cat_el.text or "")
        heat = f"⭐ {stars:,}" if stars else ""
        if forks:
            heat += f" · fork {forks:,}"
        items.append(Item(
            source="gitee",
            title=title,
            url=url,
            desc=clean_text(e.findtext("a:summary", default="", namespaces=ns)),
            heat=heat,
            stars=stars,
            extra={"language": lang, "gitee_category": cat},
        ))
        if len(items) >= limit:
            break
    if not items:
        raise RuntimeError("Gitee Atom 解析结果为空，接口可能已调整")
    return items


# ---------------------------------------------------------------- HuggingFace
def fetch_huggingface(limit: int) -> list:
    half = max(1, limit // 2)
    items = []

    models = http_request(
        "https://huggingface.co/api/models",
        params={"sort": "trendingScore", "direction": -1, "limit": half},
    ).json()
    for m in models:
        mid = m.get("modelId") or m.get("id")
        if not mid:
            continue
        pipe = m.get("pipeline_tag") or ""
        tags_txt = " ".join(str(t) for t in (m.get("tags") or [])[:8])
        likes = m.get("likes") or 0
        downloads = m.get("downloads") or 0
        items.append(Item(
            source="huggingface",
            title=mid,
            url=f"https://huggingface.co/{mid}",
            desc=clean_text(f"{pipe} {tags_txt}".strip()),
            heat=f"👍 {likes:,} · ⬇ {downloads:,}",
            stars=likes,
            extra={"kind": "model"},
        ))

    spaces = http_request(
        "https://huggingface.co/api/spaces",
        params={"sort": "trendingScore", "direction": -1, "limit": half},
    ).json()
    for s in spaces:
        sid = s.get("id")
        if not sid:
            continue
        likes = s.get("likes") or 0
        short_desc = (s.get("cardData") or {}).get("short_description", "")
        sdk = s.get("sdk") or ""
        default_desc = f"在线Demo（{sdk}）" if sdk else "在线Demo"
        items.append(Item(
            source="huggingface",
            title=sid,
            url=f"https://huggingface.co/spaces/{sid}",
            desc=clean_text(short_desc or default_desc),
            heat=f"👍 {likes:,}",
            stars=likes,
            extra={"kind": "space", "sdk": sdk},
        ))

    if not items:
        raise RuntimeError("HuggingFace API 返回为空")
    return items[:limit]


# ---------------------------------------------------------------- ModelScope
def _find_item_list(obj, keys):
    """在任意嵌套 JSON 里找到第一个包含指定字段的 dict 列表。"""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj) and any(k in obj[0] for k in keys):
            return obj
        for x in obj:
            got = _find_item_list(x, keys)
            if got:
                return got
    elif isinstance(obj, dict):
        for v in obj.values():
            got = _find_item_list(v, keys)
            if got:
                return got
    return None


def fetch_modelscope(limit: int) -> list:
    resp = http_request(
        "https://www.modelscope.cn/api/v1/dolphin/models",
        method="PUT",
        json={
            "PageSize": limit, "PageNumber": 1, "SortBy": "StarsCount",
            "Target": "", "Criterion": [], "SingleCriterion": [],
        },
        headers={
            "Content-Type": "application/json",
            "Origin": "https://www.modelscope.cn",
            "Referer": "https://www.modelscope.cn/models",
        },
    )
    payload = resp.json()
    raw = ((payload.get("Data") or {}).get("Model") or {}).get("Models")
    if not raw:
        raw = _find_item_list(payload, ("Name", "Downloads", "StarsCount")) or []
    items = []
    for m in raw[:limit]:
        name = m.get("Name") or m.get("ChineseName")
        if not name:
            continue
        path = m.get("Path") or m.get("Namespace") or ""
        stars = _to_int(m.get("Stars")) or 0
        downloads = _to_int(m.get("Downloads")) or 0
        url = f"https://www.modelscope.cn/models/{path}/{name}" if path else \
            "https://www.modelscope.cn/models"
        desc = clean_text(m.get("Description") or "")
        if not desc:
            tasks = m.get("Tasks") or []
            task_name = clean_text((tasks[0] or {}).get("ChineseName")
                                   or (tasks[0] or {}).get("Name") or "") if tasks else ""
            desc = " · ".join(x for x in (task_name, clean_text(m.get("ChineseName") or "")) if x)
        items.append(Item(
            source="modelscope",
            title=f"{path}/{name}" if path else name,
            url=url,
            desc=desc,
            heat=f"⭐ {stars:,} · ⬇ {downloads:,}",
            stars=stars,
        ))
    if not items:
        raise RuntimeError("ModelScope API 解析结果为空，接口可能已调整")
    return items


# ---------------------------------------------------------------- CodePen
def fetch_codepen(limit: int) -> list:
    soup = _soup(http_request("https://codepen.io/trending"))
    items, seen = [], set()
    for art in soup.select("article"):
        a = art.select_one('a[href*="/pen/"], a[href*="/details/"]')
        if not a:
            continue
        href = a.get("href", "")
        m = re.search(r"/(?:pen|details|full)/([A-Za-z0-9]+)", href)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        title_el = art.select_one('[data-chameleon="title"]')
        like_el = art.select_one('[data-chameleon="like-count"]')
        author_el = art.select_one('[data-chameleon="author"]')
        likes = _to_int(like_el.get_text()) if like_el else None
        title = clean_text(title_el.get_text()) if title_el else clean_text(a.get_text()) or "未命名 Pen"
        items.append(Item(
            source="codepen",
            title=title,
            url=f"https://codepen.io/pen/{m.group(1)}",
            desc=clean_text(f"by {author_el.get_text()}" if author_el else "前端在线 Demo"),
            heat=f"❤ {likes:,}" if likes else "",
            stars=likes,
            extra={"single_html": True},
        ))
        if len(items) >= limit:
            break
    if not items:
        raise RuntimeError("CodePen 热门解析结果为空，页面结构可能已变化")
    return items


# ---------------------------------------------------------------- 掘金
def fetch_juejin(limit: int) -> list:
    resp = http_request(
        "https://api.juejin.cn/content_api/v1/content/article_rank",
        params={"category_id": 1, "type": "hot"},
    )
    data = (resp.json() or {}).get("data") or []
    items = []
    for entry in data[:limit]:
        content = entry.get("content") or {}
        cid = content.get("content_id")
        title = clean_text(content.get("title") or "")
        if not cid or not title:
            continue
        counter = entry.get("content_counter") or {}
        hot = _to_int(counter.get("hot_rank_score")) or _to_int(entry.get("hot_rank_score"))
        items.append(Item(
            source="juejin",
            title=title,
            url=f"https://juejin.cn/post/{cid}",
            desc=clean_text(content.get("abstract") or ""),
            heat=f"🔥 {hot:,}" if hot else "",
            stars=hot,
        ))
    if not items:
        raise RuntimeError("掘金热榜 API 返回为空")
    return items


# ---------------------------------------------------------------- V2EX
def fetch_v2ex(limit: int) -> list:
    data = http_request("https://www.v2ex.com/api/topics/hot.json").json()
    items = []
    for t in (data or [])[:limit]:
        title = clean_text(t.get("title") or "")
        url = t.get("url") or ""
        if not title or not url:
            continue
        node = (t.get("node") or {}).get("title") or ""
        replies = t.get("replies") or 0
        items.append(Item(
            source="v2ex",
            title=title,
            url=url,
            desc=clean_text(t.get("content") or "")[:120],
            heat=f"💬 {replies:,}" + (f" · {node}" if node else ""),
            stars=replies,
        ))
    if not items:
        raise RuntimeError("V2EX API 返回为空（可能需要代理）")
    return items


SOURCE_REGISTRY = [
    ("watch", "👀 关注更新", fetch_watch),
    ("github", "GitHub Trending", fetch_github_trending),
    ("ghhtml", "GitHub 单HTML精选", fetch_github_single_html),
    ("gitee", "Gitee 热榜", fetch_gitee_hot),
    ("huggingface", "HuggingFace 模型+Space", fetch_huggingface),
    ("modelscope", "魔搭 ModelScope", fetch_modelscope),
    ("codepen", "CodePen 热门", fetch_codepen),
    ("juejin", "掘金热榜", fetch_juejin),
    ("v2ex", "V2EX 热议", fetch_v2ex),
]

