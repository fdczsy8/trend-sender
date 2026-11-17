# -*- coding: utf-8 -*-
"""生成 HTML 邮件正文与 Markdown 清单。"""
from __future__ import annotations

import datetime
import html as html_mod

TAG_COLORS = {
    "前端": "#2f6fed",
    "AI模型": "#8b3ff0",
    "安卓工具": "#18a058",
    "在线Demo": "#e07b00",
    "教程": "#c2418f",
}

SECTION_ORDER = ["watch", "github", "ghhtml", "gitee", "huggingface", "modelscope", "codepen", "juejin", "v2ex"]


def esc(text: str) -> str:
    return html_mod.escape(str(text or ""), quote=True)


def cut(text: str, max_len: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def split_sections(items: list, cfg: dict):
    """置顶区 + 各数据源分区。返回 [(标题, [Item,...]), ...]（仅非空）。"""
    sections = []
    pinned = [it for it in items if it.extra.get("pinned") or it.extra.get("single_html")]
    rest = [it for it in items if it not in pinned]
    if pinned:
        sections.append(("⭐ 置顶关注", pinned))
    limit = cfg.get("max_items_per_section", 25)
    for src in SECTION_ORDER:
        group = [it for it in rest if it.source == src][:limit]
        name = next((n for k, n, _ in _registry() if k == src), src)
        if group:
            sections.append((name, group))
    return sections


def _registry():
    import sources
    return sources.SOURCE_REGISTRY


# ---------------------------------------------------------------- HTML
def _tag_pill(tag: str) -> str:
    color = TAG_COLORS.get(tag, "#666")
    return (f'<span style="display:inline-block;background:{color};color:#fff;'
            f'font-size:11px;line-height:16px;padding:1px 7px;border-radius:9px;'
            f'margin-right:4px;">{esc(tag)}</span>')


def _prefix(it) -> str:
    prefix = ""
    if it.extra.get("pinned"):
        prefix += "⭐ "
    if it.extra.get("single_html"):
        prefix += "【单HTML】"
    return prefix


def _stats_html(stats: dict) -> str:
    fetched = stats.get("total_fetched", stats.get("total", 0))
    total = stats.get("total", 0)
    hits = stats.get("whitelist_hits", 0)
    single = stats.get("single_html", 0)
    cards = ""
    for label, value in (("抓取总条数", fetched), ("去重后推送", total),
                         ("命中关注词", hits), ("单HTML项目", single)):
        cards += (f'<td style="padding:6px 4px;text-align:center;">'
                  f'<div style="font-size:20px;font-weight:bold;color:#1a56db;">{value}</div>'
                  f'<div style="font-size:12px;color:#888;">{label}</div></td>')
    rows = ""
    for name, info in stats.get("sources", {}).items():
        if info.get("ok"):
            badge = f'<span style="color:#18a058;">成功</span>（{info.get("fetched", 0)} 条）'
        else:
            badge = f'<span style="color:#d03050;">失败</span>：{esc(cut(info.get("error", ""), 80))}'
        rows += (f'<tr><td style="padding:2px 10px 2px 0;color:#555;">{esc(name)}</td>'
                 f'<td>{badge}</td></tr>')
    return (
        '<table role="presentation" width="100%" style="border-collapse:collapse;'
        'background:#f4f7fd;border-radius:8px;margin:10px 0;">'
        f'<tr>{cards}</tr></table>'
        f'<table role="presentation" style="font-size:12px;color:#666;border-collapse:collapse;margin-bottom:6px;">{rows}</table>'
    )


def render_html(sections, stats: dict, mode: str, date_str: str) -> str:
    max_len = stats.get("desc_max_length", 160)
    body = [
        '<div style="max-width:680px;margin:0 auto;font-family:-apple-system,'
        '\'Segoe UI\',\'Microsoft YaHei\',sans-serif;color:#222;">',
        '<div style="background:linear-gradient(90deg,#1a56db,#6d28d9);color:#fff;'
        'padding:18px 20px;border-radius:10px 10px 0 0;">',
        f'<div style="font-size:20px;font-weight:bold;">开发者资讯日报</div>'
        f'<div style="font-size:12px;opacity:.85;margin-top:4px;">{esc(date_str)} · '
        f'{"完整版" if mode == "full" else "精简版"}</div></div>',
        '<div style="border:1px solid #e5e7eb;border-top:0;border-radius:0 0 10px 10px;padding:14px 18px;">',
        _stats_html(stats),
    ]
    for name, items in sections:
        body.append(
            f'<div style="font-size:15px;font-weight:bold;color:#1a56db;'
            f'border-left:4px solid #1a56db;padding-left:8px;margin:18px 0 8px;">'
            f'{esc(name)}（{len(items)}）</div>')
        if mode == "compact":
            lines = []
            for it in items:
                lines.append(f'<a href="{esc(it.url)}" style="color:#1a56db;text-decoration:none;">'
                             f'{esc(_prefix(it) + cut(it.title, 60))}</a>')
            body.append('<div style="font-size:13px;line-height:2;">' + " ｜ ".join(lines) + "</div>")
            continue
        for it in items:
            pills = "".join(_tag_pill(t) for t in it.extra.get("categories", []))
            star_badge = ""
            if "单HTML" in it.title or it.extra.get("single_html"):
                star_badge = ('<span style="display:inline-block;background:#b45309;color:#fff;'
                              'font-size:11px;line-height:16px;padding:1px 7px;border-radius:9px;'
                              'margin-right:4px;">可直接网页打包</span>')
            desc = cut(it.desc, max_len)
            desc_html = f'<div style="font-size:12px;color:#666;margin-top:3px;">{esc(desc)}</div>' if desc else ""
            heat_html = (f'<span style="font-size:11px;color:#e07b00;white-space:nowrap;">'
                         f'{esc(it.heat)}</span>' if it.heat else "")
            body.append(
                '<div style="padding:8px 10px;border-bottom:1px dashed #eee;">'
                f'<div style="font-size:14px;font-weight:600;">{_prefix(it) and esc(_prefix(it))}'
                f'<a href="{esc(it.url)}" style="color:#1a2b5e;text-decoration:none;">'
                f'{esc(cut(it.title, 90))}</a> {pills}{star_badge}</div>'
                f'{desc_html}<div style="margin-top:2px;">{heat_html}</div></div>')
    body.append(
        '<div style="font-size:11px;color:#aaa;margin-top:16px;text-align:center;">'
        '由 GitHub Actions 自动生成 · 去重周期内不重复推送</div></div></div>')
    return "".join(body)


# ---------------------------------------------------------------- Markdown
def render_markdown(sections, stats: dict, mode: str, date_str: str) -> str:
    lines = [f"# 开发者资讯日报 {date_str}", ""]
    lines.append(f"- 本次抓取总条数：**{stats.get('total_fetched', stats.get('total', 0))}**（去重后推送 **{stats.get('total', 0)}**）")
    lines.append(f"- 命中关注关键词：**{stats.get('whitelist_hits', 0)}**")
    lines.append(f"- 【单HTML】项目：**{stats.get('single_html', 0)}**")
    ok = sum(1 for i in stats.get("sources", {}).values() if i.get("ok"))
    fail = [n for n, i in stats.get("sources", {}).items() if not i.get("ok")]
    lines.append(f"- 数据源：{ok}/{len(stats.get('sources', {}))} 成功"
                 + (f"（失败：{', '.join(fail)}）" if fail else ""))
    lines.append("")
    max_len = stats.get("desc_max_length", 160)
    for name, items in sections:
        lines.append(f"## {name}（{len(items)}）")
        lines.append("")
        for it in items:
            marks = ""
            if it.extra.get("pinned"):
                marks += "⭐ "
            if it.extra.get("single_html"):
                marks += "【单HTML】"
            tags = "".join(f" `{t}`" for t in it.extra.get("categories", []))
            heat = f" — {it.heat}" if it.heat else ""
            lines.append(f"- {marks}[{cut(it.title, 100)}]({it.url}){标签}{heat}")
            if mode == "full" and it.desc:
                lines.append(f"  - {cut(it.desc, max_len)}")
        lines.append("")
    return "\n".join(lines)


def build_subject(stats: dict, date_str: str) -> str:
    parts = [f"【资讯日报】{date_str}"]
    parts.append(f"{stats.get('total', 0)}条")
    if stats.get("whitelist_hits"):
        parts.append(f"⭐{stats['whitelist_hits']}")
    if stats.get("single_html"):
        parts.append(f"单HTML×{stats['single_html']}")
    fails = [n for n, i in stats.get("sources", {}).items() if not i.get("ok")]
    if fails:
        parts.append(f"⚠{len(fails)}源失败")
    return " ".join(parts)


