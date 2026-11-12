(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const config = {
    cn: { label: '中国十大热点', eng: 'CHINA TOP 10', color: '#286ce6', icon: '🇨🇳' },
    world: { label: '全球十大热点', eng: 'WORLD TOP 10', color: '#e67c32', icon: '🌐' },
    ent: { label: '中国十大娱乐热点', eng: 'ENTERTAINMENT TOP 10', color: '#e54e83', icon: '🎬' }
  };
  const empty = () => ({ sections: { cn: [], world: [], ent: [] } });
  let data = empty();
  let tab = 'all';
  let days = [];
  let latestDate = '';
  let selectedDay = '';
  let noticeOverride = '';
  function el(tag, name, value) {
    const node = document.createElement(tag);
    if (name) node.className = name;
    if (value !== undefined) node.textContent = value;
    return node;
  }
  function dateFrom(iso) {
    try { return new Date(iso).toLocaleString('zh-CN', { timeZone:'Asia/Shanghai', month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false }); }
    catch { return ''; }
  }
  function dayBefore(day) {
    const d = new Date(`${day}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 10);
  }
  function show() {
    const q = $('#search').value.trim().toLowerCase();
    const container = $('#sections'); container.replaceChildren();
    const sections = tab === 'all' ? ['cn', 'world', 'ent'] : [tab];
    for (const kind of sections) {
      const c = config[kind], raw = data.sections?.[kind] || [];
      const filtered = raw.filter(x => !q || (x.title + ' ' + x.source).toLowerCase().includes(q));
      const section = el('section', 'section ' + kind);
      const head = el('div', 'section-head');
      head.append(el('h2', '', c.icon + ' ' + c.label), el('span', 'id', c.eng));
      section.append(head);
      const grid = el('div', 'news-grid');
      if (!raw.length) {
        const no = el('div', 'empty', `这一天的「${c.label}」没有可用新闻；不会凑数。`);
        if (data.stats?.[kind]) no.append(el('span','stat', `可用源 ${data.stats[kind].feeds_available || 0}/${data.stats[kind].feed_count || 0}`));
        grid.append(no);
      } else if (!filtered.length) {
        grid.append(el('div', 'empty', '没有匹配的新闻。'));
      }
      for (const story of filtered) {
        const item = el('article', 'news'), rank = el('span', 'rank', String(raw.indexOf(story) + 1).padStart(2, '0'));
        const content = el('div','story'), a = el('a', '', story.title);
        a.href = story.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        const src = el('div','source', `${story.source} · ${dateFrom(story.published)}`);
        if (story.source_count > 1) src.append(el('span','covered', ` · ${story.source_count}家媒体涉及`));
        content.append(a, src); item.append(rank,content); grid.append(item);
      }
      section.append(grid); container.append(section);
    }
    const count = Object.values(data.sections || {}).reduce((n, a) => n + a.length, 0);
    $('#notice').textContent = noticeOverride || `${data.method || '新闻索引'} · ${count}/30条。${data.warning || '请点击标题阅读来源原文。'}`;
    $('#stamp').textContent = data.generated_at_beijing
      ? `北京时间 · ${data.generated_at_beijing} 生成` : '正在等待首次采集';
    $('#window').textContent = data.window_start
      ? `统计时段：${data.window_start} — ${data.window_end}` : '等待新闻更新';
    $('#edition').textContent = selectedDay
      ? `当前查看：${selectedDay} 日报（09:00 截稿）` : '每天北京时间09:00截稿';
    $('#latest').classList.toggle('active', selectedDay === latestDate);
    $('#previous').classList.toggle('active', !!selectedDay && !!latestDate && selectedDay === dayBefore(latestDate));
    $('#historySelect').value = days.some(x => x.date === selectedDay) ? selectedDay : '';
  }
  function archiveWarning(message) {
    noticeOverride = message;
    const node = $('#archiveMessage');
    node.textContent = message;
    node.hidden = !message;
  }
  async function getJson(path) {
    const sep = path.includes('?') ? '&' : '?';
    const response = await fetch(path + sep + '_=' + Date.now(), { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }
  async function loadDay(date) {
    if (!date) return;
    if (!days.some(d => d.date === date)) {
      selectedDay = date;
      data = empty();
      archiveWarning(`${date} 暂无保存的日报。旧版网站之前没有按日归档，无法凭空恢复。之后每天生成的日报会保留在这里。`);
      show(); return;
    }
    try {
      const result = await getJson('./history/' + encodeURIComponent(date) + '.json');
      selectedDay = date; data = result;
      archiveWarning(''); show();
    } catch (error) {
      selectedDay = date; data = empty();
      archiveWarning(`无法载入 ${date} 历史日报：${error.message}。请确认 GitHub Actions 已提交 history 文件夹。`);
      show();
    }
  }
  async function boot() {
    try {
      const idx = await getJson('./history/index.json');
      days = Array.isArray(idx.days) ? idx.days.filter(x => /^\d{4}-\d\d-\d\d$/.test(x.date)) : [];
    } catch { days = []; }
    const select = $('#historySelect'); select.replaceChildren();
    select.append(el('option', '', days.length ? '选择日期' : '暂无历史存档'));
    select.options[0].value = '';
    for (const item of days) {
      const option = el('option', '', `${item.date}（${item.count}条）`);
      option.value = item.date; select.append(option);
    }
    latestDate = days[0]?.date || '';
    if (latestDate) {
      await loadDay(latestDate);
    } else {
      try {
        data = await getJson('./data.json');
        selectedDay = data.date || '';
        latestDate = selectedDay;
        if (!selectedDay) archiveWarning('当前可以查看最新新闻，但旧版未保存历史日报。升级后运行一次更新，系统才会开始按日期归档。');
      } catch (error) {
        archiveWarning('无法读取新闻数据：' + error.message);
      }
      show();
    }
  }
  document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => {
    tab = b.dataset.tab;
    document.querySelectorAll('[data-tab]').forEach(x => {
      x.classList.toggle('active', x === b);
      x.setAttribute('aria-selected', String(x === b));
    });
    show();
  }));
  $('#search').addEventListener('input', show);
  $('#latest').addEventListener('click', () => latestDate && loadDay(latestDate));
  $('#previous').addEventListener('click', () => latestDate && loadDay(dayBefore(latestDate)));
  $('#historySelect').addEventListener('change', e => e.target.value && loadDay(e.target.value));
  $('#download').addEventListener('click', () => {
    const W = 1080, pad = 72, rowHeight = 71, top = 238, groupHeader = 68, gap = 24;
    const counts = ['cn','world','ent'].map(x => (data.sections?.[x] || []).length);
    const H = top + counts.reduce((sum,n) => sum + groupHeader + Math.max(1,n)*rowHeight + gap,0) + 110;
    const canvas = document.createElement('canvas'); canvas.width = W*2; canvas.height = H*2;
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    ctx.scale(2,2); ctx.fillStyle = '#faf8f4'; ctx.fillRect(0,0,W,H);
    ctx.fillStyle = '#24314a'; ctx.font = '900 55px "Microsoft YaHei", sans-serif';
    ctx.fillText('每日30条热点速览', pad,96);
    ctx.font = '19px "Microsoft YaHei", sans-serif'; ctx.fillStyle = '#87909c';
    ctx.fillText('中国十大热点  ·  全球十大热点  ·  中国十大娱乐热点', pad,135);
    ctx.fillText(`${selectedDay || '最新'} 日报  |  截稿 北京时间09:00  |  ${data.window_start || ''} 至 ${data.window_end || ''}`, pad,169);
    let y = top;
    for (const kind of ['cn','world','ent']) {
      const rows = data.sections?.[kind] || [], c = config[kind];
      ctx.fillStyle = c.color; roundRect(ctx,pad,y,W-pad*2,groupHeader-8,13); ctx.fill();
      ctx.fillStyle = 'white'; ctx.font = 'bold 29px "Microsoft YaHei", sans-serif';
      ctx.fillText(c.label, pad+24, y+40); y += groupHeader;
      const list = rows.length ? rows : [{title:'当前分类没有可用新闻',source:''}];
      for (const [i,r] of list.entries()) {
        if (i%2===0) { ctx.fillStyle = '#fff'; ctx.fillRect(pad,y,W-pad*2,rowHeight); }
        ctx.font = 'bold 19px "Microsoft YaHei", sans-serif'; ctx.fillStyle = c.color;
        ctx.fillText(String(i+1).padStart(2,'0'),pad+14,y+29);
        ctx.fillStyle = '#283347'; ctx.font = 'bold 21px "Microsoft YaHei", sans-serif';
        const text = r.title.length > 42 ? r.title.slice(0,41) + '…' : r.title;
        ctx.fillText(text, pad+65, y+29);
        ctx.fillStyle = '#929aab'; ctx.font = '14px "Microsoft YaHei", sans-serif';
        ctx.fillText(`${r.source || ''}${r.source_count > 1 ? ` · ${r.source_count}家媒体` : ''}`, pad+65, y+53);
        y += rowHeight;
      }
      y += gap;
    }
    ctx.fillStyle = '#9a9da4'; ctx.font = '16px "Microsoft YaHei", sans-serif';
    ctx.fillText('仅供个人阅读 · RSS标题索引 · 非官方热点榜，不保证无遗漏',pad,y+32);
    canvas.toBlob(blob => {
      if (!blob) return;
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `每日30条热点-${selectedDay || '最新'}.png`;
      link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1500);
    }, 'image/png');
  });
  function roundRect(ctx,x,y,w,h,r) { ctx.beginPath(); ctx.roundRect(x,y,w,h,r); }
  boot();
})();
