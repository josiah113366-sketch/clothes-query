"""시뮬레이터 콘솔 화면 (HTML 한 장, 외부 스크립트·CDN·폰트 없음). 설치본에 함께 들어가도록 모듈 문자열로 둔다.

토큰은 화면 메모리에만 둔다(저장하지 않는다). 그래프 기록은 서버(/api/traffic)가 들고 있다.
"""

PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>시뮬레이터 콘솔</title>
<style>
:root {
  --bg: #090b10; --bg2: #0f1219; --panel: rgba(255,255,255,.035); --panel-hi: rgba(255,255,255,.06);
  --line: rgba(255,255,255,.08); --line-hi: rgba(255,255,255,.16);
  --text: #e9ecf3; --muted: #8a93a8; --faint: #5b6377;
  --cyan: #4cc9f0; --green: #3ddc97; --amber: #ffb020; --red: #ff5d73; --violet: #a594ff;
  --mode: var(--green); --mode-glow: rgba(61,220,151,.18);
  --radius: 16px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", system-ui, sans-serif;
  color-scheme: dark;
}
body[data-mode="medium"] { --mode: var(--amber); --mode-glow: rgba(255,176,32,.18); }
body[data-mode="burst"]  { --mode: var(--red);   --mode-glow: rgba(255,93,115,.24); }
body[data-running="false"] { --mode: var(--muted); --mode-glow: rgba(138,147,168,.10); }
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  background: var(--bg); color: var(--text); min-height: 100vh; overflow-x: hidden;
  font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased;
}
body::before {
  content: ""; position: fixed; inset: -20% -10% auto -10%; height: 70vh; z-index: -1; pointer-events: none;
  background: radial-gradient(60% 60% at 50% 0%, var(--mode-glow), transparent 70%);
  transition: background .8s ease;
}
body[data-mode="burst"][data-running="true"]::before { animation: breathe 2.4s ease-in-out infinite; }
@keyframes breathe { 50% { opacity: .45; } }
.wrap { max-width: 1280px; margin: 0 auto; padding: 16px; }

/* 헤더 */
header { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding: 6px 0 18px; }
.brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 18px; letter-spacing: -.2px; }
.live { display: inline-flex; align-items: center; gap: 7px; font-size: 11px; font-weight: 700; letter-spacing: 1.4px;
  padding: 4px 10px; border-radius: 99px; background: var(--panel); border: 1px solid var(--line); color: var(--muted); }
.live i { width: 8px; height: 8px; border-radius: 50%; background: var(--faint); }
.live.on { color: var(--green); } .live.on i { background: var(--green); box-shadow: 0 0 0 0 rgba(61,220,151,.7); animation: ping 1.6s infinite; }
.live.off { color: var(--red); } .live.off i { background: var(--red); }
@keyframes ping { 70% { box-shadow: 0 0 0 8px rgba(61,220,151,0); } 100% { box-shadow: 0 0 0 0 rgba(61,220,151,0); } }
.simclock { color: var(--muted); font-size: 13px; }
.spacer { flex: 1; }

.seg { position: relative; display: inline-flex; padding: 4px; border-radius: 12px; background: var(--panel); border: 1px solid var(--line); }
.seg button { position: relative; z-index: 1; border: 0; background: none; color: var(--muted); font: inherit; font-size: 13px; font-weight: 600;
  padding: 7px 14px; border-radius: 9px; cursor: pointer; transition: color .25s; }
.seg button.active { color: #0b0d12; }
.seg .thumb { position: absolute; top: 4px; bottom: 4px; border-radius: 9px; background: var(--mode);
  box-shadow: 0 4px 18px var(--mode-glow); transition: left .35s cubic-bezier(.3,1.4,.5,1), width .35s, background .4s; }
.switch { display: inline-flex; align-items: center; gap: 9px; cursor: pointer; font-size: 13px; color: var(--muted); user-select: none; }
.switch .track { width: 44px; height: 24px; border-radius: 99px; background: var(--panel-hi); border: 1px solid var(--line-hi); position: relative; transition: background .3s; }
.switch .knob { position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; border-radius: 50%; background: var(--muted); transition: transform .3s cubic-bezier(.3,1.4,.5,1), background .3s; }
.switch.on .track { background: rgba(61,220,151,.22); border-color: rgba(61,220,151,.5); }
.switch.on .knob { transform: translateX(20px); background: var(--green); }
.token { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 10px; background: var(--panel); border: 1px solid var(--line); }
.token input { width: 150px; background: none; border: 0; outline: 0; color: var(--text); font: inherit; font-size: 13px; }
.token.need { border-color: var(--amber); box-shadow: 0 0 0 3px rgba(255,176,32,.15); animation: shake .4s; }
@keyframes shake { 25% { transform: translateX(-4px); } 75% { transform: translateX(4px); } }

/* 카드 */
.grid { display: grid; gap: 14px; }
.kpis { grid-template-columns: repeat(5, minmax(0, 1fr)); }
.card { background: linear-gradient(180deg, var(--panel-hi), var(--panel)); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 16px; position: relative; overflow: hidden; min-width: 0; }
.card h3 { margin: 0 0 12px; font-size: 12px; font-weight: 600; color: var(--muted); letter-spacing: .3px; display: flex; align-items: center; gap: 8px; }
.card h3 .hint { margin-left: auto; font-weight: 500; color: var(--faint); }
.kpi .label { font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 6px; }
.kpi .value { font-size: 30px; font-weight: 750; letter-spacing: -.8px; margin: 6px 0 2px; line-height: 1.1; }
.kpi .value small { font-size: 13px; font-weight: 600; color: var(--muted); margin-left: 4px; letter-spacing: 0; }
.kpi .sub { font-size: 12px; color: var(--faint); min-height: 16px; }
.delta { font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 6px; }
.delta.up { color: var(--green); background: rgba(61,220,151,.1); } .delta.down { color: var(--red); background: rgba(255,93,115,.1); }
.spark { display: block; width: 100%; height: 38px; margin-top: 8px; }
.kpi::after { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent, var(--cyan)); opacity: .7; }

/* 흐름 */
.flow { margin-top: 14px; }
.flow-stage { position: relative; height: 150px; }
.flow-stage canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
.nodes { position: absolute; inset: 0; display: flex; justify-content: space-between; align-items: center; padding: 0 2%; }
.node { display: flex; flex-direction: column; align-items: center; gap: 6px; width: 92px; text-align: center; }
.node .dot { width: 46px; height: 46px; border-radius: 50%; display: grid; place-items: center; font-size: 18px;
  background: radial-gradient(circle at 35% 30%, rgba(255,255,255,.14), rgba(255,255,255,.03)); border: 1px solid var(--line-hi);
  box-shadow: 0 0 0 0 var(--mode-glow); transition: box-shadow .3s, transform .2s; }
.node.hit .dot { transform: scale(1.08); box-shadow: 0 0 22px 2px var(--mode-glow); }
.node b { font-size: 15px; font-weight: 700; }
.node span { font-size: 11px; color: var(--muted); }
.conv { position: absolute; top: 18px; font-size: 10px; color: var(--faint); transform: translateX(-50%); white-space: nowrap; }

/* 본문 2열 */
.main { grid-template-columns: minmax(0, 1.65fr) minmax(0, 1fr); margin-top: 14px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }
.chip { border: 1px solid var(--line); background: none; color: var(--muted); font: inherit; font-size: 12px; padding: 4px 10px; border-radius: 99px; cursor: pointer; transition: all .2s; }
.chip.active { color: var(--text); border-color: var(--line-hi); background: var(--panel-hi); }
.chart { position: relative; height: 260px; }
.chart svg { width: 100%; height: 100%; display: block; overflow: visible; }
.legend { display: flex; gap: 16px; font-size: 12px; color: var(--muted); margin-top: 8px; flex-wrap: wrap; }
.legend i { display: inline-block; width: 18px; height: 3px; border-radius: 2px; vertical-align: middle; margin-right: 6px; }
.tip { position: absolute; pointer-events: none; background: rgba(15,18,25,.92); border: 1px solid var(--line-hi); border-radius: 10px;
  padding: 8px 10px; font-size: 12px; white-space: nowrap; transform: translate(-50%, -110%); opacity: 0; transition: opacity .15s; backdrop-filter: blur(6px); }
.modeband { display: flex; height: 6px; border-radius: 4px; overflow: hidden; margin-top: 10px; background: var(--panel); }
.modeband div { height: 100%; }
.axis { fill: var(--faint); font-size: 10px; }

.stack { display: flex; flex-direction: column; gap: 14px; }
.codes { display: flex; height: 10px; border-radius: 6px; overflow: hidden; background: var(--panel); }
.codes div { transition: width .6s cubic-bezier(.2,.8,.2,1); }
.row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; font-size: 13px; padding: 6px 0; }
.row + .row { border-top: 1px dashed var(--line); }
.row .k { color: var(--muted); }
.row .v { font-weight: 650; }
.gauge-wrap { display: flex; align-items: center; gap: 16px; }
.gauge { width: 92px; height: 92px; flex: none; }
.gauge .bg { stroke: var(--panel-hi); } .gauge .fg { transition: stroke-dashoffset .8s cubic-bezier(.2,.8,.2,1), stroke .4s; }
.bar { height: 8px; border-radius: 6px; background: var(--panel-hi); overflow: hidden; }
.bar div { height: 100%; border-radius: 6px; transition: width .6s cubic-bezier(.2,.8,.2,1), background .4s; }
.pg { padding: 8px 0; }
.pg + .pg { border-top: 1px dashed var(--line); }
.pg .top { display: flex; align-items: center; gap: 8px; font-size: 13px; margin-bottom: 7px; }
.pg .top b { font-size: 16px; margin-left: auto; }
.badge { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 6px; letter-spacing: .3px; }
.badge.red { color: var(--red); background: rgba(255,93,115,.12); animation: blink 1.2s infinite; }
.badge.gray { color: var(--muted); background: var(--panel-hi); }
@keyframes blink { 50% { opacity: .45; } }

/* 장애 주입 */
.ops { grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 14px; }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--muted); margin-bottom: 12px; }
.field .inline { display: flex; gap: 8px; align-items: center; }
select, input[type=number] { background: var(--bg2); color: var(--text); border: 1px solid var(--line-hi); border-radius: 9px; padding: 7px 9px; font: inherit; font-size: 13px; }
input[type=range] { flex: 1; accent-color: var(--red); }
.btn { border: 1px solid var(--line-hi); background: var(--panel-hi); color: var(--text); font: inherit; font-size: 13px; font-weight: 650;
  padding: 9px 14px; border-radius: 10px; cursor: pointer; transition: transform .1s, background .2s, border-color .2s; width: 100%; }
.btn:hover { background: rgba(255,255,255,.1); } .btn:active { transform: scale(.98); }
.btn.danger { border-color: rgba(255,93,115,.45); background: rgba(255,93,115,.12); color: #ffd0d7; }
.btn.danger:hover { background: rgba(255,93,115,.2); }
.btn:disabled { opacity: .4; cursor: not-allowed; }
.active-incident { display: flex; align-items: center; gap: 16px; }
.ring { width: 76px; height: 76px; flex: none; }
.ring .fg { transition: stroke-dashoffset 1s linear; }
.ai-type { font-size: 15px; font-weight: 700; }
.ai-meta { font-size: 12px; color: var(--muted); margin-top: 4px; line-height: 1.6; }
.empty { color: var(--faint); font-size: 13px; padding: 18px 0; text-align: center; }

footer { color: var(--faint); font-size: 11px; text-align: center; padding: 22px 0 8px; }

/* 토스트·확인창 */
.toasts { position: fixed; right: 16px; bottom: 16px; display: flex; flex-direction: column; gap: 8px; z-index: 50; max-width: calc(100vw - 32px); }
.toast { background: rgba(18,21,29,.96); border: 1px solid var(--line-hi); border-left: 3px solid var(--green); padding: 11px 14px; border-radius: 12px;
  font-size: 13px; box-shadow: 0 12px 30px rgba(0,0,0,.4); animation: tin .35s cubic-bezier(.2,1.2,.4,1); }
.toast.err { border-left-color: var(--red); }
.toast.out { animation: tout .3s forwards; }
@keyframes tin { from { opacity: 0; transform: translateY(14px) scale(.96); } }
@keyframes tout { to { opacity: 0; transform: translateX(30px); } }
.modal { position: fixed; inset: 0; background: rgba(5,6,10,.6); backdrop-filter: blur(4px); display: none; place-items: center; z-index: 60; padding: 16px; }
.modal.show { display: grid; animation: fade .2s; }
@keyframes fade { from { opacity: 0; } }
.dialog { background: var(--bg2); border: 1px solid var(--line-hi); border-radius: 18px; padding: 22px; max-width: 380px; width: 100%; animation: pop .25s cubic-bezier(.2,1.3,.4,1); }
@keyframes pop { from { transform: scale(.94); opacity: 0; } }
.dialog h4 { margin: 0 0 8px; font-size: 16px; }
.dialog p { margin: 0 0 18px; color: var(--muted); font-size: 13px; line-height: 1.6; }
.dialog .acts { display: flex; gap: 8px; }

@media (max-width: 1080px) { .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } .main, .ops { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 620px) {
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } .kpi .value { font-size: 24px; }
  .flow-stage { height: 112px; } .node { width: 54px; } .node .dot { width: 34px; height: 34px; font-size: 14px; } .node b { font-size: 12px; } .conv { display: none; }
  .token input { width: 100px; }
}
@media (prefers-reduced-motion: reduce) { *, *::before { animation: none !important; transition: none !important; } }
</style>
</head>
<body data-mode="normal" data-running="true">
<div class="wrap">
  <header>
    <div class="brand">🛍️ 시뮬레이터 콘솔</div>
    <span class="live" id="live"><i></i><span>연결 중</span></span>
    <span class="simclock" id="simclock"></span>
    <span class="spacer"></span>
    <div class="seg" id="modeSeg">
      <span class="thumb"></span>
      <button data-mode="normal">normal</button>
      <button data-mode="medium">medium</button>
      <button data-mode="burst">burst</button>
    </div>
    <label class="switch" id="runSwitch"><span class="track"><span class="knob"></span></span><span id="runLabel">실행 중</span></label>
    <label class="token" id="tokenBox">🔑<input id="token" type="password" placeholder="토큰 (로컬은 비움)" autocomplete="off"></label>
  </header>

  <section class="grid kpis" id="kpis"></section>

  <section class="card flow">
    <h3>실시간 흐름 <span class="hint" id="flowHint">시뮬레이터가 보낸 것 · 분당</span></h3>
    <div class="flow-stage" id="flowStage">
      <canvas id="flowCanvas"></canvas>
      <div class="nodes" id="nodes"></div>
    </div>
  </section>

  <section class="grid main">
    <div class="card">
      <h3>보낸 것 vs 받은 것 <span class="chips" id="chips"></span></h3>
      <div class="chart" id="chart"><svg id="chartSvg"></svg><div class="tip" id="tip"></div></div>
      <div class="modeband" id="modeband" title="모드 기록 (최근 30분)"></div>
      <div class="legend"><span><i style="background:var(--cyan)"></i>시뮬레이터가 보냄</span><span><i style="background:var(--violet)"></i>API가 받음</span><span id="chartUnit"></span></div>
    </div>
    <div class="stack">
      <div class="card">
        <h3>API 상태 <span class="hint" id="apiHint">최근 1분</span></h3>
        <div class="gauge-wrap">
          <svg class="gauge" viewBox="0 0 100 100" id="gauge">
            <circle class="bg" cx="50" cy="50" r="40" fill="none" stroke-width="9"/>
            <circle class="fg" cx="50" cy="50" r="40" fill="none" stroke-width="9" stroke-linecap="round" transform="rotate(-90 50 50)" stroke-dasharray="251.3" stroke-dashoffset="251.3"/>
            <text x="50" y="49" text-anchor="middle" fill="currentColor" font-size="19" font-weight="750" id="p95">-</text>
            <text x="50" y="66" text-anchor="middle" class="axis" font-size="10">p95 ms</text>
          </svg>
          <div style="flex:1;min-width:0">
            <div class="codes" id="codes"></div>
            <div class="row"><span class="k">요청</span><span class="v" id="reqRate">-</span></div>
            <div class="row"><span class="k">Kafka 발행 OK / 실패</span><span class="v" id="kafka">-</span></div>
          </div>
        </div>
        <div class="row" style="margin-top:6px"><span class="k">DB 풀 사용 / 대기</span><span class="v" id="pool">-</span></div>
        <div class="bar"><div id="poolBar" style="width:0;background:var(--cyan)"></div></div>
      </div>
      <div class="card">
        <h3>PG별 결제 성공률 <span class="hint">최근 1분 · API 기준</span></h3>
        <div id="pgs"><div class="empty">데이터를 기다리는 중</div></div>
      </div>
    </div>
  </section>

  <section class="grid ops">
    <div class="card">
      <h3>진행 중 사건</h3>
      <div id="active"><div class="empty">없음 · 평온합니다 🌿</div></div>
    </div>
    <div class="card">
      <h3>⚡ PG 장애 주입</h3>
      <div class="field">PG
        <select id="pg"><option>PG_A</option><option selected>PG_B</option></select></div>
      <div class="field">추가 실패율 <b id="extraLabel" style="color:var(--text)">85%</b>
        <div class="inline"><input type="range" id="extra" min="0.05" max="1" step="0.05" value="0.85"></div></div>
      <div class="field">지속 시간(분)
        <input type="number" id="minutes" value="10" min="1" max="60"></div>
      <button class="btn danger" id="pgBtn">PG 장애 시작</button>
    </div>
    <div class="card">
      <h3>🧪 데이터 오염</h3>
      <div class="field">종류
        <select id="kind"><option value="ORDER_TOTAL_MISMATCH">주문 총액 불일치</option><option value="DUPLICATE_SUCCESS_PAYMENT">성공 결제 중복</option></select></div>
      <div class="field">건수
        <input type="number" id="count" value="30" min="1" max="500"></div>
      <div class="field" style="visibility:hidden">-<input type="number"></div>
      <button class="btn danger" id="polBtn">데이터 오염 실행</button>
    </div>
  </section>
  <footer>2초마다 갱신 · 그래프는 최근 30분(컨트롤러 메모리) · 장애를 일으키기 전에 정답표가 먼저 기록됩니다</footer>
</div>

<div class="toasts" id="toasts"></div>
<div class="modal" id="modal"><div class="dialog"><h4 id="mTitle"></h4><p id="mBody"></p>
  <div class="acts"><button class="btn" id="mNo">취소</button><button class="btn danger" id="mYes">실행</button></div></div></div>

<script>
"use strict";
const $ = s => document.querySelector(s);
const S = { token: "", samples: [], status: null, ok: null, metric: "orders", hover: null };
const MAX_SAMPLES = 900;
const fmt = (v, d = 0) => v == null || !isFinite(v) ? "-" : v.toLocaleString("ko-KR", { maximumFractionDigits: d, minimumFractionDigits: d });
const fmtAuto = v => v == null ? "-" : v >= 100 ? fmt(v, 0) : v >= 10 ? fmt(v, 1) : fmt(v, 2);

// ---------- 서버 ----------
function headers(json) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  if (S.token) h["Authorization"] = "Bearer " + S.token;
  return h;
}
async function call(path, body) {
  const res = await fetch(path, body === undefined ? { headers: headers(false) } : { method: "POST", headers: headers(true), body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { const e = new Error(data.error || ("HTTP " + res.status)); e.status = res.status; throw e; }
  return data;
}

// ---------- 표본 계산 ----------
const G = {
  visits: s => s.sim.behavior && s.sim.behavior.visits,
  views: s => s.sim.behavior && s.sim.behavior.views,
  carts: s => s.sim.behavior && s.sim.behavior.cart_adds,
  orders: s => s.sim.behavior && s.sim.behavior.orders,
  paysOk: s => s.sim.behavior && s.sim.behavior.payments_success,
  pays: s => s.sim.behavior && (s.sim.behavior.payments_success + s.sim.behavior.payments_failed),
  clicks: s => s.sim.behavior && (s.sim.behavior.views + s.sim.behavior.cart_adds),
  delivered: s => s.sim.behavior && (s.sim.behavior.transitions.DELIVERED || 0),
  signups: s => s.sim.member && s.sim.member.signups,
  aReq: s => s.api && s.api.requests,
  aOrders: s => s.api && s.api.orders,
  aMembers: s => s.api && s.api.members,
  aPays: s => s.api && Object.values(s.api.payments).reduce((a, b) => a + b, 0),
  aKafkaOk: s => s.api && (s.api.kafka.ok || 0),
  aKafkaFail: s => s.api && ((s.api.kafka.failed || 0) + (s.api.kafka.rejected || 0)),
  a2: s => s.api && s.api.status["2xx"], a4: s => s.api && s.api.status["4xx"], a5: s => s.api && s.api.status["5xx"],
};
const num = v => typeof v === "number" && isFinite(v) ? v : null;
function pairAgo(seconds) {
  const a = S.samples; if (a.length < 2) return null;
  const last = a[a.length - 1]; let i = a.length - 2;
  while (i > 0 && last.t - a[i].t < seconds) i--;
  return [a[i], last];
}
function delta(get, seconds) {
  const p = pairAgo(seconds); if (!p) return null;
  const x0 = num(get(p[0])), x1 = num(get(p[1]));
  if (x0 == null || x1 == null) return null;
  return { d: Math.max(0, x1 - x0), dt: p[1].t - p[0].t };
}
function rateNow(get, per = 1, seconds = 10) { const r = delta(get, seconds); return r && r.dt > 0 ? r.d / r.dt * per : null; }
function series(get, per = 1, win = 5) {
  const a = S.samples, raw = [];
  for (let i = 1; i < a.length; i++) {
    const x0 = num(get(a[i - 1])), x1 = num(get(a[i])), dt = a[i].t - a[i - 1].t;
    raw.push({ t: a[i].t, v: x0 == null || x1 == null || dt <= 0 ? null : Math.max(0, x1 - x0) / dt * per });
  }
  return raw.map((p, i) => {
    let s = 0, n = 0;
    for (let j = Math.max(0, i - win + 1); j <= i; j++) if (raw[j].v != null) { s += raw[j].v; n++; }
    return { t: p.t, v: n ? s / n : null };
  });
}
function p95(seconds) {
  const p = pairAgo(seconds); if (!p || !p[0].api || !p[1].api) return null;
  const b0 = p[0].api.latency_buckets, b1 = p[1].api.latency_buckets;
  const les = Object.keys(b1).map(k => [k, k === "+Inf" ? Infinity : parseFloat(k)]).sort((x, y) => x[1] - y[1]);
  const cum = les.map(([k, le]) => [le, Math.max(0, (b1[k] || 0) - (b0[k] || 0))]);
  const total = cum.length ? cum[cum.length - 1][1] : 0;
  if (!total) return null;
  const target = total * 0.95; let prevLe = 0, prevC = 0;
  for (const [le, c] of cum) {
    if (c >= target) {
      if (!isFinite(le)) return prevLe * 1000;
      const f = c === prevC ? 1 : (target - prevC) / (c - prevC);
      return (prevLe + (le - prevLe) * f) * 1000;
    }
    prevLe = le; prevC = c;
  }
  return null;
}

// ---------- 숫자 애니메이션 ----------
const tweens = new Map();
function animateNumber(el, to, digits) {
  if (to == null || !isFinite(to)) { el.textContent = "-"; tweens.delete(el); return; }
  const from = tweens.has(el) ? tweens.get(el).cur : to;
  const t = { from, to, cur: from, start: performance.now(), digits };
  tweens.set(el, t);
}
function tickTweens(now) {
  for (const [el, t] of tweens) {
    const k = Math.min(1, (now - t.start) / 700), e = 1 - Math.pow(1 - k, 3);
    t.cur = t.from + (t.to - t.from) * e;
    el.textContent = fmt(t.cur, t.digits);
  }
}

// ---------- KPI ----------
const KPIS = [
  { id: "visits", label: "👣 방문", unit: "/초", accent: "var(--cyan)", get: () => rateNow(G.visits, 1), digits: 1, spark: () => series(G.visits, 1), sub: () => "누적 " + fmt(num(last("visits"))) },
  { id: "orders", label: "🧾 주문", unit: "/분", accent: "var(--violet)", get: () => rateNow(G.orders, 60, 30), digits: 1, spark: () => series(G.orders, 60, 10), sub: () => "누적 " + fmt(num(last("orders"))) },
  { id: "payrate", label: "💳 결제 성공률", unit: "%", accent: "var(--green)", get: payRate, digits: 1, spark: payRateSeries, sub: () => { const r = delta(G.aPays, 60); return r ? "최근 1분 시도 " + fmt(r.d) + "건" : "API 기준"; } },
  { id: "signups", label: "✨ 가입", unit: "/분", accent: "var(--amber)", get: () => rateNow(G.signups, 60, 30), digits: 1, spark: () => series(G.signups, 60, 10), sub: () => "누적 " + fmt(num(last("signups"))) },
  { id: "req", label: "🛰️ API 요청", unit: "/초", accent: "var(--red)", get: () => rateNow(G.aReq, 1), digits: 1, spark: () => series(G.aReq, 1), sub: () => { const v = p95(30); return v == null ? "응답 시간 -" : "p95 " + fmt(v, 0) + "ms"; } },
];
function last(key) { const s = S.samples[S.samples.length - 1]; return s ? G[key](s) : null; }
function payRate() {
  const p = pairAgo(60); if (!p || !p[0].api || !p[1].api) return null;
  let ok = 0, all = 0;
  for (const [k, v] of Object.entries(p[1].api.payments)) {
    const d = Math.max(0, v - (p[0].api.payments[k] || 0)); all += d; if (k.endsWith(":SUCCESS")) ok += d;
  }
  return all ? ok / all * 100 : null;
}
function payRateSeries() {
  // 30초 창의 성공 비율. 표본마다 하나
  const a = S.samples, out = [];
  for (let i = 0; i < a.length; i++) {
    let j = i; while (j > 0 && a[i].t - a[j].t < 30) j--;
    let ok = 0, all = 0;
    if (a[i].api && a[j].api && i !== j) for (const [k, v] of Object.entries(a[i].api.payments)) {
      const d = Math.max(0, v - (a[j].api.payments[k] || 0)); all += d; if (k.endsWith(":SUCCESS")) ok += d;
    }
    out.push({ t: a[i].t, v: all ? ok / all * 100 : null });
  }
  return out;
}
function buildKpis() {
  $("#kpis").innerHTML = KPIS.map(k => `<div class="card kpi" style="--accent:${k.accent}">
    <div class="label">${k.label}<span class="delta" id="d-${k.id}"></span></div>
    <div class="value"><span id="v-${k.id}">-</span><small>${k.unit}</small></div>
    <div class="sub" id="s-${k.id}"></div>
    <svg class="spark" id="sp-${k.id}" preserveAspectRatio="none"></svg></div>`).join("");
}
function renderKpis() {
  for (const k of KPIS) {
    const v = k.get();
    animateNumber($("#v-" + k.id), v, k.digits);
    $("#s-" + k.id).textContent = k.sub();
    const sp = k.spark().slice(-450);
    drawSpark($("#sp-" + k.id), sp.map(p => p.v), k.accent);
    const d = $("#d-" + k.id);
    if (sp.length > 40 && v != null) {
      const prev = sp[sp.length - 31].v;
      if (prev) { const ch = (v - prev) / prev * 100; d.textContent = (ch >= 0 ? "▲ " : "▼ ") + fmt(Math.abs(ch), 0) + "%"; d.className = "delta " + (ch >= 0 ? "up" : "down"); }
      else { d.textContent = ""; d.className = "delta"; }
    } else { d.textContent = ""; d.className = "delta"; }
  }
}
function drawSpark(svg, vals, color) {
  const w = svg.clientWidth || 200, h = 38, pts = vals.map((v, i) => [i, v]).filter(p => p[1] != null);
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  if (pts.length < 2) { svg.innerHTML = ""; return; }
  const max = Math.max(...pts.map(p => p[1]), 1e-9), n = vals.length - 1 || 1;
  const xy = pts.map(([i, v]) => [i / n * w, h - 3 - v / max * (h - 8)]);
  const line = xy.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const gid = "g" + svg.id;
  svg.innerHTML = `<defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".35"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    <path d="${line} L${xy[xy.length - 1][0]} ${h} L${xy[0][0]} ${h} Z" fill="url(#${gid})"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round"/>
    <circle cx="${xy[xy.length - 1][0]}" cy="${xy[xy.length - 1][1]}" r="2.8" fill="${color}"/>`;
}

// ---------- 흐름 ----------
// conv: 앞 노드와 비교하는 방식. ratio = 방문당 횟수, pct-visit = 방문 대비, pct-prev = 바로 앞 대비, none = 같은 무리가 아님
const NODES = [
  { key: "visits", icon: "👣", name: "방문" }, { key: "views", icon: "👀", name: "조회", conv: "ratio" },
  { key: "carts", icon: "🛒", name: "담기", conv: "pct-visit" }, { key: "orders", icon: "🧾", name: "주문", conv: "pct-visit" },
  { key: "paysOk", icon: "💳", name: "결제 성공", conv: "pct-prev" }, { key: "delivered", icon: "📦", name: "배송 완료", conv: "none" },
];
const flow = { rates: NODES.map(() => 0), acc: NODES.map(() => 0), parts: [], w: 0, h: 0, xs: [] };
function buildFlow() {
  $("#nodes").innerHTML = NODES.map((n, i) => `<div class="node" id="n-${i}"><div class="dot">${n.icon}</div><b id="nr-${i}">-</b><span>${n.name}</span></div>`).join("");
  for (let i = 1; i < NODES.length; i++) { const c = document.createElement("div"); c.className = "conv"; c.id = "cv-" + i; $("#flowStage").appendChild(c); }
}
function layoutFlow() {
  const stage = $("#flowStage"), cv = $("#flowCanvas"), r = stage.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  flow.w = r.width; flow.h = r.height; cv.width = r.width * dpr; cv.height = r.height * dpr;
  cv.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
  flow.xs = NODES.map((_, i) => { const d = $("#n-" + i + " .dot").getBoundingClientRect(); return [d.left - r.left + d.width / 2, d.top - r.top + d.height / 2]; });
  for (let i = 1; i < NODES.length; i++) { const c = $("#cv-" + i); if (c) c.style.left = ((flow.xs[i - 1][0] + flow.xs[i][0]) / 2) + "px"; }
}
function renderFlowNumbers() {
  NODES.forEach((n, i) => {
    const v = rateNow(G[n.key], 60, 30); flow.rates[i] = v || 0;
    $("#nr-" + i).textContent = fmtAuto(v);
    const c = i > 0 && $("#cv-" + i); if (!c) return;
    const visits = flow.rates[0], prev = rateNow(G[NODES[i - 1].key], 60, 30);
    c.textContent = v == null ? "" : n.conv === "ratio" && visits ? "방문당 ×" + fmt(v / visits, 1)
      : n.conv === "pct-visit" && visits ? "방문의 " + fmt(v / visits * 100, 1) + "%"
      : n.conv === "pct-prev" && prev ? "주문의 " + fmt(v / prev * 100, 0) + "%" : "";
  });
}
function cssVar(name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); }
function stepFlow(dt) {
  const ctx = $("#flowCanvas").getContext("2d"), xs = flow.xs; if (!xs.length) return;
  ctx.clearRect(0, 0, flow.w, flow.h);
  const color = cssVar("--mode") || "#3ddc97";
  ctx.lineWidth = 2; ctx.strokeStyle = "rgba(255,255,255,.07)"; ctx.setLineDash([4, 6]);
  ctx.beginPath(); ctx.moveTo(xs[0][0], xs[0][1]); for (const p of xs) ctx.lineTo(p[0], p[1]); ctx.stroke(); ctx.setLineDash([]);
  const running = document.body.dataset.running === "true";
  for (let i = 1; i < NODES.length && running; i++) {
    // 분당 속도 → 화면 입자 수 (로그 눈금, 초당 최대 약 14개)
    const perSec = Math.min(14, Math.log10(1 + flow.rates[i]) * 4.2);
    flow.acc[i] += perSec * dt;
    while (flow.acc[i] >= 1) { flow.acc[i] -= 1; flow.parts.push({ seg: i, k: 0, speed: .55 + Math.random() * .35, off: (Math.random() - .5) * 10, r: 1.6 + Math.random() * 1.6 }); }
  }
  if (flow.parts.length > 600) flow.parts.splice(0, flow.parts.length - 600);
  ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 10;
  flow.parts = flow.parts.filter(p => {
    p.k += p.speed * dt; if (p.k >= 1) { const n = $("#n-" + p.seg); if (n) { n.classList.add("hit"); clearTimeout(n._t); n._t = setTimeout(() => n.classList.remove("hit"), 160); } return false; }
    const a = xs[p.seg - 1], b = xs[p.seg], e = p.k < .5 ? 2 * p.k * p.k : 1 - Math.pow(-2 * p.k + 2, 2) / 2;
    const x = a[0] + (b[0] - a[0]) * e, y = a[1] + (b[1] - a[1]) * e + Math.sin(p.k * Math.PI) * p.off;
    ctx.globalAlpha = Math.sin(p.k * Math.PI) * .9 + .1; ctx.beginPath(); ctx.arc(x, y, p.r, 0, Math.PI * 2); ctx.fill();
    return true;
  });
  ctx.globalAlpha = 1; ctx.shadowBlur = 0;
}

// ---------- 큰 그래프 ----------
const METRICS = {
  orders: { label: "주문", unit: "건/분", sim: G.orders, api: G.aOrders, per: 60 },
  pays: { label: "결제 시도", unit: "건/분", sim: G.pays, api: G.aPays, per: 60 },
  clicks: { label: "클릭", unit: "건/초", sim: G.clicks, api: G.aKafkaOk, per: 1 },
  signups: { label: "가입", unit: "명/분", sim: G.signups, api: G.aMembers, per: 60 },
};
function buildChips() {
  $("#chips").innerHTML = Object.entries(METRICS).map(([k, m]) => `<button class="chip" data-k="${k}">${m.label}</button>`).join("");
  $("#chips").addEventListener("click", e => { const k = e.target.dataset && e.target.dataset.k; if (k) { S.metric = k; renderChart(); } });
}
function renderChart() {
  document.querySelectorAll(".chip").forEach(c => c.classList.toggle("active", c.dataset.k === S.metric));
  const m = METRICS[S.metric], svg = $("#chartSvg"), box = $("#chart");
  const w = box.clientWidth, h = box.clientHeight, pl = 40, pr = 8, pt = 10, pb = 22;
  const a = series(m.sim, m.per, 8), b = series(m.api, m.per, 8);
  $("#chartUnit").textContent = "단위: " + m.unit;
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  if (a.length < 2) { svg.innerHTML = `<text x="${w / 2}" y="${h / 2}" text-anchor="middle" class="axis" font-size="13">표본을 모으는 중…</text>`; renderModeBand(); return; }
  const t0 = a[0].t, t1 = a[a.length - 1].t, span = Math.max(t1 - t0, 1);
  const max = Math.max(1e-9, ...a.map(p => p.v || 0), ...b.map(p => p.v || 0)) * 1.15;
  const X = t => pl + (t - t0) / span * (w - pl - pr), Y = v => pt + (1 - v / max) * (h - pt - pb);
  const path = arr => { let d = "", pen = false; for (const p of arr) { if (p.v == null) { pen = false; continue; } d += (pen ? "L" : "M") + X(p.t).toFixed(1) + " " + Y(p.v).toFixed(1); pen = true; } return d; };
  let grid = "";
  const top = max / 1.15, d = top >= 10 ? 0 : top >= 1 ? 1 : 2;
  for (let i = 0; i <= 4; i++) { const v = top * i / 4, y = Y(v); grid += `<line x1="${pl}" x2="${w - pr}" y1="${y}" y2="${y}" stroke="rgba(255,255,255,.05)"/><text x="${pl - 6}" y="${y + 3}" text-anchor="end" class="axis">${fmt(v, d)}</text>`; }
  for (let m2 = 0; m2 <= 30; m2 += 5) { const t = t1 - m2 * 60; if (t < t0) break; grid += `<text x="${X(t)}" y="${h - 6}" text-anchor="middle" class="axis">${m2 ? "-" + m2 + "분" : "지금"}</text>`; }
  const da = path(a), firstA = a.find(p => p.v != null);
  const area = da && firstA ? `${da} L${X(t1)} ${Y(0)} L${X(firstA.t)} ${Y(0)} Z` : "";
  svg.innerHTML = `<defs><linearGradient id="ga" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#4cc9f0" stop-opacity=".28"/><stop offset="1" stop-color="#4cc9f0" stop-opacity="0"/></linearGradient></defs>
    ${grid}<path d="${area}" fill="url(#ga)"/>
    <path d="${da}" fill="none" stroke="#4cc9f0" stroke-width="2.2" stroke-linejoin="round"/>
    <path d="${path(b)}" fill="none" stroke="#a594ff" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>
    <line id="cross" y1="${pt}" y2="${h - pb}" stroke="rgba(255,255,255,.25)" opacity="0"/>
    <circle id="ca" r="4" fill="#4cc9f0" opacity="0"/><circle id="cb" r="4" fill="#a594ff" opacity="0"/>`;
  S.chart = { a, b, X, Y, w, pl, pr, t0, span, m };
  renderModeBand();
  if (S.hover != null) hover(S.hover);
}
function hover(px) {
  const c = S.chart; if (!c) return; S.hover = px;
  const t = c.t0 + (px - c.pl) / (c.w - c.pl - c.pr) * c.span;
  let i = 0, best = Infinity; c.a.forEach((p, j) => { const d = Math.abs(p.t - t); if (d < best) { best = d; i = j; } });
  const pa = c.a[i], pb = c.b[i], x = c.X(pa.t);
  const cross = $("#cross"); if (!cross) return;
  cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("opacity", 1);
  for (const [id, p] of [["#ca", pa], ["#cb", pb]]) { const el = $(id); if (p && p.v != null) { el.setAttribute("cx", x); el.setAttribute("cy", c.Y(p.v)); el.setAttribute("opacity", 1); } else el.setAttribute("opacity", 0); }
  const tip = $("#tip"), ago = Math.round((c.a[c.a.length - 1].t - pa.t) / 60);
  tip.innerHTML = `<div style="color:var(--muted);margin-bottom:4px">${ago ? ago + "분 전" : "지금"} · ${new Date(pa.t * 1000).toLocaleTimeString("ko-KR")}</div>
    <div><span style="color:var(--cyan)">●</span> 보냄 <b>${fmtAuto(pa.v)}</b> ${c.m.unit}</div><div><span style="color:var(--violet)">●</span> 받음 <b>${fmtAuto(pb && pb.v)}</b> ${c.m.unit}</div>`;
  tip.style.left = Math.min(Math.max(x, 90), c.w - 90) + "px"; tip.style.top = Math.max(70, pa.v != null ? c.Y(pa.v) : 70) + "px"; tip.style.opacity = 1;
}
function unhover() { S.hover = null; $("#tip").style.opacity = 0; for (const id of ["#cross", "#ca", "#cb"]) { const el = $(id); if (el) el.setAttribute("opacity", 0); } }
function renderModeBand() {
  const a = S.samples, band = $("#modeband"); if (a.length < 2) { band.innerHTML = ""; return; }
  const colors = { normal: "var(--green)", medium: "var(--amber)", burst: "var(--red)", off: "var(--faint)", none: "transparent" };
  const runs = []; for (const s of a) { const b = s.sim.behavior, k = !b ? "none" : !b.running ? "off" : b.mode; if (runs.length && runs[runs.length - 1].k === k) runs[runs.length - 1].n++; else runs.push({ k, n: 1 }); }
  band.innerHTML = runs.map(r => `<div style="flex:${r.n};background:${colors[r.k]};opacity:.75" title="${r.k}"></div>`).join("");
}

// ---------- API·PG ----------
function renderApi() {
  const lastS = S.samples[S.samples.length - 1], up = !!(lastS && lastS.api);
  $("#apiHint").textContent = up ? "최근 1분" : (S.apiConfigured === false ? "API 주소 없음" : "API 연결 안 됨");
  const v = p95(60), g = $("#gauge .fg"), frac = v == null ? 0 : Math.min(1, v / 500);
  g.style.strokeDashoffset = 251.3 * (1 - frac);
  g.style.stroke = v == null ? "var(--faint)" : v < 100 ? "var(--green)" : v < 300 ? "var(--amber)" : "var(--red)";
  $("#p95").textContent = v == null ? "-" : fmt(v, 0);
  const c2 = delta(G.a2, 60), c4 = delta(G.a4, 60), c5 = delta(G.a5, 60);
  const tot = (c2 ? c2.d : 0) + (c4 ? c4.d : 0) + (c5 ? c5.d : 0);
  const pct = r => tot ? (r ? r.d : 0) / tot * 100 : 0;
  $("#codes").innerHTML = `<div style="width:${pct(c2)}%;background:var(--green)" title="2xx"></div><div style="width:${pct(c4)}%;background:var(--amber)" title="4xx"></div><div style="width:${pct(c5)}%;background:var(--red)" title="5xx"></div>`;
  $("#reqRate").innerHTML = up ? `${fmtAuto(rateNow(G.aReq, 1))}/초 <span style="color:var(--muted);font-weight:500">· 4xx ${fmt(c4 && c4.d)} · 5xx <span style="color:${c5 && c5.d ? "var(--red)" : "inherit"}">${fmt(c5 && c5.d)}</span></span>` : "-";
  const ko = rateNow(G.aKafkaOk, 1), kf = delta(G.aKafkaFail, 60);
  $("#kafka").innerHTML = up ? `${fmtAuto(ko)}/초 · <span style="color:${kf && kf.d ? "var(--red)" : "inherit"}">${fmt(kf && kf.d)}</span>` : "-";
  const pool = up ? lastS.api.pool : null;
  if (pool && pool.size) {
    const used = pool.size - pool.available;
    $("#pool").textContent = `${fmt(used)} / ${fmt(pool.size)} · 대기 ${fmt(pool.waiting)}`;
    $("#poolBar").style.width = (used / pool.size * 100) + "%";
    $("#poolBar").style.background = pool.waiting ? "var(--red)" : used / pool.size > .8 ? "var(--amber)" : "var(--cyan)";
  } else { $("#pool").textContent = "-"; $("#poolBar").style.width = "0"; }

  const p = pairAgo(60);
  if (!p || !p[1].api) { $("#pgs").innerHTML = `<div class="empty">${up ? "데이터를 기다리는 중" : "API 연결 안 됨"}</div>`; return; }
  const pgs = {};
  for (const [k, val] of Object.entries(p[1].api.payments)) {
    const [pg, st] = k.split(":"), d = Math.max(0, val - ((p[0].api && p[0].api.payments[k]) || 0));
    pgs[pg] = pgs[pg] || { ok: 0, all: 0 }; pgs[pg].all += d; if (st === "SUCCESS") pgs[pg].ok += d;
  }
  const extra = (S.status && S.status.pg_extra_fail) || {};
  const names = Object.keys(pgs).sort();
  $("#pgs").innerHTML = names.length ? names.map(n => {
    const r = pgs[n].all ? pgs[n].ok / pgs[n].all * 100 : null;
    const col = r == null ? "var(--faint)" : r >= 90 ? "var(--green)" : r >= 70 ? "var(--amber)" : "var(--red)";
    const badge = extra[n] ? `<span class="badge red">장애 주입 중 +${fmt(extra[n] * 100)}%</span>` : `<span class="badge gray">${fmt(pgs[n].all)}건/분</span>`;
    return `<div class="pg"><div class="top">${n} ${badge}<b style="color:${col}">${r == null ? "-" : fmt(r, 1) + "%"}</b></div><div class="bar"><div style="width:${r || 0}%;background:${col}"></div></div></div>`;
  }).join("") : `<div class="empty">최근 1분 결제 없음</div>`;
}

// ---------- 상태·컨트롤 ----------
const TYPE_NAMES = { PG_OUTAGE: "⚡ PG 장애", TRAFFIC_SURGE: "🟠 medium 모드 (급증)", INGEST_LAG: "🔴 burst 모드 (적재 지연)", DATA_POLLUTION: "🧪 데이터 오염" };
function renderStatus() {
  const st = S.status; if (!st) return;
  document.body.dataset.mode = st.mode; document.body.dataset.running = String(st.running);
  const seg = $("#modeSeg"), btn = seg.querySelector(`[data-mode="${st.mode}"]`);
  seg.querySelectorAll("button").forEach(b => b.classList.toggle("active", b === btn));
  const th = seg.querySelector(".thumb"); th.style.left = btn.offsetLeft + "px"; th.style.width = btn.offsetWidth + "px";
  $("#runSwitch").classList.toggle("on", st.running); $("#runLabel").textContent = st.running ? "실행 중" : "정지됨";
  const inc = st.active;
  $("#pgBtn").disabled = $("#polBtn").disabled = !!inc;
  if (!inc) { $("#active").innerHTML = `<div class="empty">없음 · 평온합니다 🌿</div>`; return; }
  const start = Date.parse(inc.started_at), end = inc.ends_at ? Date.parse(inc.ends_at) : null, now = Date.now();
  const left = end ? Math.max(0, end - now) : null, frac = end ? left / Math.max(1, end - start) : 1;
  const mm = left == null ? "∞" : `${Math.floor(left / 60000)}:${String(Math.floor(left / 1000) % 60).padStart(2, "0")}`;
  const col = inc.type === "PG_OUTAGE" || inc.type === "INGEST_LAG" ? "var(--red)" : "var(--amber)";
  $("#active").innerHTML = `<div class="active-incident">
    <svg class="ring" viewBox="0 0 100 100"><circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="8"/>
      <circle class="fg" cx="50" cy="50" r="42" fill="none" stroke="${col}" stroke-width="8" stroke-linecap="round" transform="rotate(-90 50 50)" stroke-dasharray="263.9" stroke-dashoffset="${263.9 * (1 - frac)}"/>
      <text x="50" y="56" text-anchor="middle" fill="currentColor" font-size="17" font-weight="750">${mm}</text></svg>
    <div style="min-width:0"><div class="ai-type">${TYPE_NAMES[inc.type] || inc.type}</div>
      <div class="ai-meta">시작 ${new Date(start).toLocaleTimeString("ko-KR")}${end ? " · 자동 종료 " + new Date(end).toLocaleTimeString("ko-KR") : ""}</div></div></div>
    <button class="btn" style="margin-top:14px" id="endBtn">지금 종료</button>`;
  $("#endBtn").onclick = () => act("/api/incidents/end", {}, "사건을 종료했습니다");
}
function renderClock() {
  const s = S.samples[S.samples.length - 1], b = s && s.sim.behavior;
  $("#simclock").textContent = b ? "🕒 " + b.sim_time.replace("T", " ").slice(0, 19) + " · 큐 " + fmt(b.queue) : "";
}
function setLive(ok, text) { const el = $("#live"); el.className = "live " + (ok ? "on" : "off"); el.querySelector("span").textContent = text; }

// ---------- 동작 ----------
function toast(msg, err) {
  const el = document.createElement("div"); el.className = "toast" + (err ? " err" : ""); el.textContent = msg;
  $("#toasts").appendChild(el); setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 300); }, err ? 5000 : 2800);
}
function confirmBox(title, body) {
  return new Promise(res => {
    $("#mTitle").textContent = title; $("#mBody").textContent = body; $("#modal").classList.add("show");
    const done = v => { $("#modal").classList.remove("show"); $("#mYes").onclick = $("#mNo").onclick = null; res(v); };
    $("#mYes").onclick = () => done(true); $("#mNo").onclick = () => done(false);
  });
}
async function act(path, body, okMsg) {
  try { S.status = await call(path, body); renderStatus(); toast("✅ " + okMsg); }
  catch (e) { if (e.status === 401) needToken(); toast("⚠️ " + e.message, true); }
}
function needToken() { const b = $("#tokenBox"); b.classList.remove("need"); void b.offsetWidth; b.classList.add("need"); $("#token").focus(); }

$("#modeSeg").addEventListener("click", async e => {
  const m = e.target.dataset && e.target.dataset.mode; if (!m || !S.status || m === S.status.mode) return;
  if (m !== "normal" && !(await confirmBox(m + " 모드로 바꿀까요?", m === "burst" ? "일상 피크의 10배 트래픽을 15분 동안 보냅니다. 정답표에 기록됩니다." : "일상 피크의 3배 트래픽을 60분 동안 보냅니다. 정답표에 기록됩니다."))) return;
  act("/api/mode", { mode: m }, m + " 모드로 바꿨습니다");
});
$("#runSwitch").addEventListener("click", async e => {
  e.preventDefault(); if (!S.status) return;
  const next = !S.status.running;
  if (!next && !(await confirmBox("시뮬레이터를 멈출까요?", "새 방문과 가입이 멈춥니다. 이미 예약된 결제·배송 전이는 계속 처리됩니다."))) return;
  act("/api/running", { running: next }, next ? "다시 시작했습니다" : "멈췄습니다");
});
$("#extra").addEventListener("input", e => $("#extraLabel").textContent = Math.round(e.target.value * 100) + "%");
$("#pgBtn").addEventListener("click", async () => {
  const pg = $("#pg").value, extra = +$("#extra").value, minutes = +$("#minutes").value;
  if (await confirmBox(`${pg} 장애를 시작할까요?`, `${minutes}분 동안 ${pg} 결제의 PG 원인 실패 확률을 ${Math.round(extra * 100)}%p 올립니다. 정답표가 먼저 기록됩니다.`))
    act("/api/incidents/pg-outage", { pg, extra_fail: extra, minutes }, pg + " 장애를 시작했습니다");
});
$("#polBtn").addEventListener("click", async () => {
  const kind = $("#kind").value, count = parseInt($("#count").value, 10);
  if (await confirmBox("데이터를 오염시킬까요?", `RDS의 최근 주문·결제 ${count}건에 ${$("#kind").selectedOptions[0].text}을(를) 만듭니다. 되돌릴 수 없습니다.`))
    act("/api/incidents/data-pollution", { kind, count }, "데이터 오염을 실행했습니다");
});
$("#token").addEventListener("input", e => { S.token = e.target.value.trim(); $("#tokenBox").classList.remove("need"); poll(); });
$("#chart").addEventListener("mousemove", e => hover(e.clientX - $("#chart").getBoundingClientRect().left));
$("#chart").addEventListener("mouseleave", unhover);
window.addEventListener("resize", () => { layoutFlow(); renderAll(); });

// ---------- 갱신 ----------
function renderAll() { renderKpis(); renderFlowNumbers(); renderChart(); renderApi(); renderClock(); renderStatus(); }
let polling = false;
async function poll() {
  if (polling) return; polling = true;
  try {
    const since = S.samples.length ? "?since=" + S.samples[S.samples.length - 1].t : "";
    const [st, tr] = await Promise.all([call("/api/status"), call("/api/traffic" + since)]);
    S.status = st; S.apiConfigured = tr.api_configured;
    S.samples.push(...tr.samples); if (S.samples.length > MAX_SAMPLES) S.samples.splice(0, S.samples.length - MAX_SAMPLES);
    const lastS = S.samples[S.samples.length - 1];
    setLive(true, lastS && lastS.sim.behavior ? "LIVE" : "시뮬레이터 응답 없음");
    renderAll();
  } catch (e) {
    if (e.status === 401) { setLive(false, "토큰 필요"); needToken(); } else setLive(false, "연결 끊김");
  } finally { polling = false; }
}
let lastFrame = performance.now(), lastRing = 0;
function frame(now) {
  const dt = Math.min(.1, (now - lastFrame) / 1000); lastFrame = now;
  tickTweens(now); stepFlow(dt);
  if (now - lastRing > 1000) { lastRing = now; if (S.status && S.status.active) renderStatus(); }
  requestAnimationFrame(frame);
}
buildKpis(); buildFlow(); buildChips(); layoutFlow();
poll(); setInterval(poll, 2000); requestAnimationFrame(frame);
</script>
</body>
</html>
"""
