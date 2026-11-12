#!/usr/bin/env python3
"""Build a small editorial news index from publisher-provided RSS feeds.

This is not a verified 'top stories of the world' algorithm. It displays
recent, deduplicated publisher headlines and original links. No full articles
or copied snippets are hosted.
"""
import calendar
import datetime as dt
import email.utils
import html
import json
import math
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parent
NOW = dt.datetime.now(dt.timezone.utc)
START = NOW - dt.timedelta(hours=24)
UA = "Mozilla/5.0 (compatible; Daily30PersonalReader/1.0; +https://github.com/)"
FEEDS = {
    "cn": [
        ("中国新闻网·要闻", "https://www.chinanews.com.cn/rss/importnews.xml", 2.0),
        ("中国新闻网·时政", "https://www.chinanews.com.cn/rss/china.xml", 1.8),
        ("中国新闻网·社会", "https://www.chinanews.com.cn/rss/society.xml", 1.3),
        ("中国新闻网·财经", "https://www.chinanews.com.cn/rss/finance.xml", 1.15),
        ("中国新闻网·即时", "https://www.chinanews.com.cn/rss/scroll-news.xml", 0.85),
    ],
    "world": [
        ("中国新闻网·国际", "https://www.chinanews.com.cn/rss/world.xml", 2.2),
        ("BBC News·World", "https://feeds.bbci.co.uk/news/world/rss.xml", 1.25),
        ("BBC News·Business", "https://feeds.bbci.co.uk/news/business/rss.xml", 0.9),
    ],
    "ent": [
        ("新浪娱乐·要闻", "https://rss.sina.com.cn/ent/hot_roll.xml", 2.0),
        ("新浪娱乐·焦点", "https://rss.sina.com.cn/news/allnews/ent.xml", 1.8),
        ("新浪娱乐·明星", "https://rss.sina.com.cn/ent/star/focus7.xml", 1.15),
        ("中国新闻网·文娱", "https://www.chinanews.com.cn/rss/culture.xml", 1.5),
    ],
}
BOOST_CN = ("国务院", "央行", "外交部", "全国", "政策", "重大", "发布", "科技", "地震", "台风", "民生", "经济", "进出口", "事故", "航天", "医保", "教育", "就业", "中美", "通报")
BOOST_WORLD = ("停火", "战争", "总统", "选举", "联合国", "制裁", "谈判", "冲突", "关税", "美联储", "和平", "重大", "国际", "撤军", "气候", "灾害", "trade", "war", "election", "president", "peace", "summit")
BOOST_ENT = ("电影", "明星", "演员", "歌手", "演唱会", "票房", "热搜", "新剧", "官宣", "音乐", "金鸡奖", "奖", "电视剧", "综艺", "导演", "婚", "离婚", "娱乐")
BAD_ENT = ("古代", "考古", "博物馆", "展览", "文化遗产", "诗词", "文物", "非遗", "旅游", "书画")
BAD_CN = ("明星", "演员", "歌手", "票房", "综艺", "演唱会")

def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s or ""))
    return " ".join(s.split())

def read_date(raw):
    if not raw:
        return None
    try:
        v = email.utils.parsedate_to_datetime(raw)
        return (v.replace(tzinfo=dt.timezone.utc) if v.tzinfo is None else v).astimezone(dt.timezone.utc)
    except Exception:
        pass
    try:
        v = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return (v.replace(tzinfo=dt.timezone.utc) if v.tzinfo is None else v).astimezone(dt.timezone.utc)
    except Exception:
        return None

def node_text(parent, *names):
    for name in names:
        node = parent.find(name)
        if node is not None and node.text:
            return clean(node.text)
    return ""

def fetch_rss(url, label, weight):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=18) as response:
        xml = response.read(2_000_000)
    root = ET.fromstring(xml)
    result = []
    items = root.findall("./channel/item")
    if not items:
        items = root.findall("{http://www.w3.org/2005/Atom}entry")
    for it in items:
        title = node_text(it, "title", "{http://www.w3.org/2005/Atom}title")
        link = node_text(it, "link")
        if not link:
            an = it.find("{http://www.w3.org/2005/Atom}link")
            if an is not None:
                link = an.attrib.get("href", "")
        published = read_date(node_text(it, "pubDate", "published", "{http://www.w3.org/2005/Atom}published", "{http://purl.org/dc/elements/1.1/}date", "{http://www.w3.org/2005/Atom}updated"))
        if not title or not link.startswith(("https://", "http://")) or published is None:
            continue
        # RSS timestamps are not all reliable. Do not quietly invent a date.
        if not (START <= published <= NOW + dt.timedelta(minutes=10)):
            continue
        result.append({"title": title, "url": link, "source": label, "published": published.isoformat(), "_weight": weight, "_dt": published})
    return result

def norm(s):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", s.lower().replace("最新", "").replace("快讯", ""))[:100]

def same(a, b):
    x, y = norm(a), norm(b)
    if not x or not y:
        return False
    if x == y:
        return True
    if len(x) > 19 and len(y) > 19 and (x in y or y in x):
        return True
    return SequenceMatcher(None, x, y).ratio() > .90

def score(a, section):
    title = a["title"].lower()
    age_hours = max(0., (NOW - a["_dt"]).total_seconds() / 3600)
    boosts = {"cn": BOOST_CN, "world": BOOST_WORLD, "ent": BOOST_ENT}[section]
    value = a["_weight"] + 1.3 * max(0, 1-age_hours/24) + .35 * min(4, sum(k.lower() in title for k in boosts))
    if section == "ent" and any(w in title for w in BAD_ENT):
        value -= 2.8
    if section == "cn" and any(w in title for w in BAD_CN):
        value -= 2.2
    if section == "world" and re.search(r"[\u4e00-\u9fff]", title):
        value += 1.0  # Chinese headlines preferred for this Chinese-language reader.
    return round(value, 3)

def select(items, section, limit=10):
    # Keep source diversity; these scores are an experimental ordering heuristic,
    # not a 'coverage' or 'importance' statistic.
    for a in items:
        a["score"] = score(a, section)
    items.sort(key=lambda a: (a["score"], a["_dt"]), reverse=True)
    chosen = []
    for a in items:
        if any(same(a["title"], b["title"]) for b in chosen):
            continue
        chosen.append(a)
        if len(chosen) == limit:
            break
    result = []
    for a in chosen:
        result.append({k: a[k] for k in ("title", "url", "source", "published")})
    return result

def main():
    news = {}
    stats = {}
    all_errors = []
    for section, feeds in FEEDS.items():
        candidates = []
        successful = 0
        for label, url, weight in feeds:
            try:
                feed_items = fetch_rss(url, label, weight)
                candidates.extend(feed_items)
                successful += 1
                print(f"{section}: {label} -> {len(feed_items)} timely articles")
            except Exception as e:
                print(f"WARN {label}: {type(e).__name__}: {e}", file=sys.stderr)
                all_errors.append(label)
        news[section] = select(candidates, section)
        stats[section] = {"candidate_count": len(candidates), "feeds_available": successful, "feed_count": len(feeds), "selected_count": len(news[section])}
    empty = sum(x["selected_count"] for x in stats.values()) == 0
    if empty:
        # Publish the site with an explicit failure state, never invented headlines.
        print("WARN: no fresh RSS stories were received; publishing an empty status page.", file=sys.stderr)
    now_bj = NOW.astimezone(TZ)
    payload = {"generated_at": NOW.isoformat(), "generated_at_beijing": now_bj.strftime("%Y-%m-%d %H:%M"), "window_start": START.astimezone(TZ).strftime("%Y-%m-%d %H:%M"), "window_end": now_bj.strftime("%Y-%m-%d %H:%M"), "method": "媒体RSS近24小时标题，简易规则排序与相似标题去重（不是权威热度排行）", "stats": stats, "warning": "本轮没有收集到可用新闻，请检查源站连接。" if empty else "仅用于个人阅读索引；不保证收录全部重大事件。标题真实性请以原文为准。", "sections": news}
    (ROOT / "data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {(ROOT / 'data.json')}: {sum(len(v) for v in news.values())} headlines; unavailable: {all_errors}")

if __name__ == "__main__":
    main()
