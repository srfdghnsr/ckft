// 模拟交易看板前端逻辑
let ws = null;
let selectedSymbol = null;
let lastData = null;
let paramDefs = [
  ["signal_period","信号周期", "select", ["day","5m","1m"]],
  ["full_market_scan","全市场扫描","bool"],
  ["scan_move_threshold","全市场预筛涨跌幅%","num"],
  ["risk_per_trade_pct","每笔风险R%","num"],
  ["max_positions_astock","A股最大持仓","num"],
  ["max_positions_future","期货最大持仓","num"],
  ["open_buffer_min","开盘缓冲(分)","num"],
  ["close_buffer_min","收盘缓冲(分)","num"],
  ["slippage_pct","滑点%","num"],
  ["strong_gain_pct","强势涨幅%","num"],
  ["strong_close_ratio","收高位比","num"],
  ["strong_vol_ratio","量比阈值","num"],
  ["breakout_n","突破N日","num"],
  ["stop_loss_pct","止损%","num"],
  ["atr_period","ATR周期","num"],
  ["atr_stop_mult","ATR止损倍","num"],
  ["pullback_tol_pct","回踩容差%","num"],
  ["exit_reversal_bars","反转离场根数","num"],
  ["astock_fee_pct","A股费率","num"],
  ["future_fee_per_lot","期货费/手","num"],
  ["future_margin_pct","期货保证金%","num"],
  ["future_leverage","期货杠杆","num"],
  ["max_total_risk_pct","总风险%","num"],
  ["cooldown_bars","冷却K线数","num"],
  ["event_blacklist_enabled","事件黑名单开","bool"],
  ["event_blacklist","事件日(逗号)","text"],
];

function fmt(n, d=2){ return (n===null||n===undefined||isNaN(n))?"—":Number(n).toFixed(d); }
function pct(n){ return (n>=0?"+":"")+fmt(n,2)+"%"; }
function cls(n){ return n>0?"up":(n<0?"down":"muted"); }
function color(n){ return n>0?"var(--up)":(n<0?"var(--down)":"var(--muted)"); }

function connect(){
  ws = new WebSocket((location.protocol==="https:"?"wss://":"ws://")+location.host+"/ws");
  ws.onmessage = e=>{ lastData = JSON.parse(e.data); render(lastData); };
  ws.onclose = ()=>{ document.getElementById("status").innerHTML='<span class="closed">连接断开，重连中…</span>'; setTimeout(connect,2000); };
  ws.onopen = ()=>{};
}

function render(d){
  const st = d.market_open ? '<span class="live">● 交易中</span>' : '<span class="closed">○ 休市</span>';
  document.getElementById("status").innerHTML = `更新 ${d.last_update} ｜ ${st}`;
  renderOverview(d.accounts);
  renderQuotes(d.quotes);
  renderPositions(d.accounts);
  renderSignals(d.signals);
  renderCandidates(d.candidates);
  drawEquity(d.equity_history);
  // 首次填充监控范围输入框
  const wa=document.getElementById("wlAstock"), wf=document.getElementById("wlFuture");
  if(wa && !wa.value && d.scope) wa.value=d.scope.astock.join(",");
  if(wf && !wf.value && d.scope) wf.value=d.scope.future.join(",");
  if(selectedSymbol) loadKline(selectedSymbol);
}

function renderOverview(acc){
  const a=acc.astock, f=acc.future;
  const peakA = Math.max(...lastData.equity_history.map(x=>x.astock), a.equity);
  const peakF = Math.max(...lastData.equity_history.map(x=>x.future), f.equity);
  const ddA = (a.equity-peakA)/peakA*100, ddF=(f.equity-peakF)/peakF*100;
  const combRet = ((a.equity+f.equity)/(a.init_capital+f.init_capital)-1)*100;
  document.getElementById("overview").innerHTML = `
    <div class="item"><div class="label">A股账户权益</div><div class="val" style="color:${color(a.return_pct)}">¥${fmt(a.equity)}</div><div class="${cls(a.return_pct)}">${pct(a.return_pct)} ｜ 现${fmt(a.cash)}</div></div>
    <div class="item"><div class="label">期货账户权益</div><div class="val" style="color:${color(f.return_pct)}">¥${fmt(f.equity)}</div><div class="${cls(f.return_pct)}">${pct(f.return_pct)} ｜ 现${fmt(f.cash)}</div></div>
    <div class="item"><div class="label">组合收益率</div><div class="val" style="color:${color(combRet)}">${pct(combRet)}</div><div class="muted">期货持仓市值 ¥${fmt(f.market_value)}</div></div>`;
  document.getElementById("drawdown").innerHTML =
    `最大回撤：A股 ${fmt(ddA)}% ｜ 期货 ${fmt(ddF)}% ｜ 累计已实现 A股 ${fmt(a.realized)} / 期货 ${fmt(f.realized)}`;
}

function renderQuotes(qs){
  const tb = document.querySelector("#quoteTable tbody");
  tb.innerHTML = "";
  qs.forEach(q=>{
    const tr=document.createElement("tr");
    if(q.symbol===selectedSymbol) tr.className="sel";
    const cp = q.change_pct==null?0:q.change_pct;
    const src = q.price_source==="kline" ? '<span class="pos-tag" title="日线价（非逐笔实时）">日线</span>' : '';
    tr.innerHTML = `<td>${q.symbol}</td><td>${q.name||q.symbol}</td>
      <td style="color:${q.ok?color(cp):'var(--muted)'}">${fmt(q.price)}</td>
      <td class="${cls(cp)}">${q.ok?pct(cp):'—'}</td>
      <td class="muted">${q.bars||0}</td>
      <td>${q.has_position?'<span class="pos-tag">持</span>':''}${src}</td>`;
    tr.onclick=()=>{ selectedSymbol=q.symbol; document.getElementById("klineSym").textContent=q.symbol; loadKline(q.symbol); renderQuotes(qs); };
    tb.appendChild(tr);
  });
}

function renderPositions(acc){
  const rows=[];
  ["astock","future"].forEach(k=>{
    acc[k].positions.forEach(p=>{
      rows.push(`<div class="row" style="justify-content:space-between;border-bottom:1px solid var(--border);padding:5px 0">
        <span>${p.symbol} <span class="muted">${p.qty}@${fmt(p.entry_price)}</span></span>
        <span class="${cls(p.float_pnl)}">${fmt(p.float_pnl)}</span>
        <span class="muted">止损 ${fmt(p.stop)}</span></div>`);
    });
  });
  document.getElementById("positions").innerHTML = rows.length?rows.join(""):'<div class="muted">无持仓</div>';
}

function renderSignals(sigs){
  const rows = sigs.slice(0,40).map(s=>{
    const c = s.type==="ENTRY"?"var(--up)":"var(--down)";
    const ok = s.ok?"":" ⚠"+(s.reason||"");
    return `<div class="row" style="justify-content:space-between;font-size:11px;border-bottom:1px solid var(--border);padding:3px 0">
      <span class="muted">${s.time}</span>
      <span style="color:${c}">${s.type==='ENTRY'?'买入':'卖出'} ${s.symbol}</span>
      <span class="muted">${s.rule||''} ${s.reason||''}</span>
      <span>${s.ok?(s.pnl!=null?fmt(s.pnl):'✓'):'✗'+ok}</span></div>`;
  });
  document.getElementById("signals").innerHTML = rows.length?rows.join(""):'<div class="muted">暂无信号</div>';
}

function renderCandidates(cands){
  if(!cands||!cands.length){ document.getElementById("candidates").innerHTML='<div class="muted">当前日线无候选信号</div>'; return; }
  const rows = cands.map(s=>{
    const col = s.state==="持有"?"var(--muted)":"var(--up)";
    const det = s.state==="持有"
      ? `入场 ${fmt(s.entry)} 止损 ${fmt(s.stop)} 现 ${fmt(s.price)}`
      : `候选(R${s.rule}) 入场 ${fmt(s.entry)} 止损 ${fmt(s.stop)}`;
    const tag = s.scope==="full" ? ' <span class="pos-tag" title="全市场扫描命中">全</span>' : '';
    return `<div class="row" style="justify-content:space-between;font-size:11px;border-bottom:1px solid var(--border);padding:3px 0">
      <span style="color:${col}">${s.state}</span>
      <span>${s.symbol} ${s.name||''}${tag}</span>
      <span class="muted">${det}</span></div>`;
  });
  document.getElementById("candidates").innerHTML = rows.join("");
}

// ---------- Canvas 图表 ----------
function setupCanvas(cv){
  const dpr=window.devicePixelRatio||1;
  const w=cv.clientWidth||600, h=cv.clientHeight||280;
  // 重要：canvas 显示尺寸由 CSS 固定（width:100%; height:280px），
  // 这里只按 CSS 尺寸 * dpr 设置绘制缓冲区，避免读回属性导致尺寸不断翻倍。
  cv.width=w*dpr; cv.height=h*dpr;
  const ctx=cv.getContext("2d"); ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.clearRect(0,0,w,h);
  return {ctx,w,h};
}

function drawKline(bars, entry, stop){
  const cv=document.getElementById("klineChart");
  if(!bars||!bars.length){ return; }
  const {ctx,w,h}=setupCanvas(cv);
  const n=Math.min(bars.length,90); const data=bars.slice(-n);
  let hi=-1e9, lo=1e9;
  data.forEach(b=>{hi=Math.max(hi,b.high);lo=Math.min(lo,b.low);});
  if(entry) hi=Math.max(hi,entry); if(stop) lo=Math.min(lo,stop);
  const pad=30, plotW=w-pad*2, plotH=h-pad*2-10;
  const x=i=>pad+(i+0.5)*plotW/n;
  const y=v=>pad+ (hi-v)/(hi-lo)*plotH;
  ctx.strokeStyle="#2a313c"; ctx.beginPath(); ctx.moveTo(pad,pad); ctx.lineTo(pad,pad+plotH); ctx.lineTo(pad+plotW,pad+plotH); ctx.stroke();
  const bw=Math.max(2,plotW/n*0.6);
  data.forEach((b,i)=>{
    const up=b.close>=b.open; const col=up?"#ff4d4f":"#1fb85b";
    ctx.strokeStyle=col; ctx.fillStyle=col;
    ctx.beginPath(); ctx.moveTo(x(i),y(b.high)); ctx.lineTo(x(i),y(b.low)); ctx.stroke();
    const yo=y(b.open), yc=y(b.close);
    ctx.fillRect(x(i)-bw/2, Math.min(yo,yc), bw, Math.max(1,Math.abs(yc-yo)));
  });
  if(entry){ ctx.strokeStyle="#ff4d4f"; ctx.setLineDash([4,3]); ctx.beginPath(); ctx.moveTo(pad,y(entry)); ctx.lineTo(pad+plotW,y(entry)); ctx.stroke(); ctx.setLineDash([]);}
  if(stop){ ctx.strokeStyle="#3b82f6"; ctx.setLineDash([4,3]); ctx.beginPath(); ctx.moveTo(pad,y(stop)); ctx.lineTo(pad+plotW,y(stop)); ctx.stroke(); ctx.setLineDash([]);}
}

function drawEquity(hist){
  const cv=document.getElementById("equityChart");
  if(!hist||hist.length<2){ return; }
  const {ctx,w,h}=setupCanvas(cv);
  let hi=-1e9, lo=1e9;
  hist.forEach(p=>{hi=Math.max(hi,p.astock,p.future);lo=Math.min(lo,p.astock,p.future);});
  const pad=30, plotW=w-pad*2, plotH=h-pad*2-10;
  const x=i=>pad+i*plotW/(hist.length-1);
  const y=v=>pad+(hi-v)/(hi-lo||1)*plotH;
  ctx.strokeStyle="#2a313c"; ctx.beginPath(); ctx.moveTo(pad,pad); ctx.lineTo(pad,pad+plotH); ctx.lineTo(pad+plotW,pad+plotH); ctx.stroke();
  const line=(key,col)=>{ ctx.strokeStyle=col; ctx.beginPath(); hist.forEach((p,i)=>{const X=x(i),Y=y(p[key]); i?ctx.lineTo(X,Y):ctx.moveTo(X,Y);}); ctx.stroke(); };
  line("astock","#3b82f6"); line("future","#f0a020");
}

let klineCache = { sym: null, bars: null };
function loadKline(sym){
  // 同标的且已缓存：直接用缓存重绘（持仓变化会刷新入场/止损线），避免重复 fetch 与闪烁
  if(klineCache.sym === sym && klineCache.bars){
    drawKlineCached(sym);
    return;
  }
  fetch("/api/kline?symbol="+encodeURIComponent(sym)).then(r=>r.json()).then(d=>{
    klineCache = { sym, bars: d.bars };
    drawKlineCached(sym);
  }).catch(()=>{});
}
function drawKlineCached(sym){
  if(!klineCache.bars) return;
  let entry=null,stop=null;
  if(lastData){
    ["astock","future"].forEach(k=>{ (lastData.accounts[k].positions||[]).forEach(p=>{ if(p.symbol===sym){entry=p.entry_price;stop=p.stop;} }); });
  }
  drawKline(klineCache.bars, entry, stop);
}

// ---------- 参数 & 监控范围 ----------
function buildParamForm(p){
  const box=document.getElementById("paramForm");
  box.innerHTML="";
  paramDefs.forEach(([k,label,type,opts])=>{
    const f=document.createElement("div"); f.className="field";
    const lab=document.createElement("span"); lab.textContent=label; f.appendChild(lab);
    let inp;
    if(type==="select"){ inp=document.createElement("select"); opts.forEach(o=>{const op=document.createElement("option");op.value=o;op.textContent=o;inp.appendChild(op);}); }
    else if(type==="bool"){ inp=document.createElement("select"); [["true","开"],["false","关"]].forEach(([v,t])=>{const op=document.createElement("option");op.value=v;op.textContent=t;inp.appendChild(op);}); }
    else { inp=document.createElement("input"); inp.type = type==="num"?"number":"text"; }
    inp.id="p_"+k;
    if(type!=="bool") inp.value = (p[k]!==undefined?p[k]:"");
    else inp.value = String(p[k]==="true"||p[k]===true);
    f.appendChild(inp); box.appendChild(f);
  });
}

function readParams(){
  const out={};
  paramDefs.forEach(([k,label,type])=>{
    const v=document.getElementById("p_"+k).value;
    if(type==="num") out[k]=parseFloat(v);
    else if(type==="bool") out[k]=(v==="true");
    else out[k]=v;
  });
  return out;
}

document.getElementById("saveParams").onclick=()=>{
  fetch("/api/params",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(readParams())}).then(()=>alert("参数已保存"));
};
document.getElementById("resetBtn").onclick=()=>{
  if(confirm("确认重置两个模拟账户（清空持仓与成交）？")) fetch("/api/reset",{method:"POST"}).then(()=>alert("已重置"));
};
document.getElementById("saveWl").onclick=()=>{
  const a=document.getElementById("wlAstock").value.split(",").map(s=>s.trim()).filter(Boolean);
  const f=document.getElementById("wlFuture").value.split(",").map(s=>s.trim()).filter(Boolean);
  fetch("/api/scope",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({astock:a,future:f})}).then(()=>alert("监控范围已保存"));
};
document.getElementById("refreshUniv").onclick=()=>{
  fetch("/api/universe/refresh",{method:"POST"}).then(r=>r.json()).then(d=>{
    alert("全市场范围已刷新，合格标的 "+(d.universe_count||0)+" 个");
  }).catch(()=>alert("刷新失败（可能东方财富不可达，将回退到种子范围）"));
};

// 初始化参数表单（从 /api/params 拉取）
fetch("/api/params").then(r=>r.json()).then(p=>{
  buildParamForm(p);
  document.getElementById("wlAstock").value=(lastData?lastData.scope.astock:p_wl_a(p));
});
function p_wl_a(p){ return ""; }

connect();
