(() => {
  const $ = s => document.querySelector(s);
  let data = { sections: { cn: [], world: [], ent: [] } };
  let tab = 'all';
  const config = {
    cn: { label: '中国十大热点', eng: 'CHINA TOP 10', color: '#286ce6', icon: '🇨🇳' },
    world: { label: '全球十大热点', eng: 'WORLD TOP 10', color: '#e67c32', icon: '🌐' },
    ent: { label: '中国十大娱乐热点', eng: 'ENTERTAINMENT TOP 10', color: '#e54e83', icon: '🎬' }
  };
  function stamp(iso) { try { return new Date(iso).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false }) } catch { return '' } }
  function e(tag, name, text) { const el = document.createElement(tag); if(name)el.className=name; if(text!==undefined)el.textContent=text; return el; }
  function show() {
    const q=$('#search').value.trim().toLowerCase(); const container=$('#sections');container.replaceChildren();
    const sections = tab === 'all' ? ['cn','world','ent'] : [tab];
    for(const kind of sections){
      const c = config[kind], raw = data.sections?.[kind] || [];
      const filtered=raw.filter(x=>!q||(x.title+' '+x.source).toLowerCase().includes(q));
      const section=e('section','section '+kind);
      const head=e('div','section-head'); const title=e('h2','',c.icon+' '+c.label); const id=e('span','id',c.eng);head.append(title,id);section.append(head);
      const grid=e('div','news-grid');
      if(!raw.length){ const no=e('div','empty','暂无已核实的数据。首次部署请运行 GitHub Actions 更新新闻，或检查媒体RSS是否可用。');const st=e('span','stat',`成功来源 ${data.stats?.[kind]?.feeds_available||0}/${data.stats?.[kind]?.feed_count||0}`);no.append(st);grid.append(no); }
      else if(!filtered.length) grid.append(e('div','empty','这组新闻没有匹配的关键词。'));
      filtered.forEach((story,i)=>{ const div=e('article','news');const rank=e('span','rank',String(raw.indexOf(story)+1).padStart(2,'0'));const content=e('div','story');const a=e('a','',story.title);a.href=story.url;a.target='_blank';a.rel='noopener noreferrer';const source=e('div','source',`${story.source}  ·  ${stamp(story.published)}`);content.append(a,source);div.append(rank,content);grid.append(div); });
      section.append(grid);container.append(section);
    }
    const count=Object.values(data.sections||{}).reduce((a,v)=>a+v.length,0);
    const incomplete=count<30 ? ` · 已选 ${count}/30 条（不足10条的分类不补旧闻）` : ` · ${count}条`;
    $('#notice').textContent=(data.method||'待更新')+incomplete+'。点击新闻标题可阅读来源原文。'+(data.warning?' '+data.warning:'');
  }
  async function boot() {
    try { const r=await fetch('./data.json?v='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);data=await r.json();$('#stamp').textContent='北京时间 · 最新生成 '+(data.generated_at_beijing||'待生成');$('#window').textContent=data.window_start ? `采集窗口：${data.window_start} — ${data.window_end}`:'等待首次采集';show(); }
    catch (err) { $('#stamp').textContent='无法载入新闻';$('#notice').textContent='未能加载 data.json：'+err.message;show(); }
  }
  document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{tab=b.dataset.tab;document.querySelectorAll('[data-tab]').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-selected',String(x===b));});show()}));
  $('#search').addEventListener('input',show);
  $('#download').addEventListener('click',()=>{
    // Export the complete brief irrespective of the current filter.
    const W=1080,pad=72,rowHeight=71,top=238,groupHeader=68,gap=24;
    const counts=['cn','world','ent'].map(x=>(data.sections?.[x]||[]).length);
    const H=top+counts.reduce((s,n)=>s+groupHeader+Math.max(1,n)*rowHeight+gap,0)+110;
    const canvas=document.createElement('canvas');canvas.width=W*2;canvas.height=H*2;
    const ctx=canvas.getContext('2d');ctx.scale(2,2);ctx.fillStyle='#faf8f4';ctx.fillRect(0,0,W,H);
    ctx.fillStyle='#24314a';ctx.font='900 55px "Microsoft YaHei", sans-serif';ctx.fillText('每日 30 条热点速览',pad,96);
    ctx.font='19px "Microsoft YaHei", sans-serif';ctx.fillStyle='#87909c';ctx.fillText('中国十大热点  ·  全球十大热点  ·  中国十大娱乐热点',pad,135);
    ctx.fillText('北京时间更新 '+(data.generated_at_beijing||'尚未更新')+'   |   近24小时媒体RSS汇总',pad,169);
    let y=top;
    for(const k of ['cn','world','ent']){
      const rows=data.sections?.[k]||[],c=config[k];ctx.fillStyle=c.color;roundRect(ctx,pad,y,W-pad*2,groupHeader-8,13);ctx.fill();ctx.fillStyle='white';ctx.font='bold 29px "Microsoft YaHei", sans-serif';ctx.fillText(c.label,pad+24,y+40);y+=groupHeader;
      const list=rows.length?rows:[{title:'本分类暂无有效数据，请运行自动更新',source:'',published:''}];
      list.forEach((r,i)=>{if(i%2===0){ctx.fillStyle='#ffffff';ctx.fillRect(pad,y,W-pad*2,rowHeight)}ctx.font='bold 19px "Microsoft YaHei", sans-serif';ctx.fillStyle=c.color;ctx.fillText(String(i+1).padStart(2,'0'),pad+14,y+29);ctx.fillStyle='#283347';ctx.font='bold 21px "Microsoft YaHei", sans-serif';const title=r.title.length>45?r.title.slice(0,44)+'…':r.title;ctx.fillText(title,pad+65,y+29);ctx.fillStyle='#929aab';ctx.font='14px "Microsoft YaHei", sans-serif';ctx.fillText(r.source||'',pad+65,y+53);y+=rowHeight});y+=gap;
    }
    ctx.fillStyle='#9a9da4';ctx.font='16px "Microsoft YaHei", sans-serif';ctx.fillText('新闻标题来自媒体RSS · 编辑规则初排 · 非权威排名 · 请点击网站原文核实',pad,y+32);
    canvas.toBlob(blob=>{if(!blob)return;const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='每日30条热点-'+(data.generated_at_beijing||'未更新').slice(0,10)+'.png';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1500)},'image/png');
  });
  function roundRect(ctx,x,y,w,h,r){ctx.beginPath();ctx.roundRect(x,y,w,h,r)}
  boot();
})();
