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

async function sendToASTRA(text, logId, mode = 'default'){
  if(!text.trim()) return;
  appendMsg(logId, 'user', text);
  showTyping(logId);

  if(isElectron){
    window.astra.sendToPython({ type:'chat', text, mode });
    // Response comes via python-event listener
    pendingLog = logId;
  } else {
    // Demo mode — pattern matching fallback
    await new Promise(r => setTimeout(r, 700));
    const reply = demoReply(text);
    appendMsg(logId, 'astra', reply);
  }
}

let pendingLog = 'dash-chat-log';

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
};

function demoReply(text){
  const lower = text.toLowerCase();
  for(const k in DEMO){ if(lower.includes(k)) return DEMO[k]; }
  return `Understood. Processing: "${text}" — Connect Claude API in Settings for full intelligence.`;
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

// ── Python Brain Events ───────────────────────────────────────────────────────
function handleBrainEvent(raw){
  let data;
  try { data = typeof raw === 'string' ? JSON.parse(raw) : raw; }
  catch(_){ return; }

  const type = data.type;

  if(type === 'brain_ready'){
    setStatus('ONLINE', true);
  } else if(type === 'chat_response'){
    appendMsg(pendingLog, 'astra', data.text);
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
  } else if(type === 'warn'){
    console.warn('[ASTRA Brain]', data.msg);
    addCVEvent('mode', `⚠ ${data.msg}`);
    // Mark relevant subsystem as error
    if(data.msg.includes('Whisper'))   setCVStatus('cvs-whisper','error','Install req.');
    if(data.msg.includes('MediaPipe')) setCVStatus('cvs-mp','error','Install req.');
    if(data.msg.includes('Webcam'))    setCVStatus('cvs-cam','error','Not found');
    if(data.msg.includes('Screen'))    setCVStatus('cvs-screen','error','Install req.');
    if(data.msg.includes('Ollama'))    setCVStatus('cvs-ollama','error','Not running');
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
  const key = await window.astra.getStore('anthropic_key') || '';
  const model = await window.astra.getStore('ollama_model') || 'llama3.1:8b';
  const whisper = await window.astra.getStore('whisper_model') || 'tiny';
  const si = document.getElementById('s-anthropic'); if(si) si.value = key;
  const sm = document.getElementById('s-ollama-model'); if(sm) sm.value = model;
  const sw = document.getElementById('s-whisper'); if(sw) sw.value = whisper;
}

async function saveSettings(){
  const key = document.getElementById('s-anthropic')?.value || '';
  const model = document.getElementById('s-ollama-model')?.value || 'llama3.1:8b';
  const whisper = document.getElementById('s-whisper')?.value || 'tiny';
  const screenshot = parseInt(document.getElementById('s-screenshot')?.value || '10');
  const gestureConf = parseInt(document.getElementById('s-gesture-conf')?.value || '75');
  if(isElectron){
    await window.astra.setStore('anthropic_key', key);
    await window.astra.setStore('ollama_model', model);
    await window.astra.setStore('whisper_model', whisper);
    window.astra.sendToPython({ type:'set_config', config:{
      anthropic_key: key,
      ollama_model: model,
      whisper_model: whisper,
      screenshot_interval: screenshot,
      gesture_confidence: gestureConf/100
    }});
  }
  appendMsg('dash-chat-log','astra','Settings saved. Restart ASTRA to apply all changes.');
}

// ── Memory ────────────────────────────────────────────────────────────────────
async function loadMemory(){
  const el = document.getElementById('memory-dump');
  if(!el) return;
  if(!isElectron){ el.textContent = 'Connect ASTRA desktop app to view memory.'; return; }
  // Memory is stored in brain/memory.json
  el.textContent = 'Loading...';
  window.astra.sendToPython({type:'ping'});
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
  '// 3 HIGH-PRIORITY OBJECTIVES DETECTED TODAY',
  '// ASTRA ONLINE — SYSTEMS NOMINAL',
  '// CONTEXT MEMORY ACTIVE — 12 SESSIONS LOADED',
];
const sub = document.getElementById('day-summary');
if(sub) sub.textContent = summaries[Math.floor(Math.random()*summaries.length)];

// ── Boot sequence status ──────────────────────────────────────────────────────
setTimeout(() => setStatus('ONLINE', true), 800);
setTimeout(() => {
  if(!isElectron){
    setStatus('DEMO MODE', true);
    addCVEvent('mode','Running in browser demo — Electron not detected');
    addCVEvent('mode','All features available when running as desktop app');
    setCVStatus('cvs-whisper','error','Needs desktop');
    setCVStatus('cvs-mp','error','Needs desktop');
    setCVStatus('cvs-cam','error','Needs desktop');
    setCVStatus('cvs-screen','error','Needs desktop');
    setCVStatus('cvs-ollama','error','Needs desktop');
  }
}, 1200);
