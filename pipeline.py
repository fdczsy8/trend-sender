# -*- coding: utf-8 -*-
"""配置加载、关键词过滤、分类打标、去重缓存。"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("DIGEST_CONFIG", BASE_DIR / "config.json"))
HISTORY_PATH = Path(os.environ.get("HISTORY_FILE", BASE_DIR / "cache" / "history.json"))


def load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    # 环境变量覆盖（供 GitHub Actions Inputs/Vars 使用）
    if os.environ.get("MODE"):
        cfg["mode"] = os.environ["MODE"].strip().lower()
    if os.environ.get("MIN_STARS"):
        try:
            v = int(os.environ["MIN_STARS"])
            for k in cfg.get("min_stars", {}):
                cfg["min_stars"][k] = v
        except ValueError:
            pass
    if os.environ.get("DEDUP_DAYS"):
        try:
            cfg["dedup_days"] = int(os.environ["DEDUP_DAYS"])
        except ValueError:
            pass
    if cfg.get("mode") not in ("full", "compact"):
        cfg["mode"] = "full"
    return cfg


def source_enabled(key: str, cfg: dict) -> bool:
    """开关优先级：环境变量 SRC_<KEY> > config.json enabled_sources。"""
    env = os.environ.get(f"SRC_{key.upper()}")
    if env is not None and env.strip() != "":
        return env.strip().lower() in ("1", "true", "on", "yes")
    return bool(cfg.get("enabled_sources", {}).get(key, True))


def item_text(item) -> str:
    return f"{item.title} {item.desc} {' '.join(str(v) for v in item.extra.values() if isinstance(v, str))}".lower()


def match_keywords(text: str, keywords) -> list:
    return [k for k in keywords if k.lower() in text]


def classify(item, cfg: dict) -> list:
    text = item_text(item)
    tags = []
    for name, kws in cfg.get("categories", {}).items():
        if match_keywords(text, kws):
            tags.append(name)
    return tags


def is_single_html(item, cfg: dict) -> bool:
    if item.extra.get("single_html"):
        return True
    if item.source == "codepen" and cfg.get("mark_codepen_as_single_html", True):
        return True
    if (item.source in ("github", "gitee")
            and cfg.get("mark_html_language_repos", True)
            and item.extra.get("language", "").upper() == "HTML"):
        return True
    return bool(match_keywords(item_text(item), cfg.get("single_html_keywords", [])))


def decorate(items: list, cfg: dict):
    """黑名单丢弃、白名单置顶标记、单HTML标记、分类打标。

    返回 (kept_items, dropped_blacklist, dropped_stars)
    """
    kept, drop_bl, drop_star = [], 0, 0
    min_stars = cfg.get("min_stars", {})
    for it in items:
        text = item_text(it)
        if match_keywords(text, cfg.get("blacklist", [])):
            drop_bl += 1
            continue
        hits = match_keywords(text, cfg.get("whitelist", []))
        it.extra["whitelist_hits"] = hits
        it.extra["pinned"] = bool(hits) or bool(it.extra.get("watch_pinned"))
        it.extra["single_html"] = is_single_html(it, cfg)
        it.extra["categories"] = classify(it, cfg)
        threshold = min_stars.get(it.source, 0) or 0
        if threshold and it.stars is not None and it.stars < threshold and not it.extra["pinned"]:
            # 命中白名单的项目无视 star 阈值，避免漏掉小众好项目
            drop_star += 1
            continue
        kept.append(it)
    return kept, drop_bl, drop_star


# ---------------------------------------------------------------- 去重缓存
def load_history() -> dict:
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"items": {}}


def _norm_title(title: str) -> str:
    return "".join(str(title).lower().split())


def dedup(items: list, history: dict, dedup_days: int):
    """过滤掉 dedup_days 天内已推送过的内容。返回 (fresh, dup_count)。"""
    today = datetime.date.today()
    fresh, dup = [], 0
    stored = history.get("items", {})
    for it in items:
        url_key = it.url.lower().rstrip("/")
        title_key = "title:" + _norm_title(it.title)
        pushed_at = None
        for k in (url_key, title_key):
            entry = stored.get(k)
            if entry and entry.get("date"):
                try:
                    d = datetime.date.fromisoformat(entry["date"])
                except ValueError:
                    continue
                if (today - d).days < dedup_days:
                    pushed_at = d
                    break
        if pushed_at:
            dup += 1
            continue
        fresh.append(it)
    return fresh, dup


def record_pushed(items: list, history: dict, keep_days: int):
    """推送成功后写入缓存，并清理过期记录，返回 history 对象。"""
    today = datetime.date.today()
    stored = history.setdefault("items", {})
    for it in items:
        date_str = today.isoformat()
        stored[it.url.lower().rstrip("/")] = {"date": date_str, "title": it.title}
        stored["title:" + _norm_title(it.title)] = {"date": date_str, "title": it.title}
    cutoff = today - datetime.timedelta(days=keep_days)
    history["items"] = {
        k: v for k, v in stored.items()
        if v.get("date") and datetime.date.fromisoformat(v["date"]) >= cutoff
    }
    return history


def save_history(history: dict):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 排序
def sort_items(items: list) -> list:
    def key(it):
        pinned_rank = 0 if (it.extra.get("pinned") or it.extra.get("single_html")) else 1
        stars = it.stars if it.stars is not None else -1
        return (pinned_rank, -stars)
    return sorted(items, key=key)
