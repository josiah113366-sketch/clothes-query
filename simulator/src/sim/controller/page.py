"""버튼 화면 (HTML 한 장, 외부 스크립트·CDN 없음). 설치본에 함께 들어가도록 모듈 문자열로 둔다."""

PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>시뮬레이터 컨트롤러</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 16px; max-width: 760px; }
  fieldset { margin: 12px 0; }
  button { margin: 2px 4px 2px 0; padding: 4px 10px; }
  pre { background: #f2f2f2; padding: 8px; white-space: pre-wrap; }
  #message { min-height: 1.4em; }
  @media (prefers-color-scheme: dark) {
    body { background: #16181d; color: #e4e6eb; }
    pre { background: #22252c; }
  }
</style>
</head>
<body>
<h1>시뮬레이터 컨트롤러</h1>
<p>운영자용 화면이다. 장애를 일으키기 전에 정답표가 먼저 기록된다.</p>

<fieldset>
  <legend>토큰</legend>
  <input id="token" type="password" placeholder="SIM_CONTROLLER_TOKEN (로컬이면 비워 둔다)" size="40" autocomplete="off">
</fieldset>

<fieldset>
  <legend>모드 (medium 60분, burst 15분 뒤 자동으로 normal)</legend>
  <button onclick="post('/api/mode', {mode: 'normal'})">normal</button>
  <button onclick="post('/api/mode', {mode: 'medium'})">medium</button>
  <button onclick="post('/api/mode', {mode: 'burst'})">burst</button>
  <span style="margin-left:16px"></span>
  <button onclick="post('/api/running', {running: true})">시작</button>
  <button onclick="post('/api/running', {running: false})">정지</button>
</fieldset>

<fieldset>
  <legend>PG 장애</legend>
  <select id="pg"><option>PG_A</option><option selected>PG_B</option></select>
  추가 실패율 <input id="extra" type="number" value="0.85" min="0.01" max="1" step="0.05" style="width:5em">
  분 <input id="minutes" type="number" value="10" min="1" max="60" style="width:4em">
  <button onclick="post('/api/incidents/pg-outage', {pg: v('pg'), extra_fail: +v('extra'), minutes: +v('minutes')})">시작</button>
</fieldset>

<fieldset>
  <legend>데이터 오염</legend>
  <select id="kind"><option>ORDER_TOTAL_MISMATCH</option><option>DUPLICATE_SUCCESS_PAYMENT</option></select>
  건수 <input id="count" type="number" value="30" min="1" max="500" style="width:5em">
  <button onclick="post('/api/incidents/data-pollution', {kind: v('kind'), count: parseInt(v('count'), 10)})">시작</button>
</fieldset>

<fieldset>
  <legend>진행 중 사건</legend>
  <button onclick="post('/api/incidents/end', {})">진행 중 사건 종료</button>
</fieldset>

<p id="message"></p>
<h2>현재 상태 (2초마다 갱신)</h2>
<pre id="status">-</pre>

<script>
const v = id => document.getElementById(id).value;
function headers() {
  const h = {"Content-Type": "application/json"};
  const token = v("token");  // 저장하지 않는다. 이 변수에만 있다
  if (token) h["Authorization"] = "Bearer " + token;
  return h;
}
function show(text) { document.getElementById("message").textContent = text; }
async function post(path, body) {
  try {
    const res = await fetch(path, {method: "POST", headers: headers(), body: JSON.stringify(body)});
    const data = await res.json();
    show(res.ok ? "완료: " + path : "오류 " + res.status + ": " + (data.error || ""));
    if (res.ok) document.getElementById("status").textContent = JSON.stringify(data, null, 2);
  } catch (e) { show("요청 실패: " + e.message); }
}
async function refresh() {
  try {
    const res = await fetch("/api/status", {headers: headers()});
    const data = await res.json();
    document.getElementById("status").textContent = res.ok ? JSON.stringify(data, null, 2) : "오류 " + res.status + ": " + (data.error || "");
  } catch (e) { document.getElementById("status").textContent = "서버에 연결할 수 없음"; }
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""
