"""A self-contained monitoring dashboard: one HTML file, no build, no server.

The React dashboard in dashboard/ reads a live FastAPI + SQLite backend. The
GitHub Action has neither — it is stateless — so this renders a single static
HTML page that fetches a history.json (produced by `docsentry run --history`)
and draws the same monitoring view entirely client-side. It works on GitHub
Pages, on any static host, or opened straight off disk.

`render_dashboard(history_url)` returns the HTML with the data source injected.
"""
from __future__ import annotations

_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="color-scheme" content="dark light" />
<title>DocSentry — Monitor</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🛡️</text></svg>" />
<style>
:root{
  --bg:#0b0f14;--surface:#111823;--surface2:#172232;--surface3:#1e2c3f;
  --border:#24344a;--border-soft:#1a2635;--text:#e8edf4;--dim:#94a3b8;--faint:#64748b;
  --accent:#5b9dff;--accent-soft:rgba(91,157,255,.14);
  --fixed-fg:#6ee7a8;--fixed-bg:rgba(16,122,76,.18);--fixed-line:#10b981;
  --alert-fg:#fbbf72;--alert-bg:rgba(146,74,18,.20);--alert-line:#f59e0b;
  --clean-fg:#7cc0ff;--clean-bg:rgba(23,74,138,.20);--clean-line:#3b82f6;
  --esc-fg:#fde68a;--esc-bg:rgba(120,90,12,.22);--esc-line:#eab308;
  --skip-fg:#a3aec0;--skip-bg:rgba(71,85,105,.22);--skip-line:#64748b;
  --err-fg:#fca5a5;--err-bg:rgba(140,30,30,.22);--err-line:#ef4444;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --radius:12px;--shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.28);
}
:root[data-theme="light"]{
  --bg:#f6f8fb;--surface:#fff;--surface2:#f1f5f9;--surface3:#e2e8f0;
  --border:#dbe3ec;--border-soft:#e8eef5;--text:#0f1b2d;--dim:#556781;--faint:#8496ae;
  --accent:#1d6ff2;--accent-soft:rgba(29,111,242,.10);
  --fixed-fg:#05713f;--fixed-bg:rgba(16,185,129,.14);
  --alert-fg:#92400e;--alert-bg:rgba(245,158,11,.16);
  --clean-fg:#10499b;--clean-bg:rgba(59,130,246,.13);
  --esc-fg:#78560c;--esc-bg:rgba(234,179,8,.18);
  --skip-fg:#475569;--skip-bg:rgba(100,116,139,.14);
  --err-fg:#991b1b;--err-bg:rgba(239,68,68,.13);--shadow:0 1px 2px rgba(15,27,45,.06),0 8px 24px rgba(15,27,45,.08);
}
@media (prefers-color-scheme:light){:root:not([data-theme]){
  --bg:#f6f8fb;--surface:#fff;--surface2:#f1f5f9;--surface3:#e2e8f0;--border:#dbe3ec;
  --border-soft:#e8eef5;--text:#0f1b2d;--dim:#556781;--faint:#8496ae;--accent:#1d6ff2;
  --accent-soft:rgba(29,111,242,.10);--fixed-fg:#05713f;--fixed-bg:rgba(16,185,129,.14);
  --alert-fg:#92400e;--alert-bg:rgba(245,158,11,.16);--clean-fg:#10499b;--clean-bg:rgba(59,130,246,.13);
  --esc-fg:#78560c;--esc-bg:rgba(234,179,8,.18);--skip-fg:#475569;--skip-bg:rgba(100,116,139,.14);
  --err-fg:#991b1b;--err-bg:rgba(239,68,68,.13);
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.shell{max-width:1000px;margin:0 auto;padding:28px 20px 80px}
code{font-family:var(--mono)}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
button{font:inherit;color:inherit;cursor:pointer}
.mast{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:22px}
.brand{display:flex;align-items:center;gap:12px}
.brand .mk{font-size:30px}
.brand h1{margin:0;font-size:24px;font-weight:750;letter-spacing:-.5px}
.brand p{margin:2px 0 0;font-size:13px;color:var(--dim)}
.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.pill{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;border:1px solid var(--border);background:var(--surface);font-size:12.5px;font-weight:550}
.dot{width:7px;height:7px;border-radius:50%;background:var(--faint)}
.dot-ok{background:var(--fixed-line);box-shadow:0 0 0 3px var(--fixed-bg)}
.dot-warn{background:var(--alert-line);box-shadow:0 0 0 3px var(--alert-bg)}
.dot-err{background:var(--err-line);box-shadow:0 0 0 3px var(--err-bg)}
.btn{display:inline-flex;align-items:center;gap:7px;padding:7px 12px;border-radius:8px;border:1px solid var(--border);background:var(--surface);font-size:13.5px;font-weight:550}
.btn:hover{background:var(--surface2);border-color:var(--faint)}
.btn-icon{padding:7px 9px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-bottom:18px}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 15px;position:relative;overflow:hidden;text-align:left}
.stat[data-clickable]{cursor:pointer}
.stat[data-clickable]:hover{border-color:var(--faint);transform:translateY(-1px)}
.stat[aria-pressed="true"]{border-color:var(--accent);background:var(--accent-soft)}
.stat::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--rail,transparent)}
.stat .v{font-size:26px;font-weight:750;letter-spacing:-.6px;line-height:1.15}
.stat .l{font-size:12.5px;color:var(--dim);margin-top:2px}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px;margin-bottom:16px;box-shadow:var(--shadow)}
.filters{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.input{padding:7px 11px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:13.5px}
.input:focus{border-color:var(--accent);outline:none}
.search{position:relative;flex:1;min-width:180px}
.search .input{width:100%;padding-left:30px}
.search .i{position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--faint)}
.grow{flex:1}.spacer{flex:1}.muted{color:var(--dim)}.small{font-size:13px}.tiny{font-size:12px}.faint{color:var(--faint)}
.run{background:var(--surface);border:1px solid var(--border);border-left-width:3px;border-radius:var(--radius);margin-bottom:12px;overflow:hidden;box-shadow:var(--shadow)}
.rhead{display:flex;align-items:center;gap:11px;padding:13px 15px;width:100%;background:none;border:none;text-align:left}
.rhead:hover{background:var(--surface2)}
.chev{color:var(--faint);transition:transform .18s;font-size:11px}
.chev.open{transform:rotate(90deg)}
.sha{font-family:var(--mono);font-size:12.5px;background:var(--surface2);border:1px solid var(--border-soft);padding:2px 7px;border-radius:5px;color:var(--dim)}
.truncate{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rbody{border-top:1px solid var(--border-soft);padding:4px 15px 12px}
.badge{display:inline-flex;align-items:center;padding:2.5px 9px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.04em;white-space:nowrap}
.badge.mini{font-size:10px;padding:1px 6px}
.b-auto_fixed{color:var(--fixed-fg);background:var(--fixed-bg)}
.b-alerted{color:var(--alert-fg);background:var(--alert-bg)}
.b-clean{color:var(--clean-fg);background:var(--clean-bg)}
.b-fix_failed_verification{color:var(--esc-fg);background:var(--esc-bg)}
.b-skip,.b-low_confidence_skip,.b-no_semantic_changes,.b-no_linked_docs,.b-no_docs_indexed{color:var(--skip-fg);background:var(--skip-bg)}
.b-error{color:var(--err-fg);background:var(--err-bg)}
.finding{display:flex;gap:11px;padding:10px 0;border-bottom:1px solid var(--border-soft);align-items:flex-start}
.finding:last-child{border-bottom:none}
.fmain{flex:1;min-width:0}
.fdetail{font-size:13.5px}
.fdetail code{background:var(--surface2);padding:1px 5px;border-radius:4px;font-size:12.5px;border:1px solid var(--border-soft)}
.fmeta{font-size:12px;color:var(--faint);margin-top:3px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.fmis{font-size:13px;color:var(--dim);margin-top:5px;padding-left:9px;border-left:2px solid var(--border)}
.conf{display:flex;align-items:center;gap:6px}
.cbar{width:40px;height:4px;background:var(--surface3);border-radius:999px;overflow:hidden}
.cfill{height:100%;border-radius:999px}
.ctext{font-family:var(--mono);font-size:11.5px;color:var(--dim);min-width:30px}
.fixbtn{background:none;border:none;color:var(--accent);font-size:12px;padding:2px 0;margin-top:4px}
pre.fix{margin:6px 0 2px;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;font-size:12px;overflow-x:auto;white-space:pre;color:var(--dim)}
.empty{text-align:center;padding:56px 20px;color:var(--dim)}
.empty .mk{font-size:38px;margin-bottom:10px;opacity:.55}
.empty h3{margin:0 0 6px;font-size:16px;color:var(--text)}
.banner{display:flex;gap:10px;padding:11px 14px;border-radius:8px;font-size:13.5px;margin-bottom:16px;border:1px solid}
.banner.err{background:var(--err-bg);border-color:var(--err-line);color:var(--err-fg)}
.footer{margin-top:32px;padding-top:16px;border-top:1px solid var(--border-soft);font-size:12.5px;color:var(--faint);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.rmeta{font-size:12px;color:var(--faint);margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}
</style>
</head>
<body>
<div class="shell">
  <div class="mast">
    <div class="brand">
      <span class="mk">🛡️</span>
      <div><h1>DocSentry</h1><p>Documentation drift, monitored.</p></div>
    </div>
    <div class="actions">
      <span class="pill" id="status"><span class="dot" id="statusDot"></span><span id="statusText">loading…</span></span>
      <a class="pill" id="repoPill" style="display:none;color:inherit" target="_blank" rel="noreferrer"><span>⎇</span><span id="repoName"></span></a>
      <select class="input" id="refresh" title="Auto-refresh">
        <option value="0">↻ Off</option><option value="15">↻ 15s</option>
        <option value="30" selected>↻ 30s</option><option value="60">↻ 1m</option>
      </select>
      <button class="btn btn-icon" id="theme" title="Toggle theme">◐</button>
      <button class="btn" id="reload">Refresh</button>
    </div>
  </div>

  <div id="err"></div>
  <div class="stats" id="stats"></div>

  <div class="panel">
    <div class="filters">
      <div class="search"><span class="i">⌕</span><input class="input" id="q" placeholder="Search commits, files, findings…" /></div>
      <select class="input" id="statusFilter"><option value="">All statuses</option></select>
      <button class="btn" id="clearFilters" style="display:none">Clear filters</button>
      <span class="spacer"></span>
      <span class="small muted" id="count"></span>
    </div>
  </div>

  <div id="runs"></div>

  <div class="footer">
    <span id="foot">—</span>
    <span><a href="https://github.com/mannas632006/DocSentry-_-Keepin-It-Real" target="_blank" rel="noreferrer">DocSentry</a></span>
  </div>
</div>

<script>
const HISTORY_URL = "__HISTORY_URL__";
const STATUS = {
  auto_fixed:{label:"AUTO-FIXED",rail:"var(--fixed-line)"},
  alerted:{label:"ALERT",rail:"var(--alert-line)"},
  fix_failed_verification:{label:"ESCALATED",rail:"var(--esc-line)"},
  clean:{label:"CLEAN",rail:"var(--clean-line)"},
  low_confidence_skip:{label:"SKIPPED",rail:"var(--skip-line)"},
  no_semantic_changes:{label:"NO CHANGES",rail:"var(--skip-line)"},
  no_linked_docs:{label:"NO DOCS",rail:"var(--skip-line)"},
  no_docs_indexed:{label:"NO DOCS",rail:"var(--skip-line)"},
  error:{label:"ERROR",rail:"var(--err-line)"},
};
const info = s => STATUS[s] || {label:(s||"?").toUpperCase().replace(/_/g," "),rail:"var(--skip-line)"};
const PRECEDENCE = ["error","auto_fixed","fix_failed_verification","alerted","low_confidence_skip","clean"];
const esc = s => String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const code = s => esc(s).replace(/`([^`]+)`/g,"<code>$1</code>");
const badgeClass = s => STATUS[s]?("b-"+s):"b-skip";
function ago(ts){ if(!ts)return"never"; const d=Math.floor(Date.now()/1000-ts);
  if(d<60)return d+"s ago"; if(d<3600)return Math.floor(d/60)+"m ago";
  if(d<86400)return Math.floor(d/3600)+"h ago"; if(d<2592000)return Math.floor(d/86400)+"d ago";
  return new Date(ts*1000).toLocaleDateString(); }
const full = ts => ts?new Date(ts*1000).toLocaleString():"";
const confColor = c => c>=.85?"var(--fixed-line)":c>=.5?"var(--alert-line)":"var(--skip-line)";

let ALL=[], expanded=new Set(), filterStatus="", query="", generatedAt=null;

function docLink(repo, commit, doc){
  if(!repo||!doc||!doc.file)return null;
  const ref=commit||"HEAD";
  const ln=doc.start_line?("#L"+doc.start_line+(doc.end_line>doc.start_line?"-L"+doc.end_line:"")):"";
  return `https://github.com/${repo}/blob/${ref}/${doc.file}${ln}`;
}
function headline(results){ for(const s of PRECEDENCE){ if(results.some(r=>r.status===s))return s; } return results[0]?results[0].status:"clean"; }

function computeStats(runs){
  const c={total_runs:runs.length,auto_fixed:0,alerted:0,fix_failed_verification:0,clean:0,low_confidence_skip:0};
  for(const run of runs) for(const f of (run.results||[])) if(f.status in c) c[f.status]++;
  return c;
}
function matches(run){
  if(filterStatus && !(run.results||[]).some(r=>r.status===filterStatus)) return false;
  if(query){ const q=query.toLowerCase();
    const hay=[run.commit,run.commit_msg,...(run.results||[]).flatMap(r=>[r.change&&r.change.detail,r.doc&&r.doc.file,r.doc&&r.doc.heading,r.mismatch])].filter(Boolean).join(" ").toLowerCase();
    if(!hay.includes(q)) return false; }
  return true;
}

function renderStats(runs){
  const s=computeStats(runs);
  const cards=[["total_runs","Runs",null,"var(--accent)"],["auto_fixed","Auto-fixed","auto_fixed",info("auto_fixed").rail],
    ["alerted","Alerts","alerted",info("alerted").rail],["fix_failed_verification","Escalated","fix_failed_verification",info("fix_failed_verification").rail],
    ["clean","Clean","clean",info("clean").rail],["low_confidence_skip","Skipped","low_confidence_skip",info("low_confidence_skip").rail]];
  document.getElementById("stats").innerHTML = cards.map(([k,l,st,rail])=>{
    const active=st&&filterStatus===st;
    return `<button class="stat" style="--rail:${rail}" ${st?'data-clickable':''} aria-pressed="${active}" data-status="${st||''}"><div class="v">${s[k]||0}</div><div class="l">${l}</div></button>`;
  }).join("");
  document.querySelectorAll(".stat[data-clickable]").forEach(el=>el.onclick=()=>{
    const st=el.dataset.status; filterStatus=(filterStatus===st?"":st); render();
  });
}

function renderFinding(f, repo, commit){
  const detail = (f.change&&f.change.detail) || f.mismatch || info(f.status).label;
  const href = docLink(repo, commit, f.doc);
  const docStr = f.doc&&f.doc.file ? (f.doc.file + (f.doc.heading?` § ${f.doc.heading}`:"") + (f.doc.start_line?`:${f.doc.start_line}`:"")) : "";
  const dry = f.url && f.url.indexOf("dry-run://")===0;
  let right="";
  if(dry) right=`<span class="badge mini b-skip" title="dry run">DRY RUN</span>`;
  else if(f.url) right=`<a class="small" href="${esc(f.url)}" target="_blank" rel="noreferrer">view →</a>`;
  const conf = f.confidence>0 ? `<div class="conf" title="confidence ${(f.confidence*100).toFixed(0)}%"><div class="cbar"><div class="cfill" style="width:${Math.round(f.confidence*100)}%;background:${confColor(f.confidence)}"></div></div><span class="ctext">${(f.confidence*100).toFixed(0)}%</span></div>` : "";
  const fixId = "fix"+Math.random().toString(36).slice(2);
  const fix = f.suggested_fix ? `<button class="fixbtn" onclick="var e=document.getElementById('${fixId}');e.style.display=e.style.display==='none'?'block':'none'">Toggle suggested fix</button><pre class="fix" id="${fixId}" style="display:none">${esc(f.suggested_fix)}</pre>` : "";
  return `<div class="finding">
    <span class="badge ${badgeClass(f.status)}">${info(f.status).label}</span>
    <div class="fmain">
      <div class="fdetail">${code(detail)}</div>
      ${(f.change&&f.change.file)||docStr?`<div class="fmeta">${f.change&&f.change.file?`<span class="mono">${esc(f.change.file)}</span>`:""}${docStr?`<span>→</span>${href?`<a class="mono" href="${esc(href)}" target="_blank" rel="noreferrer">${esc(docStr)}</a>`:`<span class="mono">${esc(docStr)}</span>`}`:""}${f.change&&f.change.kind?`<span class="badge mini b-skip">${esc(f.change.kind.replace(/_/g," "))}</span>`:""}</div>`:""}
      ${f.mismatch&&f.change&&f.change.detail?`<div class="fmis">${esc(f.mismatch)}</div>`:""}
      ${fix}
    </div>
    ${conf}${right}
  </div>`;
}

function renderRun(run){
  const results=run.results||[];
  const top=headline(results), open=expanded.has(run.id);
  const counts={}; for(const r of results) counts[r.status]=(counts[r.status]||0)+1;
  const chips=Object.entries(counts).map(([s,n])=>`<span class="badge mini ${badgeClass(s)}">${info(s).label}${n>1?" ×"+n:""}</span>`).join("");
  const body = open ? `<div class="rbody">
    ${run.error?`<div class="banner err" style="margin-top:10px"><span>⚠</span><div><b>Run failed:</b> ${esc(run.error)}</div></div>`:""}
    ${results.length===0&&!run.error?`<p class="small muted" style="padding:8px 0">No findings recorded.</p>`:""}
    ${results.map(f=>renderFinding(f,run.repo,run.commit)).join("")}
    <div class="rmeta"><span>${full(run.ts)}</span>${run.duration_ms?`<span>· ${(run.duration_ms/1000).toFixed(1)}s</span>`:""}<span>· ${esc(run.trigger||"run")}</span></div>
  </div>`:"";
  return `<div class="run" style="border-left-color:${info(top).rail}">
    <button class="rhead" data-id="${run.id}">
      <span class="chev ${open?'open':''}">▶</span>
      <span class="sha" title="${esc(run.commit)}">${esc((run.commit||"").slice(0,7)||"—")}</span>
      <span class="grow truncate">${esc(run.commit_msg||"")||'<span class="faint">no message</span>'}</span>
      ${run.dry_run?`<span class="badge mini b-skip">DRY RUN</span>`:""}
      ${chips}
      <span class="tiny faint" title="${full(run.ts)}">${ago(run.ts)}</span>
    </button>${body}</div>`;
}

function render(){
  const runs=[...ALL].sort((a,b)=>(b.ts||0)-(a.ts||0));
  renderStats(runs);
  const filtered=runs.filter(matches);
  const filtering = filterStatus||query;
  document.getElementById("clearFilters").style.display = filtering?"":"none";
  document.getElementById("count").textContent = `${filtered.length} run${filtered.length===1?"":"s"}${filtering?" matching":""}`;
  const el=document.getElementById("runs");
  if(filtered.length===0){
    el.innerHTML=`<div class="run"><div class="empty"><div class="mk">${filtering?"⌕":"🛡️"}</div><h3>${filtering?"Nothing matches":"No runs yet"}</h3><p class="small">${filtering?"Try clearing the filters.":"Push a commit to the watched repo — runs appear here."}</p></div></div>`;
  } else {
    el.innerHTML=filtered.map(renderRun).join("");
    el.querySelectorAll(".rhead").forEach(b=>b.onclick=()=>{ const id=+b.dataset.id; expanded.has(id)?expanded.delete(id):expanded.add(id); render(); });
  }
  // status filter dropdown options
  const sf=document.getElementById("statusFilter");
  if(sf.options.length<=1){ for(const s of ["auto_fixed","alerted","fix_failed_verification","clean","low_confidence_skip","error"]){ const o=document.createElement("option"); o.value=s; o.textContent=info(s).label; sf.appendChild(o);} }
  sf.value=filterStatus;
}

async function load(quiet){
  const dot=document.getElementById("statusDot"), txt=document.getElementById("statusText");
  try{
    const res=await fetch(HISTORY_URL+(HISTORY_URL.includes("?")?"&":"?")+"_="+Date.now(),{cache:"no-store"});
    if(!res.ok) throw new Error("HTTP "+res.status);
    const data=await res.json();
    ALL=(data.runs||data||[]).filter(r=>r&&typeof r==="object");
    if(!ALL.every(r=>"id"in r)) ALL=ALL.map((r,i)=>({id:r.id!=null?r.id:i, ...r}));
    generatedAt=data.generated_at||null;
    const repo=(ALL.find(r=>r.repo)||{}).repo;
    if(repo){ const rp=document.getElementById("repoPill"); rp.style.display=""; rp.href="https://github.com/"+repo; document.getElementById("repoName").textContent=repo; }
    dot.className="dot dot-ok"; txt.textContent=ALL.length+" run"+(ALL.length===1?"":"s");
    document.getElementById("err").innerHTML="";
    document.getElementById("foot").textContent = "Updated "+(generatedAt?ago(generatedAt):"now")+(ALL.length?" · latest run "+ago(ALL.slice().sort((a,b)=>(b.ts||0)-(a.ts||0))[0].ts):"");
    render();
  }catch(e){
    dot.className="dot dot-err"; txt.textContent="no data";
    if(!quiet||ALL.length===0){
      document.getElementById("err").innerHTML=`<div class="banner err"><span>⚠</span><div><b>Couldn't load history</b> from <code>${esc(HISTORY_URL)}</code> — ${esc(e.message)}.<div class="tiny" style="margin-top:4px">If this is a fresh setup, the first run hasn't published history yet.</div></div></div>`;
    }
  }
}

// theme
(function(){ try{const t=localStorage.getItem("ds.theme"); if(t)document.documentElement.setAttribute("data-theme",t);}catch(e){} })();
document.getElementById("theme").onclick=()=>{
  const cur=document.documentElement.getAttribute("data-theme");
  const next=cur==="dark"?"light":cur==="light"?"":"dark";
  if(next)document.documentElement.setAttribute("data-theme",next); else document.documentElement.removeAttribute("data-theme");
  try{next?localStorage.setItem("ds.theme",next):localStorage.removeItem("ds.theme");}catch(e){}
};
document.getElementById("q").oninput=e=>{query=e.target.value;render();};
document.getElementById("statusFilter").onchange=e=>{filterStatus=e.target.value;render();};
document.getElementById("clearFilters").onclick=()=>{filterStatus="";query="";document.getElementById("q").value="";render();};
document.getElementById("reload").onclick=()=>load(false);
let timer=null;
function schedule(){ if(timer)clearInterval(timer); const s=+document.getElementById("refresh").value; if(s)timer=setInterval(()=>load(true),s*1000); }
document.getElementById("refresh").onchange=schedule;
load(false); schedule();
</script>
</body>
</html>
"""


def render_dashboard(history_url: str = "history.json") -> str:
    """Return the standalone dashboard HTML, pointed at history_url."""
    # Replace, not format: the template is full of literal braces (CSS/JS).
    return _TEMPLATE.replace("__HISTORY_URL__", history_url)
