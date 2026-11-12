#!/usr/bin/env python3
"""Daily30 v2: daily 09:00 CST editorial RSS index and persistent history.

Ranks *reported articles*, not objective global attention. Cross-publisher
coverage is a proxy for importance, not factual verification. Fail closed when
nothing is available; never invent headlines or backdate a rolling feed.
"""
from __future__ import annotations
import datetime as dt
import email.utils
import html
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
ROOT = Path(__file__).resolve().parent
ARCHIVES = ROOT / 'history'
UA = 'Mozilla/5.0 (compatible; Daily30NewsIndex/2.0; personal RSS reader)'
ATOM = '{http://www.w3.org/2005/Atom}'
DC = '{http://purl.org/dc/elements/1.1/}'

# We consume published headlines and original links, not article bodies.
# Independent publisher count is based on outlets, NOT number of RSS channels.
def gn(query, language='zh-CN', region='CN', edition='CN:zh-Hans'):
    return 'https://news.google.com/rss/search?q=' + urllib.parse.quote(query) + '&hl=' + language + '&gl=' + region + '&ceid=' + urllib.parse.quote(edition)

FEEDS = {
 'cn': [
  ('中国新闻网·要闻', 'https://www.chinanews.com.cn/rss/importnews.xml', 1.1, '中国新闻网'),
  ('中国新闻网·时政', 'https://www.chinanews.com.cn/rss/china.xml', 1.05, '中国新闻网'),
  ('中国新闻网·财经', 'https://www.chinanews.com.cn/rss/finance.xml', .95, '中国新闻网'),
  ('中国新闻网·社会', 'https://www.chinanews.com.cn/rss/society.xml', .80, '中国新闻网'),
  ('中国新闻网·即时', 'https://www.chinanews.com.cn/rss/scroll-news.xml', .65, '中国新闻网'),
  ('Google新闻·中国焦点', gn('中国 OR 国务院 OR 央行 OR 外交部 when:2d'), .9, 'Google新闻'),
  ('Google新闻·中国经济科技', gn('(中国 经济) OR (中国 科技) OR (中国 社会) when:2d'), .78, 'Google新闻'),
 ],
 'world': [
  ('BBC·国际', 'https://feeds.bbci.co.uk/news/world/rss.xml', 1.05, 'BBC'),
  ('BBC·商业', 'https://feeds.bbci.co.uk/news/business/rss.xml', .8, 'BBC'),
  ('卫报·国际', 'https://www.theguardian.com/world/rss', 1.0, 'The Guardian'),
  ('NPR·国际', 'https://feeds.npr.org/1004/rss.xml', .95, 'NPR'),
  ('半岛电视台·国际', 'https://www.aljazeera.com/xml/rss/all.xml', .85, 'Al Jazeera'),
  ('中国新闻网·国际', 'https://www.chinanews.com.cn/rss/world.xml', 1.0, '中国新闻网'),
  ('Google新闻·国际头条', 'https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en', .85, 'Google新闻'),
  ('Google新闻·全球综合', 'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en', .65, 'Google新闻'),
 ],
 'ent': [
  ('新浪娱乐·要闻', 'https://rss.sina.com.cn/ent/hot_roll.xml', 1.15, '新浪娱乐'),
  ('新浪娱乐·焦点', 'https://rss.sina.com.cn/news/allnews/ent.xml', 1.05, '新浪娱乐'),
  ('新浪娱乐·明星', 'https://rss.sina.com.cn/ent/star/focus7.xml', 1.0, '新浪娱乐'),
  ('中国新闻网·文娱', 'https://www.chinanews.com.cn/rss/culture.xml', .75, '中国新闻网'),
  ('Google新闻·华语娱乐', gn('明星 OR 电影 OR 电视剧 OR 综艺 OR 歌手 OR 演唱会 when:2d'), .9, 'Google新闻'),
  ('Google新闻·中文娱乐圈', gn('内娱 OR 娱乐圈 OR 影视剧 OR 华语音乐 when:2d'), .85, 'Google新闻'),
 ],
}

# Each phrase is an *editorial heuristic*, not proof that a story is true.
IMPACT = {
 'cn': [
  (('中央政治局','国务院','全国人大','央行','人民银行','货币政策','最高人民法院','重大改革','国家安全'), 1.9),
  (('外交部','中美','关税','制裁','经济增长','财政','失业','医保','养老','教育政策','航天','空间站','地震','洪水','特大','事故','召回'), 1.2),
  (('人工智能','半导体','新能源','高铁','科研突破','楼市','房价','出口','贸易'), .8),
 ],
 'world': [
  (('战争','停火','空袭','袭击','总统','首相','选举','制裁','政变','俄乌','中东','核武','爆炸','灾难','央行','贸易战','peace','ceasefire','war','airstrike','attack','election','president','presidential','prime minister','missile','sanction','nuclear','tariff'), 1.8),
  (('联合国','峰会','抗议','罢工','外交','谈判','地震','人道主义','通胀','利率','climate','earthquake','protest','strike','diplomat','inflation','refugee','summit','interest rate'), 1.1),
  (('科技','气候','人工智能','疫苗','AI','economic','economy','technology','science'), .65),
 ],
 'ent': [
  (('金鸡奖','电影节','电视剧','电影','新剧','票房','演员','明星','导演','演唱会','歌手','音乐','综艺','官宣','离婚','结婚','首映','获奖','纪录','微博热搜','热搜'), 1.2),
  (('官宣','爆红','定档','开播','发布','公开','回应','争议','领奖','新歌'), .6),
 ],
}
PENALTY = {
 'cn': ('招聘会','校园招聘','开幕式','校庆','地方展会','播种进度','科普活动','图片展','网络主播','娱乐圈','电视剧','演员','演唱会'),
 'world': ('recipe','puzzle','football match','match report','fashion trends','restaurant review','opinion:','live blog'),
 'ent': ('古籍','历史遗址','文物','考古','博物馆','非遗传承','诗词大会','展览','书画','文化遗产','旅游线路'),
}
GENERIC = re.compile(r'(最新|快讯|关注|突发|图文|组图|视频|刚刚|一图读懂|独家|消息称|外媒|记者观察|深度观察|hot\s*take|live updates)', re.I)


def clean(text):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', '', text or '')).split())


def parse_date(value):
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except Exception:
        try:
            d = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def text_of(node, *tags):
    for tag in tags:
        sub = node.find(tag)
        if sub is not None and sub.text:
            return clean(sub.text)
    return ''


def publisher_key(name):
    key = re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', (name or '').lower())
    known = {'bbcnews': 'bbc', 'britishbroadcastingcorporation': 'bbc',
             'theguardian': 'guardian', 'guardian': 'guardian',
             'reuters': 'reuters', 'reutersnews': 'reuters',
             'associatedpress': 'ap', 'apnews': 'ap',
             '新华社': '新华社', '新华网': '新华社',
             '中央电视台': '央视', '央视新闻': '央视'}
    return known.get(key, key)


def latest_completed_window(now_utc):
    now_local = now_utc.astimezone(TZ)
    cutoff = dt.datetime.combine(now_local.date(), dt.time(9), tzinfo=TZ)
    if now_local < cutoff:
        cutoff -= dt.timedelta(days=1)
    return cutoff - dt.timedelta(days=1), cutoff


def parse_items(xml_bytes, feed_name, base_weight, base_publisher, start, end):
    root = ET.fromstring(xml_bytes)
    entries = root.findall('./channel/item')
    if not entries:
        entries = root.findall(f'{ATOM}entry')
    items = []
    for i, item in enumerate(entries):
        title = text_of(item, 'title', f'{ATOM}title')
        url = text_of(item, 'link')
        if not url:
            link = item.find(f'{ATOM}link')
            if link is not None:
                url = link.get('href', '')
        when = parse_date(text_of(item, 'pubDate', 'published', f'{ATOM}published', f'{ATOM}updated', f'{DC}date'))
        if not (title and url.startswith(('https://','http://')) and when and start <= when < end):
            continue
        publisher = base_publisher
        if base_publisher == 'Google新闻':
            publisher = text_of(item, 'source') or 'Google新闻（来源未注明）'
            if title.endswith(' - ' + publisher):
                title = title[:-(len(publisher) + 3)]
        if len(title) < 7 or len(title) > 180:
            continue
        items.append({'title': title, 'url': url, 'source': publisher, 'feed': feed_name,
                      'published': when.isoformat(), 'publisher': publisher_key(publisher),
                      '_weight': base_weight, '_date': when, '_feed_rank': i})
    return items


def get_items(feed, start, end):
    name, url, weight, publisher = feed
    request = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*',
        'Accept-Language': 'zh-CN,zh;q=0.8,en;q=0.7'})
    with urllib.request.urlopen(request, timeout=17) as response:
        xml_bytes = response.read(3_000_000)
    return parse_items(xml_bytes, name, weight, publisher, start, end)


def norm(title):
    title = GENERIC.sub('', title)
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', title.lower())[:150]


def shingles(title, n):
    s = norm(title)
    return set(s[i:i+n] for i in range(max(0, len(s) - n + 1)))


def same_event(a, b):
    x, y = norm(a), norm(b)
    if not x or not y:
        return False
    if x == y:
        return True
    if len(x) >= 16 and len(y) >= 16 and (x in y or y in x):
        return True
    seq = SequenceMatcher(None, x, y).ratio()
    if seq >= .79:
        return True
    a2, b2 = shingles(a, 2), shingles(b, 2)
    a3, b3 = shingles(a, 3), shingles(b, 3)
    if not a2 or not b2 or not a3 or not b3:
        return False
    s2 = len(a2 & b2) / len(a2 | b2)
    s3 = len(a3 & b3) / len(a3 | b3)
    # Strict enough to avoid merging different stories just because both
    # reference the same country, public figure or broad subject.
    return (s3 >= .40 and s2 >= .48) or (seq >= .64 and s3 >= .30 and s2 >= .40)


def impact_score(title, section):
    lower = title.lower()
    amount = 0.0
    for phrases, weight in IMPACT[section]:
        if any(p.lower() in lower for p in phrases):
            amount += weight
    if any(p.lower() in lower for p in PENALTY[section]):
        amount -= 3.0 if section != 'world' else 2.0
    # Entertainment RSS often also contains general museum/heritage news.
    if section == 'ent' and not any(p.lower() in lower for group, _ in IMPACT['ent'] for p in group):
        amount -= 1.7
    return amount


def events_from_items(items):
    # Cluster only *similar headline descriptions*. Even identical event
    # clusters do not assert independent fact checking.
    clusters = []
    seen_urls = set()
    for it in sorted(items, key=lambda i: (i['_weight'], i['_date']), reverse=True):
        if it['url'] in seen_urls:
            continue
        seen_urls.add(it['url'])
        cluster = next((cluster for cluster in clusters if any(same_event(it['title'], m['title']) for m in cluster['members'][:5])), None)
        if cluster is None:
            cluster = {'members': []}
            clusters.append(cluster)
        cluster['members'].append(it)
    return clusters


def rank_events(items, section, end):
    events = []
    for cluster in events_from_items(items):
        members = cluster['members']
        publishers = {m['publisher'] for m in members}
        # Display a concise Chinese title when possible; favor clearly
        # described events over overlong clickbait and aggregator headlines.
        representative = max(members, key=lambda m: (
            m['_weight'] + (.38 if re.search('[\u4e00-\u9fff]', m['title']) else 0)
            + (.2 if 10 <= len(m['title']) <= 65 else 0), -len(m['title'])))
        d = max(m['_date'] for m in members)
        age_h = max(0, (end.astimezone(dt.timezone.utc) - d).total_seconds() / 3600)
        distinct = len(publishers)
        # Source diversity dominates recency: five reports from one outlet
        # count as ONE publisher, not as five corroborating news organizations.
        corroboration = min(6.0, max(0, distinct - 1) * 2.2)
        importance = impact_score(representative['title'], section)
        recency = .4 * (1 - min(24., age_h) / 24.)
        placement = .4 * max(0, 1 - representative['_feed_rank'] / 30)
        score = round(3.0 + importance + corroboration + representative['_weight'] + recency + placement, 3)
        events.append({'title': representative['title'], 'url': representative['url'],
           'source': representative['source'], 'published': representative['published'],
           'source_count': distinct, 'sources': sorted({m['source'] for m in members})[:6],
           'score': score, '_cluster': cluster})
    return sorted(events, key=lambda x: (x['score'], x['published']), reverse=True)


def choose(events, limit=10, avoid=None):
    avoid = avoid or []
    accepted = []
    deferred = []
    primary_counts = Counter()
    for event in events:
        if any(same_event(event['title'], past['title']) for past in avoid):
            continue
        if any(same_event(event['title'], past['title']) for past in accepted):
            continue
        publisher = event['source'].lower()
        if primary_counts[publisher] >= 5:
            deferred.append(event)
        else:
            accepted.append(event)
            primary_counts[publisher] += 1
        if len(accepted) == limit:
            break
    for event in deferred:
        if len(accepted) == limit:
            break
        accepted.append(event)
    return [{k: v for k, v in e.items() if not k.startswith('_')} for e in accepted]


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def build_index():
    entries = []
    for f in ARCHIVES.glob('????-??-??.json'):
        try:
            d = dt.date.fromisoformat(f.stem)
            payload = json.loads(f.read_text('utf-8'))
            n = sum(len(v) for v in payload.get('sections', {}).values())
            entries.append({'date': d.isoformat(), 'count': n, 'file': f.name})
        except (OSError, ValueError, TypeError):
            continue
    entries.sort(key=lambda x: x['date'], reverse=True)
    write_json(ARCHIVES / 'index.json', {'version': 2, 'days': entries})
    return entries


def generate(now=None, fetcher=None, root=None, force=False):
    global ROOT, ARCHIVES
    if root is not None:
        ROOT = Path(root)
        ARCHIVES = ROOT / 'history'
    now = now or dt.datetime.now(dt.timezone.utc)
    start, end = latest_completed_window(now)
    date = end.date().isoformat()
    archive_file = ARCHIVES / f'{date}.json'
    if archive_file.exists() and not force:
        print(f'Daily archive {date} already exists; reusing the same fixed edition.')
        data = json.loads(archive_file.read_text('utf-8'))
        write_json(ROOT / 'data.json', data)
        build_index()
        return data
    fetcher = fetcher or get_items
    stats = {}
    errors = []
    ranked = {}
    for section, feeds in FEEDS.items():
        pool, available, publishers = [], 0, set()
        # Concurrent feed retrieval keeps the daily job responsive when a
        # publisher is slow or a legacy RSS endpoint times out.
        with ThreadPoolExecutor(max_workers=min(6, len(feeds))) as executor:
            futures = {executor.submit(fetcher, feed, start.astimezone(dt.timezone.utc),
                                       end.astimezone(dt.timezone.utc)): feed for feed in feeds}
            for future in as_completed(futures):
                feed = futures[future]
                try:
                    got = future.result()
                    pool.extend(got)
                    available += 1
                    publishers.update(x['publisher'] for x in got)
                    print(f'{section}: {feed[0]} -> {len(got)}')
                except Exception as exc:
                    print(f'WARNING {feed[0]}: {type(exc).__name__}: {exc}', file=sys.stderr)
                    errors.append(feed[0])
        ranked[section] = rank_events(pool, section, end)
        stats[section] = {'candidate_count': len(pool), 'feeds_available': available,
            'feed_count': len(feeds), 'publishers_seen': len(publishers),
            'events_found': len(ranked[section])}
    # Assemble Chinese stories first, then a globally diverse list excluding
    # extremely similar repeats, then Chinese entertainment.
    selected = {'cn': choose(ranked['cn'])}
    selected['world'] = choose(ranked['world'], avoid=selected['cn'])
    selected['ent'] = choose(ranked['ent'], avoid=selected['cn'] + selected['world'])
    count = sum(len(x) for x in selected.values())
    if count == 0:
        raise RuntimeError('All feeds returned no valid stories in this 09:00–09:00 window. No empty archive will be published.')
    for section in selected:
        stats[section]['selected_count'] = len(selected[section])
    data = {'version': 2, 'date': date,
      'generated_at': now.isoformat(),
      'generated_at_beijing': now.astimezone(TZ).strftime('%Y-%m-%d %H:%M'),
      'window_start': start.strftime('%Y-%m-%d %H:%M'),
      'window_end': end.strftime('%Y-%m-%d %H:%M'),
      'method': '多来源RSS + 相似事件合并 + 不同媒体覆盖度 + 事件影响力 + 少量时效加权（非官方热搜）',
      'warning': '排名是启发式编辑排序；媒体多源报道不等于事实已核实。部分RSS源可能不可用，无法保证全球前十无遗漏。',
      'stats': stats, 'source_errors': errors,
      'sections': selected}
    write_json(archive_file, data)
    write_json(ROOT / 'data.json', data)
    build_index()
    print(f'Wrote {date}: {count}/30 articles; {len(errors)} feeds unavailable')
    return data


def main():
    generate(force=os.getenv('FORCE_REFRESH', '').lower() in {'1','true','yes'})

if __name__ == '__main__':
    main()
