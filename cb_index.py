"""
Taiwan CB Index Builder
Outputs: output/cb_indices.html  — interactive dashboard
         - live filter panel
         - theme switcher (Light / Bloomberg Dark)
"""

import sqlite3, time, json
import pandas as pd
import numpy as np
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH    = r"d:\VS Code\dbdownloader\data\finmind.db"
OUTPUT_DIR = Path(r"d:\VS Code\CBMonitor\output")
START_DATE = "2010-01-01"

DEFAULTS = dict(
    useMaxPrice = True,
    maxPrice    = 200,
    useMinMaturity = True,
    minMaturity = 90,
    useParityLo = True,
    parityLo    = 95,
    useParityHi = True,
    parityHi    = 105,
)

OUTPUT_DIR.mkdir(exist_ok=True)
def p(msg): print(msg, flush=True)

# ── Data loading ──────────────────────────────────────────────────────────────
def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    daily = pd.read_sql(
        "SELECT date,cb_id,close,unit FROM taiwan_stock_convertible_bond_daily WHERE date>=?",
        conn, params=(START_DATE,)
    )
    basic = pd.read_sql(
        """SELECT date,cb_id,ConversionPrice,PriceOfUnderlyingStock,
                  OutstandingAmount,DueDateOfConversion,DateOfDelisted
           FROM taiwan_stock_convertible_bond WHERE date>=?""",
        conn, params=(START_DATE,)
    )
    conn.close()
    daily["date"] = pd.to_datetime(daily["date"])
    basic["date"] = pd.to_datetime(basic["date"])
    df = daily.merge(basic, on=["date","cb_id"], how="left")
    df.sort_values(["cb_id","date"], inplace=True)
    bcols = ["ConversionPrice","PriceOfUnderlyingStock",
             "OutstandingAmount","DueDateOfConversion","DateOfDelisted"]
    df[bcols] = df.groupby("cb_id", sort=False)[bcols].ffill()
    return df.reset_index(drop=True)

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    cp, sp = df["ConversionPrice"], df["PriceOfUnderlyingStock"]
    df["parity"] = np.where(cp > 0, 100.0 * sp / cp, np.nan)
    df["prem"]   = np.where(df["parity"] > 0, df["close"] / df["parity"] - 1.0, np.nan)
    df["due"]  = pd.to_datetime(df["DueDateOfConversion"], errors="coerce")
    df["dl"]   = (df["due"] - df["date"]).dt.days
    df.sort_values(["cb_id","date"], inplace=True)
    df["v5"] = df.groupby("cb_id", sort=False)["unit"] \
                  .transform(lambda s: s.rolling(5, min_periods=1).mean())
    del_d = pd.to_datetime(df["DateOfDelisted"], errors="coerce")
    df["delist"] = del_d.notna() & (df["date"] >= del_d)
    return df

def embed_filter(df: pd.DataFrame) -> pd.DataFrame:
    mask = (df["close"] > 0) & (~df["delist"]) & (df["ConversionPrice"] > 0)
    return df[mask].copy()

def prepare_raw_json(df: pd.DataFrame) -> str:
    dates = sorted(df["date"].dt.strftime("%Y-%m-%d").unique())
    didx  = {d: i for i, d in enumerate(dates)}
    cbids = sorted(df["cb_id"].astype(str).unique())
    cidx  = {c: i for i, c in enumerate(cbids)}
    df    = df.copy()
    df["di"] = df["date"].dt.strftime("%Y-%m-%d").map(didx)
    df["ci"] = df["cb_id"].astype(str).map(cidx)
    df["_c"]  = (df["close"] * 10).round().clip(0, 32767).astype(int)
    df["_u"]  = df["unit"].clip(0, 65535).astype(int)
    df["_v"]  = (df["v5"] * 10).round().clip(0, 65535).astype(int)
    df["_p"]  = (df["prem"] * 10000).fillna(-9999).round().clip(-9999, 99999).astype(int)
    df["_pa"] = (df["parity"] * 10).fillna(-1).round().clip(-1, 99999).astype(int)
    df["_dl"] = df["dl"].fillna(-1).astype(int)
    df["_o"]  = ((df["OutstandingAmount"].fillna(0) / 1e7) * 10
                 ).round().clip(0, 999999).astype(int)
    rows = df[["di","ci","_c","_u","_v","_p","_pa","_dl","_o"]].values.tolist()
    return json.dumps({"dates": dates, "cbids": cbids, "rows": rows}, separators=(",", ":"))


# ══════════════════════════════════════════════════════════════════════════════
#  HTML template
# ══════════════════════════════════════════════════════════════════════════════
_HTML = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8"/>
<title>Taiwan CB Indices</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
/* ── reset ── */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;font-family:"Segoe UI",Arial,sans-serif}

/* ══ LIGHT theme (default) ════════════════════════════════════════════════ */
body{background:#f0f2f5;color:#222}

header{background:#1a237e;color:#fff}
.tabs{background:#e8eaf6}
.tab-btn{background:#c5cae9;color:#283593}
.tab-btn:hover{background:#9fa8da}
.tab-btn.active{background:#fff;color:#1a237e}
.chart-area{background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.07)}
.hint{background:#fafafa;border-top:1px solid #eee;color:#888}
#filter-drawer{background:#fff;border-right:1px solid #ddd}
#filter-inner h2{color:#1a237e;border-bottom:2px solid #e8eaf6}
.f-section h3{color:#3f51b5;background:#e8eaf6}
.f-row label{color:#444}
.f-val{color:#1a237e}
#btn-apply{background:#1a237e;color:#fff}
#btn-apply:hover{background:#283593}
#btn-reset{background:#e8eaf6;color:#3f51b5}
.f-status{color:#888}
#filter-toggle,#theme-btn{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.3);color:#fff}
#filter-toggle:hover,#theme-btn:hover{background:rgba(255,255,255,.25)}

/* ══ BLOOMBERG DARK theme ═════════════════════════════════════════════════ */
body.bbg{background:#0A0A0A;color:#C8C8C8}

body.bbg header{background:#000;border-bottom:3px solid #FF6600}
body.bbg .tabs{background:#111}
body.bbg .tab-btn{background:#1A1A1A;color:#FF9900;border:1px solid #222}
body.bbg .tab-btn:hover{background:#222;color:#FFC200}
body.bbg .tab-btn.active{background:#FF6600;color:#000;border-color:#FF6600;
  box-shadow:0 -2px 8px rgba(255,102,0,.4)}
body.bbg .chart-area{background:#0E1117;box-shadow:0 2px 12px rgba(0,0,0,.5)}
body.bbg .hint{background:#0A0A0A;border-top:1px solid #1A1A1A;color:#555}
body.bbg #filter-drawer{background:#0D0D0D;border-right:1px solid #222}
body.bbg #filter-inner h2{color:#FF9900;border-bottom:2px solid #222}
body.bbg .f-section h3{color:#FF6600;background:#1A1A1A}
body.bbg .f-row label{color:#999}
body.bbg .f-val{color:#FF9900}
body.bbg #btn-apply{background:#FF6600;color:#000}
body.bbg #btn-apply:hover{background:#FF8800}
body.bbg #btn-reset{background:#1A1A1A;color:#FF9900;border:1px solid #333}
body.bbg .f-status{color:#555}
body.bbg #filter-toggle,body.bbg #theme-btn{
  background:rgba(255,102,0,.15);border:1px solid #FF6600;color:#FF9900}
body.bbg #filter-toggle:hover,body.bbg #theme-btn:hover{
  background:rgba(255,102,0,.3);color:#FFC200}
body.bbg input[type=range]{accent-color:#FF6600}

/* ══ layout ═══════════════════════════════════════════════════════════════ */
body{display:flex;flex-direction:column}
header{flex-shrink:0;padding:9px 16px;display:flex;
       align-items:center;justify-content:space-between}
.hdr-left h1{font-size:1.1rem;font-weight:700}
.hdr-left p{font-size:.72rem;opacity:.7;margin-top:1px}
.hdr-right{display:flex;gap:8px;flex-shrink:0;margin-left:14px}
#filter-toggle,#theme-btn{
  padding:5px 14px;border-radius:4px;cursor:pointer;font-size:.8rem;
  font-weight:600;white-space:nowrap;transition:background .15s}

#body-wrap{flex:1;min-height:0;display:flex;overflow:hidden}

/* filter drawer */
#filter-drawer{width:0;overflow:hidden;transition:width .25s ease;
  display:flex;flex-direction:column;flex-shrink:0}
#filter-drawer.open{width:280px;overflow-y:auto}
#filter-inner{padding:14px 16px;min-width:260px}
#filter-inner h2{font-size:.9rem;font-weight:700;margin-bottom:10px;padding-bottom:6px}
.f-section{margin-bottom:14px}
.f-section h3{font-size:.78rem;font-weight:600;padding:3px 8px;
  border-radius:3px;margin-bottom:8px}
.f-note{font-size:.7rem;line-height:1.35;margin:-2px 0 8px;color:#777}
.f-row{display:flex;align-items:center;gap:8px;margin-bottom:7px}
.f-row label{font-size:.75rem;width:92px;flex-shrink:0;line-height:1.3}
.f-row input[type=checkbox]{width:15px;height:15px;flex-shrink:0;accent-color:#3f51b5}
.f-row .f-suffix{font-size:.75rem;white-space:nowrap}
.f-row input[type=number]{
  width:72px;padding:4px 6px;border-radius:4px;font-size:.85rem;font-weight:600;
  text-align:right;border:1px solid #bbb;outline:none;transition:border .15s}
.f-row input[type=number]:focus{border-color:#3f51b5}
body.bbg .f-row input[type=number]{background:#1A1A1A;border-color:#333;color:#FF9900}
body.bbg .f-row input[type=checkbox]{accent-color:#FF6600}
body.bbg .f-row input[type=number]:focus{border-color:#FF6600}
body.bbg .f-note{color:#777}
#btn-apply,#btn-reset{width:100%;border:none;border-radius:4px;cursor:pointer;font-weight:600}
#btn-apply{padding:8px;font-size:.85rem;margin-top:8px}
#btn-reset{padding:5px;font-size:.78rem;margin-top:5px}
.f-status{font-size:.7rem;margin-top:8px;text-align:center}

/* main area */
#main-area{flex:1;min-width:0;display:flex;flex-direction:column}
.tabs{flex-shrink:0;display:flex;gap:3px;padding:10px 14px 0}
.tab-btn{padding:7px 18px;border:none;border-radius:6px 6px 0 0;cursor:pointer;
  font-size:.84rem;font-weight:500;transition:background .15s}
.chart-area{flex:1;min-height:0;display:flex;flex-direction:column;
  margin:0 14px 12px;border-radius:0 6px 6px 6px;overflow:hidden}
.chart-panel{display:none;flex:1;min-height:0}
.chart-panel.active{display:flex;flex-direction:column}
.chart-panel>div{flex:1;min-height:0}
.overlay-tools{flex:0 0 auto!important;display:flex;gap:14px;align-items:center;
  flex-wrap:wrap;padding:8px 12px;border-bottom:1px solid #eee;font-size:.78rem}
.overlay-tools label{display:flex;align-items:center;gap:5px;white-space:nowrap;cursor:pointer}
.overlay-tools select{font-size:.78rem;padding:3px 6px;border:1px solid #bbb;border-radius:4px}
.overlay-tools input{accent-color:#3f51b5}
.overlay-plot{flex:1;min-height:0}
body.bbg .overlay-tools{border-bottom-color:#1A1A1A}
body.bbg .overlay-tools select{background:#1A1A1A;border-color:#333;color:#FF9900}
body.bbg .overlay-tools input{accent-color:#FF6600}
.hint{flex-shrink:0;font-size:.7rem;padding:3px 12px 5px}
</style>
</head>
<body>
<header>
  <div class="hdr-left">
    <h1>📈 台灣可轉債指數儀表板</h1>
    <p id="hdr-params">載入中...</p>
  </div>
  <div class="hdr-right">
    <button id="theme-btn"   onclick="cycleTheme()">🌙 Bloomberg</button>
    <button id="filter-toggle" onclick="toggleDrawer()">⚙ 篩選條件</button>
  </div>
</header>

<div id="body-wrap">
  <!-- ── filter drawer ── -->
  <div id="filter-drawer">
    <div id="filter-inner">
      <h2>篩選條件</h2>
      <div class="f-section">
        <h3>套用全部圖表</h3>
        <div class="f-note">影響：市場廣度、全市場溢價率、疊加圖、CB報酬指數</div>
        <div class="f-row"><input type="checkbox" id="f-useMaxPrice" checked onchange="syncVal('useMaxPrice',this.checked)">
          <label>剔除收盤價</label>
          <input type="number" id="f-maxPrice" min="100" max="500" step="5" value="__maxPrice__"
                 onchange="syncVal('maxPrice',+this.value)" onkeydown="enterApply(event)">
          <span class="f-suffix">以上</span></div>
        <div class="f-row"><input type="checkbox" id="f-useMinMaturity" checked onchange="syncVal('useMinMaturity',this.checked)">
          <label>剔除剩餘天數</label>
          <input type="number" id="f-minMaturity" min="0" max="730" step="5" value="__minMaturity__"
                 onchange="syncVal('minMaturity',+this.value)" onkeydown="enterApply(event)">
          <span class="f-suffix">以下</span></div>
        <div class="f-row"><input type="checkbox" id="f-useParityLo" checked onchange="syncVal('useParityLo',this.checked)">
          <label>parity</label>
          <input type="number" id="f-parityLo" min="0" max="300" step="1" value="__parityLo__"
                 onchange="syncVal('parityLo',+this.value)" onkeydown="enterApply(event)">
          <span class="f-suffix">以上</span></div>
        <div class="f-row"><input type="checkbox" id="f-useParityHi" checked onchange="syncVal('useParityHi',this.checked)">
          <label>parity</label>
          <input type="number" id="f-parityHi" min="0" max="300" step="1" value="__parityHi__"
                 onchange="syncVal('parityHi',+this.value)" onkeydown="enterApply(event)">
          <span class="f-suffix">以下</span></div>
      </div>
      <button id="btn-apply" onclick="applyFilters()">套用 重新計算</button>
      <button id="btn-reset" onclick="resetFilters()">恢復預設值</button>
      <div class="f-status" id="f-status"></div>
    </div>
  </div>

  <!-- ── charts ── -->
  <div id="main-area">
    <div class="tabs">
      <button class="tab-btn active" onclick="showTab('breadth',this)">① 市場廣度</button>
      <button class="tab-btn"        onclick="showTab('premium',this)">② 全市場溢價率</button>
      <button class="tab-btn"        onclick="showTab('overlay',this)">③ 疊加圖</button>
      <button class="tab-btn"        onclick="showTab('returnIdx',this)">④ CB報酬指數</button>
    </div>
    <div class="chart-area">
      <div id="breadth" class="chart-panel active"><div id="plt-breadth"></div></div>
      <div id="premium" class="chart-panel">       <div id="plt-premium"></div></div>
      <div id="overlay" class="chart-panel">
        <div class="overlay-tools">
          <label>左軸
            <select id="ov-left-axis" onchange="updateOverlayAxis('left',this.value)">
              <option value="premium" selected>溢價率</option>
              <option value="price">收盤價</option>
              <option value="return">報酬指數</option>
            </select>
          </label>
          <label>右軸
            <select id="ov-right-axis" onchange="updateOverlayAxis('right',this.value)">
              <option value="premium">溢價率</option>
              <option value="price" selected>收盤價</option>
              <option value="return">報酬指數</option>
            </select>
          </label>
          <label><input type="checkbox" id="ov-prem-med" checked onchange="updateOverlayLine('premMed',this.checked)">溢價中位</label>
          <label><input type="checkbox" id="ov-prem-mean" checked onchange="updateOverlayLine('premMean',this.checked)">溢價平均</label>
          <label><input type="checkbox" id="ov-price-med" checked onchange="updateOverlayLine('priceMed',this.checked)">收盤中位</label>
          <label><input type="checkbox" id="ov-price-mean" checked onchange="updateOverlayLine('priceMean',this.checked)">收盤平均</label>
          <label><input type="checkbox" id="ov-ret-eq" checked onchange="updateOverlayLine('retEq',this.checked)">平均報酬</label>
          <label><input type="checkbox" id="ov-ret-size" checked onchange="updateOverlayLine('retSize',this.checked)">規模加權報酬</label>
        </div>
        <div id="plt-overlay" class="overlay-plot"></div>
      </div>
      <div id="returnIdx" class="chart-panel">    <div id="plt-return"></div></div>
      <div class="hint">
        💡 移至圖表顯示十字線報價 ・ 滾輪縮放 ・ 拖曳平移 ・ 雙擊還原 ・ 底部捲軸瀏覽歷史
      </div>
    </div>
  </div>
</div>

<script>
// ══ Embedded data ══════════════════════════════════════════════════════════
const _RAW      = __RAW_JSON__;
const _DEFAULTS = __DEFAULTS_JSON__;

// Pre-index by date
const _by = Array.from({length:_RAW.dates.length}, ()=>[]);
for (const r of _RAW.rows) _by[r[0]].push(r);

// ══ Theme ══════════════════════════════════════════════════════════════════
const THEMES = {
  light: {
    paper:'#ffffff', plot:'#ffffff', grid:'#eeeeee', font:'#333333',
    hdrNote:'#555',
    c1:'#2196F3', c2:'#43A047', c3:'#E91E63', c4:'#9C27B0',
    bar:'rgba(200,200,200,0.35)',
    rangebg:'#e8eaf6', rangeActive:'#3f51b5',
    annColor:['red','goldenrod','#aaa'],
    refLine:['red','goldenrod','#aaa'],
    label:'🌙 Bloomberg',
  },
  bloomberg: {
    paper:'#0E1117', plot:'#0E1117', grid:'#1C2A38', font:'#C8C8C8',
    hdrNote:'#777',
    c1:'#00C8E8', c2:'#FF6B35', c3:'#7FFF00', c4:'#FFD700',
    bar:'rgba(0,200,232,0.12)',
    rangebg:'#1A1A1A', rangeActive:'#FF6600',
    annColor:['#FF4444','#FFC000','#666'],
    refLine:['#FF4444','#FFC000','#555'],
    label:'☀ 淺色',
  },
};
let _theme = 'light';

function cycleTheme() {
  _theme = _theme === 'light' ? 'bloomberg' : 'light';
  document.body.classList.toggle('bbg', _theme === 'bloomberg');
  document.getElementById('theme-btn').textContent = THEMES[_theme].label;
  applyFilters();
}

function T() { return THEMES[_theme]; }

// ══ Filters ════════════════════════════════════════════════════════════════
let cfg = Object.assign({}, _DEFAULTS);

function syncVal(key, val) { cfg[key] = val; }
function enterApply(e) { if (e.key === 'Enter') applyFilters(); }
function resetFilters() {
  cfg = Object.assign({}, _DEFAULTS);
  for (const k of Object.keys(_DEFAULTS)) {
    const el = document.getElementById('f-'+k);
    if (el) {
      if (el.type === 'checkbox') el.checked = _DEFAULTS[k];
      else el.value = _DEFAULTS[k];
    }
  }
  applyFilters();
}

// ══ Compute ════════════════════════════════════════════════════════════════
function median(a) {
  if (!a.length) return null;
  a.sort((x,y)=>x-y);
  const m=a.length;
  return m&1 ? a[m>>1] : (a[(m>>1)-1]+a[m>>1])/2;
}

function computeAll() {
  const N = _RAW.dates.length;
  const {
    useMaxPrice,maxPrice,useMinMaturity,minMaturity,
    useParityLo,parityLo,useParityHi,parityHi
  } = cfg;
  const bd=[],bMed=[],bMean=[],bCnt=[];
  const pd=[],pMed=[],pMean=[],pCnt=[];
  const rd=[],rEq=[],rSize=[],rCnt=[];
  const prevClose = new Map();
  let eqIdx=100, sizeIdx=100, started=false;

  for (let di=0;di<N;di++) {
    const rows=_by[di]; if(!rows.length) continue;
    const date=_RAW.dates[di];

    // Shared whole-market sample for breadth and premium.
    const bA=[], pA=[];
    let retSum=0, retN=0, retW=0, retWSum=0;
    const currentClose = [];
    for (const [,ci,c,u,,p,pa,dl,o] of rows) {
      if(u<=0) continue;
      const cl=c/10;
      currentClose.push([ci,cl]);
      const parity=pa/10;
      if(useMaxPrice && cl>=maxPrice) continue;
      if(useMinMaturity && dl>=0&&dl<=minMaturity) continue;
      if(useParityLo && parity<parityLo) continue;
      if(useParityHi && parity>parityHi) continue;
      bA.push(cl);
      if(p!==-9999) pA.push(p/10000);
      const prev = prevClose.get(ci);
      if(prev>0){
        const ret = cl/prev - 1;
        retSum += ret;
        retN += 1;
        const weight = o/10;
        if(weight>0){
          retW += ret*weight;
          retWSum += weight;
        }
      }
    }
    if(bA.length){
      bd.push(date); bCnt.push(bA.length);
      const s=bA.reduce((a,b)=>a+b,0); bMean.push(s/bA.length);
      bMed.push(median([...bA]));
    }
    if(pA.length){
      pd.push(date); pCnt.push(pA.length);
      const s=pA.reduce((a,b)=>a+b,0); pMean.push(s/pA.length);
      pMed.push(median([...pA]));
    }
    if(retN>0 && retWSum>0){
      const eqRet = retSum/retN;
      const sizeRet = retW/retWSum;
      if(started){
        eqIdx *= (1+eqRet);
        sizeIdx *= (1+sizeRet);
      } else {
        started = true;
      }
      rd.push(date); rEq.push(eqIdx); rSize.push(sizeIdx); rCnt.push(retN);
    }
    for(const [ci,cl] of currentClose) prevClose.set(ci,cl);
  }
  return {breadth:{dates:bd,median:bMed,mean:bMean,count:bCnt},
          premium:{dates:pd,median:pMed,mean:pMean,count:pCnt},
          returns:{dates:rd,equal:rEq,size:rSize,count:rCnt}};
}

// ══ Plotly helpers ══════════════════════════════════════════════════════════
const RS_BTN = (count,label,step,stepmode) => ({count,label,step,stepmode});
function rangeSelector(){
  return {buttons:[
    RS_BTN(3,'3M','month','backward'),
    RS_BTN(6,'6M','month','backward'),
    RS_BTN(1,'1Y','year', 'backward'),
    RS_BTN(3,'3Y','year', 'backward'),
    {step:'all',label:'全部'},
  ], bgcolor:T().rangebg, activecolor:T().rangeActive, font:{size:11,color:T().font}};
}
function xRange1Y(dates){
  const last=new Date(dates[dates.length-1]);
  const from=new Date(last); from.setFullYear(from.getFullYear()-1);
  return [from.toISOString().slice(0,10), last.toISOString().slice(0,10)];
}
function xAxis(dates){
  return { title:{text:'日期',font:{color:T().font}},
    rangeselector:rangeSelector(),
    rangeslider:{visible:true,thickness:.04,bgcolor:T().rangebg},
    range:xRange1Y(dates),
    showspikes:true,spikemode:'across',spikesnap:'cursor',
    spikecolor:T().c1,spikethickness:1,spikedash:'dot',
    color:T().font, gridcolor:T().grid, linecolor:T().grid,
    tickfont:{color:T().font}, titlefont:{color:T().font},
  };
}
function yAxis(title, side='left', overlay=null){
  return { title:{text:title,font:{color:T().font}},
    showgrid:side==='left', gridcolor:T().grid, zeroline:false,
    color:T().font, tickfont:{color:T().font},
    ...(overlay ? {overlaying:overlay,side} : {}),
  };
}
function premiumYAxis(){
  return Object.assign(yAxis('溢價率'), {tickformat:'.1%'});
}
function baseLayout(title, dates){
  return {
    title:{text:title, font:{size:14,color:T().font}},
    autosize:true,
    paper_bgcolor:T().paper, plot_bgcolor:T().plot,
    font:{color:T().font},
    hovermode:'x unified',
    legend:{orientation:'h',x:0.01,y:0.98,xanchor:'left',yanchor:'top',
            font:{color:T().font},bgcolor:T().paper,
            bordercolor:T().grid,borderwidth:1},
    margin:{l:60,r:65,t:45,b:10},
    xaxis:xAxis(dates),
    hoverlabel:{bgcolor:T().plot,bordercolor:T().c1,font:{color:T().font}},
  };
}
function refLine(y, color, yref='y'){ return {type:'line',xref:'paper',x0:0,x1:1,yref,y0:y,y1:y,
  line:{color,width:1,dash:'dot'}}; }
function annLabel(y, text, color, yref='y'){ return {xref:'paper',x:1.01,yref,y,
  text,showarrow:false,font:{size:9,color},xanchor:'left'}; }
const CFG = {responsive:true,displayModeBar:true,scrollZoom:true,
             modeBarButtonsToRemove:['lasso2d','select2d']};

// ══ Render ══════════════════════════════════════════════════════════════════
const overlayLines = {
  premMed:true,premMean:true,priceMed:true,priceMean:true,retEq:true,retSize:true
};
const overlayAxes = {left:'premium',right:'price'};

function renderBreadth(b){
  const traces=[
    {x:b.dates,y:b.median,name:'中位數 Median',type:'scatter',
     yaxis:'y2',line:{color:T().c1,width:2}},
    {x:b.dates,y:b.mean,  name:'平均數 Mean',  type:'scatter',
     yaxis:'y2',line:{color:T().c2,width:2}},
    {x:b.dates,y:b.count, name:'掛牌檔數',type:'bar',
     marker:{color:T().bar},hovertemplate:'%{y}檔<extra></extra>'},
  ];
  const [cHot,cWarm,cPar] = T().annColor;
  const layout=Object.assign(baseLayout('市場廣度指數 — 每日 CB 收盤價中位數 / 平均數',b.dates),{
    yaxis:  yAxis('掛牌檔數'),
    yaxis2: yAxis('收盤價 (每百元面額)','right','y'),
    shapes:[refLine(120,cHot,'y2'),refLine(110,cWarm,'y2'),refLine(100,cPar,'y2')],
    annotations:[annLabel(120,'120 過熱',cHot,'y2'),annLabel(110,'110 偏熱',cWarm,'y2'),
                 annLabel(100,'100 面額',cPar,'y2')],
  });
  Plotly.react('plt-breadth',traces,layout,CFG);
}

function renderPremium(p){
  const traces=[
    {x:p.dates,y:p.median,name:'中位數溢價率',type:'scatter',
     yaxis:'y2',line:{color:T().c4,width:2}},
    {x:p.dates,y:p.mean,name:'平均溢價率',type:'scatter',
     yaxis:'y2',line:{color:T().c2,width:2}},
    {x:p.dates,y:p.count,name:'有效檔數',type:'bar',
     marker:{color:T().bar},hovertemplate:'%{y}檔<extra></extra>'},
  ];
  const layout=Object.assign(baseLayout('全市場溢價率 — 每檔 CB 溢價率中位數 / 平均數',p.dates),{
    yaxis:  yAxis('有效檔數'),
    yaxis2: Object.assign(premiumYAxis(), {overlaying:'y', side:'right'}),
    shapes:[
      {type:'line',xref:'paper',x0:0,x1:1,yref:'y2',y0:0,y1:0,
       line:{color:T().font,width:1,dash:'dash'}},
      {type:'line',xref:'paper',x0:0,x1:1,yref:'y2',y0:0.1,y1:0.1,
       line:{color:T().annColor[1],width:1,dash:'dot'}},
    ],
  });
  Plotly.react('plt-premium',traces,layout,CFG);
}

function metricAxis(metric, side='left', overlay=null){
  if(metric==='premium') {
    const ax=premiumYAxis();
    return overlay ? Object.assign(ax,{overlaying:overlay,side}) : ax;
  }
  if(metric==='price') return yAxis('收盤價 (每百元面額)',side,overlay);
  return yAxis('報酬指數',side,overlay);
}
function metricTitle(metric){
  return metric==='premium' ? '溢價率' : metric==='price' ? '收盤價' : '報酬指數';
}
function addOverlayMetricTraces(traces, metric, axis, b, p, r){
  const yaxis = axis==='y2' ? 'y2' : undefined;
  if(metric==='premium'){
    if(overlayLines.premMed) traces.push({x:p.dates,y:p.median,name:'溢價率中位數',type:'scatter',
      yaxis,line:{color:T().c4,width:2}});
    if(overlayLines.premMean) traces.push({x:p.dates,y:p.mean,name:'溢價率平均數',type:'scatter',
      yaxis,line:{color:T().c2,width:2,dash:'dot'}});
  } else if(metric==='price'){
    if(overlayLines.priceMed) traces.push({x:b.dates,y:b.median,name:'收盤價中位數',type:'scatter',
      yaxis,line:{color:T().c1,width:2}});
    if(overlayLines.priceMean) traces.push({x:b.dates,y:b.mean,name:'收盤價平均數',type:'scatter',
      yaxis,line:{color:T().c3,width:2,dash:'dot'}});
  } else {
    if(overlayLines.retEq) traces.push({x:r.dates,y:r.equal,name:'平均報酬指數',type:'scatter',
      yaxis,line:{color:'#009688',width:2}});
    if(overlayLines.retSize) traces.push({x:r.dates,y:r.size,name:'規模加權報酬指數',type:'scatter',
      yaxis,line:{color:'#FF3366',width:2,dash:'dot'}});
  }
}
function renderOverlay(b,p,r){
  const dates = [...new Set([...b.dates, ...p.dates, ...r.dates])].sort();
  const traces=[];
  addOverlayMetricTraces(traces,overlayAxes.left,'y',b,p,r);
  addOverlayMetricTraces(traces,overlayAxes.right,'y2',b,p,r);
  const shapes=[];
  if(overlayAxes.left==='premium') shapes.push(
    {type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:0,y1:0,
     line:{color:T().font,width:1,dash:'dash'}});
  if(overlayAxes.right==='premium') shapes.push(
    {type:'line',xref:'paper',x0:0,x1:1,yref:'y2',y0:0,y1:0,
     line:{color:T().font,width:1,dash:'dash'}});
  if(overlayAxes.left==='price'||overlayAxes.left==='return') shapes.push(refLine(100,T().annColor[2],'y'));
  if(overlayAxes.right==='price'||overlayAxes.right==='return') shapes.push(refLine(100,T().annColor[2],'y2'));
  const layout=Object.assign(baseLayout(`疊加圖 — ${metricTitle(overlayAxes.left)} vs ${metricTitle(overlayAxes.right)}`,dates),{
    yaxis:  metricAxis(overlayAxes.left),
    yaxis2: metricAxis(overlayAxes.right,'right','y'),
    shapes,
  });
  Plotly.react('plt-overlay',traces,layout,CFG);
}

function renderReturnIndex(r){
  const traces=[
    {x:r.dates,y:r.count,name:'有效報酬檔數',type:'bar',
     marker:{color:T().bar},hovertemplate:'%{y}檔<extra></extra>'},
    {x:r.dates,y:r.equal.map(v=>v/100-1),name:'平均累積報酬率',type:'scatter',yaxis:'y2',
     line:{color:T().c1,width:2}},
    {x:r.dates,y:r.size.map(v=>v/100-1),name:'發行規模加權累積報酬率',type:'scatter',yaxis:'y2',
     line:{color:T().c3,width:2}},
  ];
  const layout=Object.assign(baseLayout('CB 累積報酬率 — 平均 vs 發行規模加權',r.dates),{
    yaxis:  yAxis('有效報酬檔數'),
    yaxis2: Object.assign(yAxis('累積報酬率','right','y'), {tickformat:'.1%'}),
    shapes:[refLine(0,T().annColor[2],'y2')],
  });
  Plotly.react('plt-return',traces,layout,CFG);
}

function updateOverlayLine(key, checked){
  overlayLines[key]=checked;
  if(_lastIdx) {
    renderOverlay(_lastIdx.breadth,_lastIdx.premium,_lastIdx.returns);
    setTimeout(resizeActive,30);
  }
}
function updateOverlayAxis(side, metric){
  const other = side==='left' ? 'right' : 'left';
  if(metric===overlayAxes[other]){
    const select = document.getElementById(side==='left' ? 'ov-left-axis' : 'ov-right-axis');
    if(select) select.value = overlayAxes[side];
    return;
  }
  overlayAxes[side]=metric;
  if(_lastIdx) {
    renderOverlay(_lastIdx.breadth,_lastIdx.premium,_lastIdx.returns);
    setTimeout(resizeActive,30);
  }
}

// ══ UI wiring ═══════════════════════════════════════════════════════════════
let _lastIdx = null;

function applyFilters(){
  const t0=performance.now();
  _lastIdx=computeAll();
  renderBreadth(_lastIdx.breadth);
  renderPremium(_lastIdx.premium);
  renderOverlay(_lastIdx.breadth,_lastIdx.premium,_lastIdx.returns);
  renderReturnIndex(_lastIdx.returns);
  const ms=(performance.now()-t0).toFixed(0);
  document.getElementById('f-status').textContent=
    `${ms}ms · 廣度${_lastIdx.breadth.dates.length}天 溢價${_lastIdx.premium.dates.length}天 報酬${_lastIdx.returns.dates.length}天`;
  const b=_lastIdx.breadth, last=b.dates[b.dates.length-1]||'';
  const med=b.median[b.median.length-1], cnt=b.count[b.count.length-1];
  document.getElementById('hdr-params').textContent=
    `最新 ${last}  中位數 ${med?med.toFixed(1):'-'}  掛牌有量 ${cnt||0} 檔`;
  setTimeout(resizeAll,50);
}

function getChartSize(){
  const area=document.querySelector('.chart-area');
  const hint=document.querySelector('.hint');
  const w=Math.max(300,(area?.clientWidth||800)-4);
  const h=Math.max(250,(area?.clientHeight||500)-(hint?.offsetHeight||20)-6);
  return {w,h};
}
// Resize every chart div (including hidden panels) so they're correct when revealed
function resizeAll(){
  const {w,h}=getChartSize();
  document.querySelectorAll('.js-plotly-plot').forEach(d=>
    Plotly.relayout(d,{width:w, height:h})
  );
}
function resizeActive(){
  const {w,h}=getChartSize();
  const panel=document.querySelector('.chart-panel.active');
  if(!panel) return;
  panel.querySelectorAll('.js-plotly-plot').forEach(d=>
    Plotly.relayout(d,{width:w, height:h})
  );
}
function showTab(id,btn){
  document.querySelectorAll('.chart-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
  setTimeout(resizeActive,30);
}
function toggleDrawer(){
  document.getElementById('filter-drawer').classList.toggle('open');
  setTimeout(resizeAll,280);
}
window.addEventListener('resize',resizeAll);
window.addEventListener('load',()=>{ applyFilters(); setTimeout(resizeAll,200); });
</script>
</body>
</html>
"""

# ── Generate HTML ─────────────────────────────────────────────────────────────
def make_html(raw_json: str) -> str:
    defaults_json = json.dumps(DEFAULTS, separators=(",",":"))
    html = _HTML.replace("__RAW_JSON__", raw_json) \
                .replace("__DEFAULTS_JSON__", defaults_json)
    for k, v in DEFAULTS.items():
        html = html.replace(f"__{k}__", str(v))
    return html


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    p("Loading data …")
    raw = load_data()
    p(f"  {len(raw):,} rows | {raw['cb_id'].nunique():,} CBs | {raw['date'].nunique():,} dates  ({time.time()-t0:.1f}s)")
    p("Computing features …")
    df = compute_features(raw)
    df = embed_filter(df)
    p(f"  After filter: {len(df):,} rows  ({time.time()-t0:.1f}s)")
    p("Serialising embed data …")
    raw_json = prepare_raw_json(df)
    p(f"  JSON {len(raw_json)/1024/1024:.1f} MB  ({time.time()-t0:.1f}s)")
    p("Building HTML …")
    html = make_html(raw_json)
    out = OUTPUT_DIR / "cb_indices.html"
    out.write_text(html, encoding="utf-8")
    p(f"  → {out}  ({time.time()-t0:.1f}s)  file: {out.stat().st_size/1024/1024:.1f} MB")
    p("Done.")

if __name__ == "__main__":
    main()
