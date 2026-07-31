// ASTRA Renderer — app.js
// Handles UI logic, Python brain events, IPC, timer, gestures

const isElectron = typeof window.astra !== 'undefined';

// ── Clock ─────────────────────────────────────────────────────────────────────
function pad(n){ return String(n).padStart(2,'0'); }

function updateClock(){
  const now = new Date();
  const el = document.getElementById('clock');
  if(el) el.textContent = pad(now.getHours())+':'+pad(now.getMinutes())+':'+pad(now.getSeconds());

  const h = now.getHours();
  const greet = document.getElementById('greeting');
  if(greet){
    const salutation = h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
    greet.innerHTML = `${salutation}, <span style="color:var(--accent)">Commander.</span>`;
  }
}
setInterval(updateClock, 1000);
updateClock();

// ── View Navigation ───────────────────────────────────────────────────────────
function setView(el){
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  el.classList.add('active');
  const view = el.dataset.view;
  const target = document.getElementById('view-'+view);
  if(target) target.classList.add('active');
  if(view === 'memory') loadMemory();
  if(view === 'webhooks') refreshWebhookLog();
  if(view === 'missions') loadMissions();
  if(view === 'health') requestHealth();
}

function loadMissions(){
  if(isElectron) window.astra.sendToPython({ type: 'list_missions' });
  else renderMissions([
    {id:'system_scan',name:'System scan',desc:'Platform + Desktop list',icon:'radar-2'},
    {id:'desktop_inventory',name:'Desktop inventory',desc:'List Desktop files',icon:'folder'},
    {id:'focus_prep',name:'Focus prep',desc:'Deep-work checklist',icon:'target'},
  ]);
}

function renderMissions(list){
  const grid = document.getElementById('missions-grid');
  if(!grid) return;
  if(!list || !list.length){ grid.innerHTML = '<p class="sub">No missions</p>'; return; }
  grid.innerHTML = list.map(m => `
    <button type="button" class="mission-card" onclick="runMission('${m.id}')">
      <i class="ti ti-${m.icon || 'rocket'}"></i>
      <div class="mc-name">${m.name}</div>
      <div class="mc-status">${m.desc || ''}</div>
    </button>`).join('');
}

function runMission(id){
  pendingLog = 'dash-chat-log';
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const dashNav = document.querySelector('[data-view="dashboard"]');
  if(dashNav) dashNav.classList.add('active');
  document.getElementById('view-dashboard')?.classList.add('active');
  appendMsg('dash-chat-log', 'user', `Run mission: ${id}`);
  showTyping('dash-chat-log');
  if(isElectron) window.astra.sendToPython({ type: 'mission', id });
}

function requestHealth(){
  if(isElectron) window.astra.sendToPython({ type: 'health' });
}

function applyHealth(data){
  const s = data.subsystems || {};
  const set = (id, ok, label) => {
    const el = document.getElementById(id);
    if(!el) return;
    el.textContent = label || (ok ? 'OK' : 'OFF');
    el.className = 'hc-status ' + (ok ? 'ok' : 'bad');
  };
  set('h-cloud', s.cloud_llm, s.cloud_llm ? (s.cloud_provider || 'ready') : 'no key / credits');
  set('h-ollama', s.ollama);
  set('h-webhooks', s.webhooks, s.webhooks ? `:${data.webhook_port||9003}` : 'off');
  set('h-speech', s.speech);
  set('h-vision', s.vision);
  set('h-agent', s.agent_tools, 'ready');
  set('h-memory', s.memory, 'ready');
  const m = document.getElementById('h-model');
  if(m){ m.textContent = data.model || '—'; m.className = 'hc-status ok'; }
  const ts = document.getElementById('health-ts');
  if(ts) ts.textContent = 'Last probe: ' + (data.ts || new Date().toISOString());
}

function addMemoryNote(kind){
  const inp = document.getElementById('mem-input');
  const text = (inp?.value || '').trim();
  if(!text) return;
  if(isElectron) window.astra.sendToPython({ type: 'memory_add', text, kind });
  if(inp) inp.value = '';
}

function renderMemoryDump(data){
  const el = document.getElementById('memory-dump');
  if(!el) return;
  el.textContent = JSON.stringify(data || {}, null, 2);
}

// ── Mode Activation ───────────────────────────────────────────────────────────
function activateMode(el){
  document.querySelectorAll('.mode-card').forEach(c => {
    c.classList.remove('active-mode');
    c.querySelector('.mc-status').textContent = 'Standby';
    c.style.setProperty('--c', c.dataset.color);
  });
  el.classList.add('active-mode');
  el.querySelector('.mc-status').textContent = 'Active';
  el.style.setProperty('--c', el.dataset.color);
  const modeName = el.dataset.mode;
  const badge = document.getElementById('mode-badge');
  if(badge) badge.textContent = modeName;
  addCVEvent('mode', `Mode switched → ${modeName}`);
  appendMsg('dash-chat-log', 'astra', `${modeName} activated. Workspace optimized.`);
}

// Set color vars on load
document.querySelectorAll('.mode-card').forEach(c => c.style.setProperty('--c', c.dataset.color));

// ── Chat ──────────────────────────────────────────────────────────────────────
function appendMsg(logId, role, text){
  const log = document.getElementById(logId);
  if(!log) return;
  // Remove typing indicator if present
  const typing = log.querySelector('.typing-row');
  if(typing) typing.remove();

  const div = document.createElement('div');
  div.className = `msg ${role === 'user' ? 'user-msg' : 'astra-msg'}`;
  const now = new Date();
  const ts = pad(now.getHours())+':'+pad(now.getMinutes())+':'+pad(now.getSeconds());
  div.innerHTML = `<div class="msg-who">${role === 'user' ? 'YOU' : 'ASTRA'} // ${ts}</div><div class="msg-body">${text}</div>`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function showTyping(logId){
  const log = document.getElementById(logId);
  if(!log) return;
  const div = document.createElement('div');
  div.className = 'msg astra-msg typing-row';
  div.innerHTML = `<div class="msg-who">ASTRA // THINKING</div><div class="msg-body typing-body"><div class="dot-anim"><span></span><span></span><span></span></div></div>`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

let pendingLog = 'dash-chat-log';
let streamBuf = '';
let streamEl = null;

function beginStream(logId){
  const log = document.getElementById(logId);
  if(!log) return;
  const typing = log.querySelector('.typing-row');
  if(typing) typing.remove();
  streamBuf = '';
  const div = document.createElement('div');
  div.className = 'msg astra-msg stream-msg';
  const now = new Date();
  const ts = pad(now.getHours())+':'+pad(now.getMinutes())+':'+pad(now.getSeconds());
  div.innerHTML = `<div class="msg-who">ASTRA // ${ts}</div><div class="msg-body stream-body"></div>`;
  log.appendChild(div);
  streamEl = div.querySelector('.stream-body');
  log.scrollTop = log.scrollHeight;
}

function appendStreamDelta(text){
  if(!streamEl) beginStream(pendingLog);
  streamBuf += text;
  if(streamEl){
    streamEl.textContent = streamBuf;
    const log = streamEl.closest('.chat-log');
    if(log) log.scrollTop = log.scrollHeight;
  }
}

function endStream(finalText){
  if(finalText && streamEl) streamEl.textContent = finalText;
  else if(finalText && !streamEl) appendMsg(pendingLog, 'astra', finalText);
  streamEl = null;
  streamBuf = '';
}

function pushToolTrace(name, status, preview){
  const el = document.getElementById('tool-trace');
  if(!el) return;
  el.style.display = 'flex';
  const row = document.createElement('div');
  row.className = 'tool-row ' + (status || '');
  row.innerHTML = `<i class="ti ti-tool"></i><b>${name||'tool'}</b><span>${status||''}</span><code>${(preview||'').toString().slice(0,120)}</code>`;
  el.insertBefore(row, el.firstChild);
  while(el.children.length > 8) el.lastChild.remove();
}

async function sendToASTRA(text, logId, mode = 'default'){
  if(!text.trim()) return;
  appendMsg(logId, 'user', text);
  showTyping(logId);
  streamEl = null;
  streamBuf = '';

  if(isElectron){
    const agent = mode !== 'chat_only';
    window.astra.sendToPython({ type:'chat', text, mode, agent });
    pendingLog = logId;
  } else {
    await new Promise(r => setTimeout(r, 700));
    const reply = demoReply(text);
    appendMsg(logId, 'astra', reply);
  }
}

function sendDashChat(){
  const inp = document.getElementById('dash-input');
  const val = inp.value.trim();
  if(!val) return;
  inp.value = '';
  sendToASTRA(val, 'dash-chat-log');
}

function sendFullChat(){
  const inp = document.getElementById('chat-input');
  const mode = document.getElementById('model-select')?.value || 'default';
  const val = inp.value.trim();
  if(!val) return;
  inp.value = '';
  sendToASTRA(val, 'full-chat-log', mode);
}

function quickSend(text){
  document.getElementById('dash-input').value = text;
  sendDashChat();
}

document.getElementById('dash-input')?.addEventListener('keydown', e => { if(e.key === 'Enter') sendDashChat(); });
document.getElementById('chat-input')?.addEventListener('keydown', e => { if(e.key === 'Enter') sendFullChat(); });

// ── Demo Replies (fallback when no Python) ────────────────────────────────────
const DEMO = {
  'focus lock':   'Focus Lock engaged. Distracting apps restricted. Deep work timer active. Notifications muted.',
  'deep work':    'Deep work session initiated. 90-minute block active. All notifications muted.',
  'summarize':    'Today: 6/9 tasks complete. 3h 42m deep work logged. Pending: webhook engine, competitor research, Railway deploy.',
  'plan':         'Hour 1: ASTRA webhook engine. Hour 2: SaaS research. Hour 3: Railway deploy. Hour 4: JEE revision.',
  'market':       'BTC +2.4% at $67,420. Nifty mild correction -0.3%. ETH +1.8%. Gold steady. No major macro events tonight.',
  'debug':        'Paste your stack trace and I will isolate the root cause.',
  'deploy':       'Railway deployment requires your API key in Settings. Run: railway up --detach from your project root.',
  'research':     'Initiating research engine. What topic or competitors should I analyze?',
  'webhook':      'Webhooks live on http://localhost:9003 — POST /github, /stripe, /astra, or /custom/*.',
};

function demoReply(text){
  const lower = text.toLowerCase();
  for(const k in DEMO){ if(lower.includes(k)) return DEMO[k]; }
  return `Understood. Processing: "${text}" — Grok (xAI) is primary. Key is loaded from .env when running the desktop app.`;
}

// ── Focus Timer ───────────────────────────────────────────────────────────────
let timerSecs = 25*60, timerTotal = 25*60, timerRunning = false, timerInterval = null;

function toggleTimer(){
  const btn = document.getElementById('timer-start');
  if(!timerRunning){
    timerRunning = true;
    btn.textContent = 'PAUSE';
    btn.classList.remove('active');
    timerInterval = setInterval(() => {
      if(timerSecs > 0){
        timerSecs--;
        updateTimerDisplay();
      } else {
        clearInterval(timerInterval);
        timerRunning = false;
        btn.textContent = 'START';
        btn.classList.add('active');
        timerSecs = timerTotal;
        updateTimerDisplay();
        appendMsg('dash-chat-log','astra','Focus session complete. Time for a 5-minute break.');
      }
    }, 1000);
  } else {
    timerRunning = false;
    btn.textContent = 'START';
    btn.classList.add('active');
    clearInterval(timerInterval);
  }
}

function resetTimer(){
  clearInterval(timerInterval);
  timerRunning = false;
  timerSecs = timerTotal;
  updateTimerDisplay();
  const btn = document.getElementById('timer-start');
  btn.textContent = 'START';
  btn.classList.add('active');
}

function setTimer(mins){
  clearInterval(timerInterval);
  timerRunning = false;
  timerSecs = timerTotal = mins * 60;
  updateTimerDisplay();
  const btn = document.getElementById('timer-start');
  btn.textContent = 'START';
  btn.classList.add('active');
}

function updateTimerDisplay(){
  const el = document.getElementById('timer-val');
  if(el) el.textContent = pad(Math.floor(timerSecs/60))+':'+pad(timerSecs%60);
  const prog = document.getElementById('timer-prog');
  if(prog) prog.style.width = Math.round((timerSecs/timerTotal)*100)+'%';
}

// ── System Stats Simulation ───────────────────────────────────────────────────
setInterval(() => {
  const cpu = 25 + Math.floor(Math.random()*40);
  const ram = 52 + Math.floor(Math.random()*20);
  const net = 8  + Math.floor(Math.random()*55);
  const update = (bar,num,v) => {
    const b = document.getElementById(bar), n = document.getElementById(num);
    if(b) b.style.width = v+'%';
    if(n) n.textContent = v+'%';
  };
  update('s-cpu','n-cpu',cpu);
  update('s-ram','n-ram',ram);
  update('s-net','n-net',net);
  const tbCpu = document.getElementById('tb-cpu'), tbRam = document.getElementById('tb-ram');
  if(tbCpu) tbCpu.textContent = cpu;
  if(tbRam) tbRam.textContent = ram;
}, 3000);

// ── Tasks ─────────────────────────────────────────────────────────────────────
function checkTask(el){
  el.classList.add('done');
  el.innerHTML = '<i class="ti ti-check"></i>';
  const label = el.parentElement.querySelector('.task-label');
  if(label) label.classList.add('done-label');
}

function delTask(btn){
  btn.closest('.task-item').remove();
}

function addTask(){
  const label = prompt('Task description:');
  if(!label) return;
  const tag = prompt('Tag (CODE / STUDY / BUILD):','CODE').toUpperCase();
  const list = document.getElementById('task-list');
  const div = document.createElement('div');
  div.className = 'task-item';
  div.dataset.tag = tag;
  const tagClass = tag === 'STUDY' ? 'tag-study' : tag === 'BUILD' ? 'tag-build' : 'tag-code';
  div.innerHTML = `<div class="task-check" onclick="checkTask(this)"></div><span class="task-label">${label}</span><span class="task-tag ${tagClass}">${tag}</span><button class="task-del" onclick="delTask(this)"><i class="ti ti-x"></i></button>`;
  list.appendChild(div);
}

// ── CV Event Log ──────────────────────────────────────────────────────────────
function addCVEvent(type, text){
  const log = document.getElementById('cv-event-log');
  if(!log) return;
  const muted = log.querySelector('.muted');
  if(muted) muted.remove();
  const div = document.createElement('div');
  div.className = `cve-item ${type}`;
  const now = new Date();
  div.textContent = `[${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}] ${text}`;
  log.insertBefore(div, log.firstChild);
  if(log.children.length > 30) log.lastChild.remove();
}

// ── Webhook UI ────────────────────────────────────────────────────────────────
function setWebhookOnline(port, msg){
  const pill = document.getElementById('wh-status-pill');
  const m = document.getElementById('wh-status-msg');
  const url = document.getElementById('wh-base-url');
  const curl = document.getElementById('wh-curl');
  if(pill){ pill.textContent = 'ONLINE'; pill.classList.remove('off'); }
  if(m) m.textContent = msg || `Listening on port ${port || 9003}`;
  if(url) url.textContent = `http://localhost:${port || 9003}`;
  if(curl) curl.textContent = `curl -X POST http://localhost:${port || 9003}/astra \\\n  -H "Content-Type: application/json" \\\n  -d "{\\"text\\":\\"Hello ASTRA\\"}"`;
}

function pushWebhookLog(path, eventName, summary){
  const log = document.getElementById('wh-live-log');
  if(!log) return;
  if(log.querySelector('.wh-log-item') && log.textContent.includes('No events yet')) log.innerHTML = '';
  const now = new Date();
  const ts = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  const div = document.createElement('div');
  div.className = 'wh-log-item';
  div.innerHTML = `<span class="ts">${ts}</span> <span class="ev">${eventName || 'event'}</span> · <b>${path || '?'}</b><br/>${(summary || '').toString().slice(0,180)}`;
  log.insertBefore(div, log.firstChild);
  while(log.children.length > 40) log.lastChild.remove();
  const dot = document.getElementById('wh-nav-dot');
  if(dot) dot.style.display = 'block';
  addCVEvent('webhook', `Webhook ${path}: ${eventName || ''}`);
}

function testWebhook(){
  if(isElectron){
    window.astra.sendToPython({
      type: 'webhook_test',
      path: '/custom/ui-test',
      payload: { source: 'astra-ui', message: 'Test from ASTRA desktop', ts: new Date().toISOString() }
    });
  } else {
    pushWebhookLog('/custom/ui-test', 'test.ui', 'Demo mode — brain offline');
  }
  appendMsg('dash-chat-log', 'astra', 'Webhook test event fired.');
}

function refreshWebhookLog(){
  if(isElectron) window.astra.sendToPython({ type: 'get_webhook_log' });
}

function sendOutgoingWebhook(){
  const url = document.getElementById('wh-out-url')?.value?.trim();
  let payload = {};
  try { payload = JSON.parse(document.getElementById('wh-out-body')?.value || '{}'); }
  catch(_){ appendMsg('dash-chat-log','astra','Outgoing payload must be valid JSON.'); return; }
  if(!url){ appendMsg('dash-chat-log','astra','Enter a destination URL for the outgoing webhook.'); return; }
  if(isElectron){
    window.astra.sendToPython({ type: 'webhook_out', url, payload });
  }
  pushWebhookLog('OUT', 'webhook.out', url);
}

function copyCurl(){
  const t = document.getElementById('wh-curl')?.textContent || '';
  if(navigator.clipboard) navigator.clipboard.writeText(t).then(() => appendMsg('dash-chat-log','astra','Curl snippet copied.'));
}

// ── Python Brain Events ───────────────────────────────────────────────────────
function handleBrainEvent(raw){
  let data;
  try { data = typeof raw === 'string' ? JSON.parse(raw) : raw; }
  catch(_){ return; }

  const type = data.type;

  if(type === 'brain_ready'){
    setStatus('ONLINE', true);
    const pb = document.getElementById('provider-badge');
    if(pb) pb.textContent = (data.provider || 'Grok') + (data.model ? ' · ' + data.model : '');
    if(data.has_xai){
      setIndicator('ind-ollama', true);
      setCVStatus('cvs-ollama', 'ok', data.provider || 'Cloud');
    }
    if(isElectron){
      window.astra.sendToPython({ type: 'list_missions' });
      window.astra.sendToPython({ type: 'health' });
    }
  } else if(type === 'chat_start'){
    // typing already shown
  } else if(type === 'chat_delta'){
    appendStreamDelta(data.text || '');
  } else if(type === 'chat_response'){
    endStream(data.text);
    // remove leftover typing
    const log = document.getElementById(pendingLog);
    if(log){ const t = log.querySelector('.typing-row'); if(t) t.remove(); }
  } else if(type === 'tool_call'){
    pushToolTrace(data.name, data.status || 'run', JSON.stringify(data.args||{}));
  } else if(type === 'tool_result'){
    pushToolTrace(data.name, data.ok ? 'ok' : 'err', data.preview || '');
  } else if(type === 'missions_list'){
    renderMissions(data.missions || []);
  } else if(type === 'health'){
    applyHealth(data);
  } else if(type === 'memory_dump'){
    renderMemoryDump(data.data);
  } else if(type === 'memory_search_results'){
    renderMemoryDump({ hits: data.hits });
  } else if(type === 'speech_ready'){
    setIndicator('ind-speech', true);
    setCVStatus('cvs-whisper', 'ok', 'Online');
    addCVEvent('speech', 'Whisper STT ready — no wake word needed');
  } else if(type === 'speech_listening'){
    setIndicator('ind-speech', true);
    addCVEvent('speech', 'VAD active — listening');
  } else if(type === 'speech_transcript'){
    addCVEvent('speech', `Heard: "${data.text}"`);
    const pttInd = document.getElementById('ptt-ind');
    if(pttInd) pttInd.classList.remove('active');
    sendToASTRA(data.text, pendingLog);
  } else if(type === 'cv_ready'){
    setIndicator('ind-cam', true);
    setIndicator('ind-gesture', true);
    setCVStatus('cvs-mp', 'ok', 'Online');
    addCVEvent('gesture', 'MediaPipe loaded — gesture detection active');
  } else if(type === 'webcam_active'){
    setCVStatus('cvs-cam', 'ok', 'Online');
    addCVEvent('presence', 'Webcam active — presence tracking');
  } else if(type === 'gesture'){
    const g = data.gesture, action = data.action;
    addCVEvent('gesture', `Gesture: ${g} → ${action}`);
    updateGestureHUD(g);
    handleGestureAction(action);
  } else if(type === 'presence'){
    const p = data.present;
    const el = document.getElementById('m-presence');
    const bar = document.getElementById('m-presence-bar');
    if(el) el.textContent = p ? 'At desk' : 'Away';
    if(bar) bar.style.width = p ? '100%' : '0%';
    addCVEvent('presence', p ? 'User at desk' : 'User away');
  } else if(type === 'away_detected'){
    if(timerRunning){ clearInterval(timerInterval); timerRunning = false; appendMsg('dash-chat-log','astra','You stepped away — focus timer paused.'); }
  } else if(type === 'screen_insight'){
    const bar = document.getElementById('insight-bar');
    const txt = document.getElementById('insight-text');
    if(bar && txt){ txt.textContent = data.text; bar.style.display = 'flex'; }
    setCVStatus('cvs-screen', 'ok', 'Online');
    addCVEvent('mode', `Screen: ${data.text.substring(0,60)}...`);
  } else if(type === 'screen_watch_active'){
    setCVStatus('cvs-screen', 'ok', 'Online');
  } else if(type === 'webhook_server_ready'){
    setWebhookOnline(data.port, data.msg);
  } else if(type === 'webhook_in'){
    const summary = typeof data.payload === 'object' ? JSON.stringify(data.payload).slice(0,160) : String(data.payload||'');
    pushWebhookLog(data.path, data.event, summary);
    appendMsg('dash-chat-log', 'astra', `Webhook received: ${data.event || data.path}`);
  } else if(type === 'webhook_reply'){
    pushWebhookLog(data.path, 'astra.reply', data.reply);
    appendMsg('dash-chat-log', 'astra', `Webhook → Grok: ${data.reply}`);
  } else if(type === 'webhook_log'){
    const log = document.getElementById('wh-live-log');
    if(log && Array.isArray(data.items)){
      log.innerHTML = '';
      if(!data.items.length){
        log.innerHTML = '<div class="wh-log-item"><span class="ts">//</span> No stored webhook events yet.</div>';
      } else {
        data.items.slice().reverse().forEach(it => {
          pushWebhookLog(it.path, it.event, it.summary || '');
        });
      }
    }
  } else if(type === 'webhook_out_result'){
    appendMsg('dash-chat-log', 'astra', data.ok ? `Outgoing webhook OK → ${data.url}` : `Outgoing webhook failed → ${data.url}`);
  } else if(type === 'webhook_test_ok'){
    // already logged via webhook_in
  } else if(type === 'config_updated'){
    if(data.has_xai){ setIndicator('ind-ollama', true); setCVStatus('cvs-ollama','ok','Grok'); }
  } else if(type === 'warn'){
    console.warn('[ASTRA Brain]', data.msg);
    addCVEvent('mode', `⚠ ${data.msg}`);
    if(data.msg.includes('Whisper'))   setCVStatus('cvs-whisper','error','Install req.');
    if(data.msg.includes('MediaPipe')) setCVStatus('cvs-mp','error','Install req.');
    if(data.msg.includes('Webcam'))    setCVStatus('cvs-cam','error','Not found');
    if(data.msg.includes('Screen'))    setCVStatus('cvs-screen','error','Install req.');
    if(data.msg.includes('Ollama') || data.msg.includes('Grok')) setCVStatus('cvs-ollama','error','Check key');
  }
}

function handleGestureAction(action){
  switch(action){
    case 'gesture_focus_lock':
      const focusCard = document.querySelector('[data-mode="FOCUS LOCK"]');
      if(focusCard) activateMode(focusCard);
      break;
    case 'gesture_deep_work':
      if(!timerRunning) toggleTimer();
      appendMsg('dash-chat-log','astra','Deep work started via gesture.');
      break;
    case 'gesture_confirm':
      appendMsg('dash-chat-log','astra','Confirmed.');
      break;
    case 'gesture_mode_switch':
      appendMsg('dash-chat-log','astra','Mode switch gesture detected. Which mode?');
      break;
  }
}

function updateGestureHUD(gesture){
  const hud = document.getElementById('gesture-hud');
  const lbl = document.getElementById('gesture-label');
  const icons = {'FIST':'✊','OPEN_HAND':'🖐','PEACE':'✌️','THUMBS_UP':'👍','POINTING_UP':'☝️','POINTING_DOWN':'👇'};
  if(lbl) lbl.textContent = (icons[gesture]||'') + ' ' + gesture.replace('_',' ');
  if(hud){ hud.classList.add('active'); setTimeout(() => hud.classList.remove('active'), 2000); }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setStatus(text, online){
  const el = document.getElementById('status-text');
  if(el) el.textContent = text;
}

function setIndicator(id, active){
  const el = document.getElementById(id);
  if(el) el.classList.toggle('active', active);
}

function setCVStatus(id, state, label){
  const el = document.getElementById(id);
  if(!el) return;
  el.className = `cvs-badge ${state}`;
  el.textContent = label;
}

// ── Settings ──────────────────────────────────────────────────────────────────
async function loadSettings(){
  if(!isElectron) return;
  const xai = await window.astra.getStore('xai_key') || '';
  const xaiModel = await window.astra.getStore('xai_model') || 'grok-4.5';
  const key = await window.astra.getStore('anthropic_key') || '';
  const model = await window.astra.getStore('ollama_model') || 'llama3.1:8b';
  const whisper = await window.astra.getStore('whisper_model') || 'tiny';
  const sx = document.getElementById('s-xai'); if(sx && xai) sx.value = xai;
  const sxm = document.getElementById('s-xai-model'); if(sxm) sxm.value = xaiModel;
  const si = document.getElementById('s-anthropic'); if(si) si.value = key;
  const sm = document.getElementById('s-ollama-model'); if(sm) sm.value = model;
  const sw = document.getElementById('s-whisper'); if(sw) sw.value = whisper;
}

async function saveSettings(){
  const xai = document.getElementById('s-xai')?.value || '';
  const xaiModel = document.getElementById('s-xai-model')?.value || 'grok-4.5';
  const key = document.getElementById('s-anthropic')?.value || '';
  const model = document.getElementById('s-ollama-model')?.value || 'llama3.1:8b';
  const whisper = document.getElementById('s-whisper')?.value || 'tiny';
  const screenshot = parseInt(document.getElementById('s-screenshot')?.value || '10');
  const gestureConf = parseInt(document.getElementById('s-gesture-conf')?.value || '75');
  if(isElectron){
    await window.astra.setStore('xai_key', xai);
    await window.astra.setStore('xai_model', xaiModel);
    await window.astra.setStore('anthropic_key', key);
    await window.astra.setStore('ollama_model', model);
    await window.astra.setStore('whisper_model', whisper);
    window.astra.sendToPython({ type:'set_config', config:{
      xai_key: xai,
      xai_model: xaiModel,
      anthropic_key: key,
      ollama_model: model,
      whisper_model: whisper,
      screenshot_interval: screenshot,
      gesture_confidence: gestureConf/100
    }});
  }
  appendMsg('dash-chat-log','astra','Settings saved. Grok key applied for new messages.');
}

// ── Memory ────────────────────────────────────────────────────────────────────
async function loadMemory(){
  const el = document.getElementById('memory-dump');
  if(!el) return;
  if(!isElectron){ el.textContent = 'Connect ASTRA desktop app to view memory.'; return; }
  el.textContent = 'Loading...';
  window.astra.sendToPython({ type: 'memory_get' });
}

// ── Push-to-talk ──────────────────────────────────────────────────────────────
if(isElectron){
  window.astra.on('ptt-start', () => {
    const pttInd = document.getElementById('ptt-ind');
    if(pttInd) pttInd.classList.add('active');
    window.astra.sendToPython({type:'ptt_start'});
    addCVEvent('speech','Push-to-talk activated');
  });

  window.astra.on('activate-mode', (modeName) => {
    const card = document.querySelector(`[data-mode="${modeName}"]`);
    if(card) activateMode(card);
  });

  window.astra.on('python-event', handleBrainEvent);
  window.astra.on('ws-event', handleBrainEvent);

  loadSettings();
}

// ── Day Summary ───────────────────────────────────────────────────────────────
const summaries = [
  '// GROK ONLINE — WEBHOOKS ARMED ON :9003',
  '// ASTRA ONLINE — SYSTEMS NOMINAL',
  '// CONTEXT MEMORY ACTIVE — READY TO EXECUTE',
];
const sub = document.getElementById('day-summary');
if(sub) sub.textContent = summaries[Math.floor(Math.random()*summaries.length)];

// ── Boot sequence status ──────────────────────────────────────────────────────
setTimeout(() => setStatus('ONLINE', true), 800);
setTimeout(() => {
  if(!isElectron){
    setStatus('DEMO MODE', true);
    const pill = document.querySelector('.status-pill');
    if(pill){ pill.classList.remove('online'); pill.classList.add('demo'); }
    addCVEvent('mode','Running in browser demo — Electron not detected');
    addCVEvent('mode','All features available when running as desktop app');
    setCVStatus('cvs-whisper','error','Needs desktop');
    setCVStatus('cvs-mp','error','Needs desktop');
    setCVStatus('cvs-cam','error','Needs desktop');
    setCVStatus('cvs-screen','error','Needs desktop');
    setCVStatus('cvs-ollama','error','Needs desktop');
  } else {
    // Probe webhook health from renderer (brain may still be starting)
    fetch('http://localhost:9003/health').then(r => r.json()).then(j => {
      setWebhookOnline(j.port || 9003, j.status);
    }).catch(() => {});
  }
}, 1200);
