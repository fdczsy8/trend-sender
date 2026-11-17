# -*- coding: utf-8 -*-
"""开发者资讯日报：抓取 → 过滤/打标 → 去重 → HTML邮件 + Markdown 清单。

本地测试：  python main.py --no-email
密钥全部来自环境变量（GitHub Actions 用 Secrets 注入），代码零硬编码。
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
import traceback
from pathlib import Path

import mailer
import pipeline
import report
import sources

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", BASE_DIR / "output"))


def collect_items(cfg: dict):
    """按开关逐个抓取数据源，源与源之间限速。返回 (items, source_stats)。"""
    items, stats = [], {}
    delay = cfg.get("request_delay_seconds", 2)
    limit = cfg.get("per_source_limit", 30)
    for idx, (key, name, fetcher) in enumerate(sources.SOURCE_REGISTRY):
        if not pipeline.source_enabled(key, cfg):
            print(f"[skip] {name} 已关闭")
            continue
        if idx and delay:
            time.sleep(delay)
        print(f"[fetch] {name} ...")
        try:
            got = fetcher(limit)
            items.extend(got)
            stats[name] = {"ok": True, "fetched": len(got)}
            print(f"  -> {len(got)} 条")
        except Exception as e:  # noqa: BLE001 - 单源失败不影响其他源
            stats[name] = {"ok": False, "fetched": 0, "error": str(e)}
            print(f"  !! 失败: {e}")
    return items, stats


def build_stats(all_items, kept, drop_bl, drop_star, dup, source_stats, cfg):
    whitelist_hits = sum(1 for it in kept if it.extra.get("pinned"))
    single_html = sum(1 for it in kept if it.extra.get("single_html"))
    return {
        "total_fetched": len(all_items),
        "total": len(kept),
        "whitelist_hits": whitelist_hits,
        "single_html": single_html,
        "dropped_blacklist": drop_bl,
        "dropped_min_stars": drop_star,
        "dropped_duplicate": dup,
        "sources": source_stats,
        "desc_max_length": cfg.get("desc_max_length", 160),
    }


def run(send_email: bool = True) -> int:
    cfg = pipeline.load_config()
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d %H:%M")

    all_items, source_stats = collect_items(cfg)
    kept, drop_bl, drop_star = pipeline.decorate(all_items, cfg)

    history = pipeline.load_history()
    fresh, dup = pipeline.dedup(kept, history, cfg.get("dedup_days", 7))
    fresh = pipeline.sort_items(fresh)
    stats = build_stats(all_items, fresh, drop_bl, drop_star, dup, source_stats, cfg)

    sections = report.split_sections(fresh, cfg)
    html_body = report.render_html(sections, stats, cfg["mode"], date_str)
    md_body = report.render_markdown(sections, stats, cfg["mode"], date_str)
    subject = report.build_subject(stats, date_str)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUTPUT_DIR / f"digest-{now.strftime('%Y%m%d-%H%M')}.md"
    md_path.write_text(md_body, encoding="utf-8")
    (OUTPUT_DIR / "digest.html").write_text(html_body, encoding="utf-8")
    print(f"[output] Markdown 清单: {md_path}")

    failures = {n: i.get("error", "") for n, i in source_stats.items() if not i.get("ok")}

    if not send_email:
        print("[dry-run] 跳过邮件发送")
    elif not mailer.smtp_configured():
        print("[warn] SMTP 未配置，跳过发送（本地预览可打开 output/digest.html）")
    else:
        mailer.send_email(subject, html_body)
        print(f"[mail] 已发送: {subject}")
        pipeline.save_history(pipeline.record_pushed(
            fresh, history, cfg.get("history_keep_days", 60)))
        print("[cache] 去重历史已更新")

    if failures:
        detail = "以下数据源抓取失败：\n\n" + "\n".join(f"· {n}: {e}" for n, e in failures.items())
        print(f"[warn] {len(failures)} 个数据源失败")
        if send_email and mailer.smtp_configured():
            mailer.send_error_email(f"【报错提醒】资讯日报 {len(failures)} 个数据源失败 {date_str}", detail)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="开发者资讯日报")
    parser.add_argument("--no-email", action="store_true", help="本地干跑，不发送邮件")
    args = parser.parse_args()
    try:
        return run(send_email=not args.no_email)
    except Exception:  # noqa: BLE001 - 任何致命错误都发提醒邮件并以非零码退出
        err = traceback.format_exc()
        print(f"[fatal] {err}", file=sys.stderr)
        if mailer.smtp_configured():
            mailer.send_error_email("【报错提醒】资讯日报脚本运行失败", err)
        return 1


if __name__ == "__main__":
    sys.exit(main())
