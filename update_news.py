#!/usr/bin/env python3
"""Daily30 v3: fixed 09:00 Chinese editions with editorial signal and daily archives.

60s curated newsletter is used as an optional ranking signal only. Never
copy the curated newsletter's entire list as articles; output links are
reported RSS items and each keeps its own publication timestamp. Media
coverage is a weak proxy for salience, NOT independent fact checking.
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
UA = 'Mozilla/5.0 (compatible; Daily30NewsIndex/3.0; personal RSS reader)'
CURATED_BASE = 'https://raw.githubusercontent.com/vikiboss/60s-static-host/main/static/60s/'
CURATED_FALLBACK = 'https://60s-static.viki.moe/60s/'
ATOM = '{http://www.w3.org/2005/Atom}'
DC = '{http://purl.org/dc/elements/1.1/}'

# We consume published headlines and original links, not article bodies.
# Independent publisher count is based on outlets, NOT number of RSS channels.
def gn(query, language='zh-CN', region='CN', edition='CN:zh-Hans'):
    return 'https://news.google.com/rss/search?q=' + urllib.parse.quote(query) + '&hl=' + language + '&gl=' + region + '&ceid=' + urllib.parse.quote(edition)

# Aggregators are discovery channels: the visible source is the publisher of
# each article, not the aggregator. A source's name never means endorsement.
FEEDS = {
 'cn': [
  ('中国新闻网·要闻', 'https://www.chinanews.com.cn/rss/importnews.xml', 1.2, '中国新闻网'),
  ('中国新闻网·时政', 'https://www.chinanews.com.cn/rss/china.xml', 1.2, '中国新闻网'),
  ('中国新闻网·财经', 'https://www.chinanews.com.cn/rss/finance.xml', 1.0, '中国新闻网'),
  ('中国新闻网·社会', 'https://www.chinanews.com.cn/rss/society.xml', .85, '中国新闻网'),
  ('中国新闻网·即时', 'https://www.chinanews.com.cn/rss/scroll-news.xml', .7, '中国新闻网'),
  ('聚合·国家政策', gn('(国务院 OR 政策 OR 财政部 OR 人大 OR 外交部) when:2d'), 1.1, '谷歌新闻'),
  ('聚合·民生经济', gn('(最低工资 OR 医保 OR 社保 OR 住房 OR 物价 OR 税收) when:2d'), 1.1, '谷歌新闻'),
  ('聚合·重大社会', gn('(中国 地震) OR (中国 重大事故) OR (中国 社会热点) when:2d'), .95, '谷歌新闻'),
  ('聚合·科技产业', gn('(中国 科研突破) OR (中国 新能源) OR (中国 人工智能) when:2d'), .9, '谷歌新闻'),
  ('聚合·中国要闻', gn('中国 OR 国务院 OR 央行 OR 外交部 when:2d'), .88, '谷歌新闻'),
 ],
 'world': [
  ('中国新闻网·国际', 'https://www.chinanews.com.cn/rss/world.xml', 1.15, '中国新闻网'),
  ('聚合·全球要闻', gn('(国际大事 OR 全球重大新闻 OR 世界新闻) when:2d'), 1.05, '谷歌新闻'),
  ('聚合·世界局势', gn('(俄乌 OR 停火 OR 战争 OR 军事冲突 OR 国际谈判) when:2d'), 1.2, '谷歌新闻'),
  ('聚合·国际政治', gn('(美国总统 OR 国际选举 OR 外交 OR 联合国 OR 国际峰会) when:2d'), 1.03, '谷歌新闻'),
  ('聚合·国际经济', gn('(全球经济 OR 美联储 OR 关税 OR 国际贸易 OR 全球股市) when:2d'), .93, '谷歌新闻'),
  ('聚合·国际社会', gn('(国际灾害 OR 国际疫情 OR 世界气候 OR 国际罢工) when:2d'), .9, '谷歌新闻'),
  # English feeds contribute cross-source signals, but English titles are NOT
  # selected as the visible story: the entire website remains Chinese.
  ('英国广播公司·国际', 'https://feeds.bbci.co.uk/news/world/rss.xml', .95, '英国广播公司'),
  ('卫报·国际', 'https://www.theguardian.com/world/rss', .92, '卫报'),
  ('美国公共广播电台·国际', 'https://feeds.npr.org/1004/rss.xml', .86, '美国公共广播电台'),
  ('半岛电视台·国际', 'https://www.aljazeera.com/xml/rss/all.xml', .84, '半岛电视台'),
 ],
 'ent': [
  ('新浪娱乐·要闻', 'https://rss.sina.com.cn/ent/hot_roll.xml', 1.23, '新浪娱乐'),
  ('新浪娱乐·焦点', 'https://rss.sina.com.cn/news/allnews/ent.xml', 1.12, '新浪娱乐'),
  ('新浪娱乐·明星', 'https://rss.sina.com.cn/ent/star/focus7.xml', 1.04, '新浪娱乐'),
  ('中国新闻网·文娱', 'https://www.chinanews.com.cn/rss/culture.xml', .73, '中国新闻网'),
  ('聚合·明星娱乐', gn('(明星 OR 演员 OR 娱乐圈 OR 华语歌手) when:2d'), .98, '谷歌新闻'),
  ('聚合·影视综艺', gn('(电视剧 OR 中国电影 OR 综艺 OR 票房) when:2d'), .95, '谷歌新闻'),
  ('聚合·华语音乐', gn('(演唱会 OR 华语新歌 OR 音乐节 OR 歌手) when:2d'), .9, '谷歌新闻'),
 ],
}

# Each phrase is an *editorial heuristic*, not proof that a story is true.
# Each term matches a *potential* significance signal, never verifies a fact.
IMPACT = {
 'cn': [
  (('政治局','国务院','全国人大','国家主席','国家安全','最高法','最高检','立法','新规','重大改革','监管政策','央行','人民银行','货币政策','国家税务总局','外交部','中美关系'), 2.45),
  (('最低工资','养老金','社保','医保','教育政策','就业政策','住房保障','房贷','楼市','利率','税收','财政','惠民','物价','生活成本','用工','救灾','补贴','停车收费'), 2.15),
  (('地震','洪水','台风','空难','特大事故','火灾','刑事案件','应急响应','公共安全','食品安全','维权','重大诉讼'), 1.7),
  (('航天','卫星发射','自主研发','首飞','科技突破','半导体','人工智能','新能源','芯片','新能源汽车'), 1.1),
  (('贸易','出口','国际组织','共建“一带一路”','外交会谈','金融市场','资本市场'), 1.0),
 ],
 'world': [
  (('停火','换俘','谈判','和平协议','冲突','导弹','空袭','制裁','战争','俄乌','中东','巴以','军事行动','袭击','选举','政变','总统','首相','政局'), 2.3),
  (('联合国','外交','峰会','国会','参议院','政府辞职','抗议','全国罢工','重大袭击','核武','气候大会'), 1.65),
  (('关税','全球经济','通胀','利率','美联储','贸易政策','国际贸易','金融危机','能源危机','油价'), 1.65),
  (('地震','疫情','洪水','气候','自然灾害','火山','公共卫生','难民','人道主义','重大研究'), 1.35),
 ],
 'ent': [
  (('金鸡奖','金像奖','金马奖','电影节','电影奖','票房纪录','电影票房','官宣主演','官宣','首映','颁奖','获奖','电视剧','演唱会','新专辑','综艺','顶流'), 1.65),
  (('明星','演员','导演','歌手','艺人','娱乐圈','电影','新剧','定档','开播','回应','音乐','离婚','结婚','恋情','粉丝'), 1.0),
 ],
}
PENALTY = {
 'cn': ('招聘会','校园招聘','开幕式','校庆','地方展会','播种进度','科普活动','图片展','网络主播','娱乐圈','电视剧','演员','演唱会','天气预报','地方文化节','传统民俗','文艺晚会'),
 'world': ('recipe','puzzle','football match','match report','fashion trends','restaurant review','opinion:','live blog','美食推荐','名人八卦'),
 'ent': ('古籍','历史遗址','文物','考古','博物馆','非遗传承','诗词大会','展览','书画','文化遗产','旅游线路','古籍修复','饮食文化','文化名城'),
}
TOPICS = {
 'cn': [
  ('政策政务', ('国务院','全国人大','党中央','外交部','新规','立法','政策','央行','政府','国家安全','政治局','规定')),
  ('经济民生', ('最低工资','社保','医保','养老金','住房','经济','税收','财政','物价','收费','就业','贸易','消费','补贴','金融','房地产')),
  ('社会热点', ('地震','火灾','事故','失联','争议','事件','调查','交通','法院','学校','大学','医院','食品安全','维权')),
  ('科技产业', ('科技','芯片','人工智能','卫星','航天','新能源','首飞','科研','出口','电动车','汽车')),
 ],
 'world': [
  ('冲突与安全', ('战争','俄乌','巴以','加沙','空袭','袭击','停火','导弹','战事','军事','恐怖','换俘')),
  ('国际政治', ('总统','首相','大选','选举','国会','参议院','外交','峰会','辞职','政变','联合国','政府')),
  ('国际经济', ('全球经济','关税','美联储','利率','通胀','油价','贸易','国际金融','市场')),
  ('全球社会', ('气候','洪水','地震','疫情','公共卫生','罢工','抗议','难民','灾害','饥荒')),
 ],
 'ent': [
  ('电影与奖项', ('金鸡奖','金像奖','金马奖','奥斯卡','电影','票房','导演','颁奖')),
  ('剧集与综艺', ('电视剧','综艺','真人秀','开播','定档','剧集','主演')),
  ('音乐与演出', ('歌手','音乐','新歌','演唱会','专辑','音乐节','巡演')),
  ('明星动态', ('艺人','明星','演员','恋情','婚姻','回应','工作室','离婚','结婚')),
 ],
}
SOURCE_DISPLAY = {
 'BBC':'英国广播公司','BBC News':'英国广播公司','The Guardian':'英国《卫报》',
 'NPR':'美国公共广播电台','Al Jazeera':'半岛电视台','Reuters':'路透社',
 'Associated Press':'美联社','AP News':'美联社','Bloomberg':'彭博社',
 'CNBC':'美国消费者新闻与商业频道','Google新闻':'谷歌新闻','Google News':'谷歌新闻',
 'China Daily':'中国日报','Xinhua':'新华社','新华社':'新华社',
 '央视新闻':'央视新闻', 'People.cn':'人民网', '新浪网':'新浪新闻',
 'BBC中文':'英国广播公司中文网',
 'CNN':'美国有线电视新闻网', 'NBC News':'美国全国广播公司新闻',
 'ABC News':'美国广播公司新闻', 'CBS News':'美国哥伦比亚广播公司新闻',
 'The New York Times':'纽约时报', 'The Washington Post':'华盛顿邮报',
 'Financial Times':'金融时报', 'The Economist':'经济学人',
 'Fox News':'福克斯新闻', 'New York Post':'纽约邮报',
 'Variety':'《综艺》杂志', 'The Hollywood Reporter':'《好莱坞报道者》',
 'Entertainment Weekly':'《娱乐周刊》', 'Rolling Stone':'《滚石》杂志',
 'Billboard':'《公告牌》杂志', 'People.com':'《人物》杂志'

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
        if base_publisher in {'谷歌新闻', 'Google新闻'}:
            publisher = text_of(item, 'source') or '聚合新闻（媒体未标明）'
            if title.endswith(' - ' + publisher):
                title = title[:-(len(publisher) + 3)]
        if len(title) < 7 or len(title) > 180:
            continue
        raw_publisher = publisher
        publisher = SOURCE_DISPLAY.get(publisher, publisher)
        if not re.search(r'[\u4e00-\u9fff]', publisher):
            publisher = '海外媒体'
        items.append({'title': title, 'url': url, 'source': publisher, 'original_source': raw_publisher, 'feed': feed_name,
                      'published': when.isoformat(), 'publisher': publisher_key(raw_publisher),
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



def get_curated_news(date):
    """Optional same-day 60s reference. Never substitute a stale edition."""
    for url in (CURATED_BASE + date + '.json', CURATED_FALLBACK + date + '.json'):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=12) as r:
                raw = json.loads(r.read(128_000).decode('utf-8'))
            if raw.get('date') != date:
                continue
            items = [clean(x) for x in raw.get('news', []) if isinstance(x, str)]
            if not items:
                continue
            return {'date': date, 'headlines': items[:30],
                    'url': raw.get('link') if str(raw.get('link','')).startswith('https://') else
                           'https://60s-static.viki.moe/', 'source':'每天60秒读懂世界'}
        except Exception as e:
            print(f'Curated reference unavailable ({type(e).__name__}): {url}', file=sys.stderr)
    return None


def has_chinese(text):
    # English-only RSS stories help measure source coverage but cannot become
    # the visible representative on a Chinese-only site.
    return len(re.findall(r'[\u4e00-\u9fff]', text)) >= 6


def topic_of(title, section):
    s = title.lower()
    for label, terms in TOPICS[section]:
        if any(t.lower() in s for t in terms):
            return label
    return '其他要闻' if section != 'ent' else '其他娱乐'


def is_entertainment(title):
    lower = title.lower()
    if any(p.lower() in lower for p in PENALTY['ent']):
        return False
    return any(p.lower() in lower for terms, _ in IMPACT['ent'] for p in terms)


def curated_similarity(title, headline):
    """Conservative lexical link for one event described in different ways.

    An editorial hit changes rank only, not the actual RSS title/source/link.
    This is *not* semantic fact checking.
    """
    a, b = norm(title), norm(headline)
    if len(a) < 10 or len(b) < 10:
        return 0.0
    if a in b or b in a:
        return 1.0
    grams_a, grams_b = shingles(title, 2), shingles(headline, 2)
    hits = grams_a & grams_b
    if len(hits) < 5:
        return 0.0
    fraction = len(hits) / max(1, min(len(grams_a), len(grams_b)))
    if fraction < 0.32:
        return 0.0
    three_a, three_b = shingles(title, 3), shingles(headline, 3)
    common3 = len(three_a & three_b)
    if common3 < 3:
        return 0.0
    if fraction > .45 or (fraction > .35 and common3 >= 5):
        return min(1.0, fraction)
    return 0.0


def digest_match(title, reference):
    if not reference:
        return 0.0
    return max((curated_similarity(title, headline) for headline in reference.get('headlines', [])), default=0.0)

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


def rank_events(items, section, end, reference=None):
    events = []
    for cluster in events_from_items(items):
        members = cluster['members']
        chinese = [m for m in members if has_chinese(m['title'])]
        # No opaque machine translation; publish only source titles in Chinese.
        if not chinese:
            continue
        # Entertainment without entertainment specifics is not a hot topic.
        if section == 'ent' and not any(is_entertainment(m['title']) for m in chinese):
            continue
        publishers = {m['publisher'] for m in members}
        representative = max(chinese, key=lambda m: (
            m['_weight'] + (.23 if 12 <= len(m['title']) <= 65 else 0)
            + (.20 if topic_of(m['title'], section) != '其他要闻' else 0), -len(m['title'])))
        d = max(m['_date'] for m in members)
        age_h = max(0, (end.astimezone(dt.timezone.utc) - d).total_seconds() / 3600)
        distinct = len(publishers)
        # Multiple same-outlet feeds do NOT count as independent sources.
        corroboration = min(4.8, max(0, distinct - 1) * 1.65)
        importance = max(impact_score(m['title'], section) for m in chinese)
        # The 60s article is a *curated attention signal*, not our article source.
        cur_match = 0 if section == 'ent' else max(digest_match(m['title'], reference) for m in chinese)
        curated_boost = (3.8 if section == 'cn' else 3.2) * cur_match
        recency = .35 * (1 - min(24., age_h) / 24.)
        placement = .30 * max(0, 1 - representative['_feed_rank'] / 30)
        score = round(2.0 + importance + corroboration + curated_boost + representative['_weight'] + recency + placement, 3)
        topic = topic_of(representative['title'], section)
        events.append({'title': representative['title'], 'url': representative['url'],
           'source': representative['source'], 'published': representative['published'],
           'source_count': distinct, 'sources': sorted({m['source'] for m in members})[:6],
           'score': score, 'topic': topic, 'editorial_reference': bool(cur_match >= .32),
           '_cluster': cluster})
    return sorted(events, key=lambda x: (x['score'], x['published']), reverse=True)


def choose(events, limit=10, avoid=None, section='cn'):
    avoid = avoid or []
    candidates = [e for e in events if not any(same_event(e['title'], x['title']) for x in avoid)]
    chosen = []
    topic_counts = Counter()
    publisher_counts = Counter()
    while candidates and len(chosen) < limit:
        def current_score(e):
            topic = e.get('topic','其他要闻')
            # Editor-like balanced page: one narrow type of news shouldn't
            # consume all ten positions. Keep high-impact events ahead.
            topical_penalty = max(0, topic_counts[topic] - 1) * (.75 if section != 'ent' else .8)
            source_penalty = max(0, publisher_counts[e['source']] - 2) * .28
            return (e['score'] - topical_penalty - source_penalty, e['score'])
        best = max(candidates, key=current_score)
        candidates.remove(best)
        if any(same_event(best['title'], x['title']) for x in chosen):
            continue
        chosen.append(best)
        topic_counts[best.get('topic','其他要闻')] += 1
        publisher_counts[best['source']] += 1
    return [{k: v for k, v in e.items() if not k.startswith('_')} for e in chosen]


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
    write_json(ARCHIVES / 'index.json', {'version': 3, 'days': entries})
    return entries


def generate(now=None, fetcher=None, root=None, force=False, curated_fetcher=None):
    global ROOT, ARCHIVES
    if root is not None:
        ROOT = Path(root)
        ARCHIVES = ROOT / 'history'
    now = now or dt.datetime.now(dt.timezone.utc)
    start, end = latest_completed_window(now)
    date = end.date().isoformat()
    archive_file = ARCHIVES / f'{date}.json'
    prior = None
    if archive_file.exists():
        prior = json.loads(archive_file.read_text('utf-8'))
    # Preserve older archives. Upgrade only the CURRENT day's old-format
    # snapshot; recheck an early morning snapshot once if 60s was not ready.
    local_now = now.astimezone(TZ)
    should_recheck_reference = bool(prior and prior.get('version', 0) >= 3 and
        not prior.get('reference', {}).get('available') and local_now.date() == end.date() and
        local_now.hour <= 11)
    if prior and not force and prior.get('version', 0) >= 3 and not should_recheck_reference:
        print(f'Daily archive {date} already exists; reusing the same fixed edition.')
        write_json(ROOT / 'data.json', prior)
        build_index()
        return prior
    if prior and not force and prior.get('version', 0) < 3 and local_now.date() != end.date():
        print(f'Old completed archive {date} left unchanged.')
        write_json(ROOT / 'data.json', prior)
        build_index()
        return prior
    curated_fetcher = curated_fetcher or get_curated_news
    reference = curated_fetcher(date)
    if prior and not force and should_recheck_reference and not reference:
        print('Same-day curated feed unavailable; retain existing archive.')
        write_json(ROOT / 'data.json', prior)
        build_index()
        return prior
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
        ranked[section] = rank_events(pool, section, end, reference=reference if section != 'ent' else None)
        stats[section] = {'candidate_count': len(pool), 'feeds_available': available,
            'feed_count': len(feeds), 'publishers_seen': len(publishers),
            'events_found': len(ranked[section])}
    # Assemble Chinese stories first, then a globally diverse list excluding
    # extremely similar repeats, then Chinese entertainment.
    selected = {'cn': choose(ranked['cn'], section='cn')}
    selected['world'] = choose(ranked['world'], avoid=selected['cn'], section='world')
    selected['ent'] = choose(ranked['ent'], avoid=selected['cn'] + selected['world'], section='ent')
    count = sum(len(x) for x in selected.values())
    if count == 0:
        if prior:
            print('No new stories from sources; retain previously saved archive.')
            write_json(ROOT / 'data.json', prior)
            build_index()
            return prior
        raise RuntimeError('All feeds returned no valid stories in this 09:00–09:00 window. No empty archive will be published.')
    for section in selected:
        stats[section]['selected_count'] = len(selected[section])
    data = {'version': 3, 'date': date,
      'generated_at': now.isoformat(),
      'generated_at_beijing': now.astimezone(TZ).strftime('%Y-%m-%d %H:%M'),
      'window_start': start.strftime('%Y-%m-%d %H:%M'),
      'window_end': end.strftime('%Y-%m-%d %H:%M'),
      'method': '精选日报重要性参考 + 新闻媒体独立报道 + 政策民生和重大事件优先 + 同题去重与领域均衡',
      'warning': '个人新闻索引；相关媒体多并不代表事实已独立核实。精选日报只作排名参考，不会直接复制其全部新闻。',
      'reference': {'available': bool(reference), 'source':'每天60秒读懂世界',
                    'date': reference['date'] if reference else None,
                    'url': reference['url'] if reference else None,
                    'matching_articles': sum(1 for rows in selected.values() for r in rows if r.get('editorial_reference'))},
      'stats': stats, 'source_errors': errors,
      'sections': selected}
    write_json(archive_file, data)
    write_json(ROOT / 'data.json', data)
    build_index()
    print(f'Wrote {date}: {count}/30 articles; {len(errors)} feeds unavailable; curated={bool(reference)}')
    return data


def main():
    generate(force=os.getenv('FORCE_REFRESH', '').lower() in {'1','true','yes'})

if __name__ == '__main__':
    main()
