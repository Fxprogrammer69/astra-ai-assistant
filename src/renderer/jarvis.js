/**
 * ASTRA Jarvis layer — voice that works in Electron.
 * Primary: MediaRecorder/WAV → Python STT (Whisper or SpeechRecognition)
 * Fallback: Web Speech API when available
 * TTS: speechSynthesis
 */
(function () {
  'use strict';

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;

  const state = {
    mode: 'idle',
    continuous: false,
    wakeEnabled: true,
    voiceEnabled: true,
    ttsEnabled: false, // off by default for speed; toggle in UI
    camOn: false,
    lastHeard: '',
    stream: null,
    recognition: null,
    restartTimer: null,
    recording: false,
    mediaRecorder: null,
    audioChunks: [],
    micStream: null,
    useWebSpeech: false,
  };

  function $(id) { return document.getElementById(id); }

  function setOrb(mode) {
    state.mode = mode;
    const core = $('jarvis-core');
    const label = $('jarvis-state-label');
    const ring = $('jarvis-ring');
    if (core) {
      core.classList.remove('idle', 'listening', 'thinking', 'speaking');
      core.classList.add(mode || 'idle');
    }
    if (ring) {
      ring.classList.remove('idle', 'listening', 'thinking', 'speaking');
      ring.classList.add(mode || 'idle');
    }
    const labels = {
      idle: 'STANDBY',
      listening: 'LISTENING',
      thinking: 'PROCESSING',
      speaking: 'SPEAKING',
    };
    if (label) label.textContent = labels[mode] || 'STANDBY';
    document.body.classList.toggle('jarvis-listening', mode === 'listening');
    document.body.classList.toggle('jarvis-thinking', mode === 'thinking');
    document.body.classList.toggle('jarvis-speaking', mode === 'speaking');
  }

  function setHeard(text) {
    state.lastHeard = text || '';
    const el = $('jarvis-heard');
    if (el) el.textContent = text ? `"${text}"` : 'Hold Speak / Alt+Space — then talk';
    const live = $('voice-live-text');
    if (live) live.textContent = text || '—';
  }

  function pulseBars(active) {
    document.querySelectorAll('.jv-bar').forEach((b, i) => {
      if (active) {
        b.style.animationDuration = (0.35 + (i % 5) * 0.08) + 's';
        b.classList.add('on');
      } else b.classList.remove('on');
    });
  }

  function setIndicatorSafe(on) {
    const ind = $('ind-speech');
    if (ind) ind.classList.toggle('on', !!on);
    const ptt = $('ptt-ind');
    if (ptt) ptt.classList.toggle('active', !!on);
    const btn = $('jv-listen-btn');
    if (btn) btn.classList.toggle('active', !!state.continuous || !!on);
    if (typeof setCVStatus === 'function') {
      setCVStatus('cvs-whisper', on || state.continuous ? 'ok' : 'loading',
        on || state.continuous ? (state.useWebSpeech ? 'Web Speech' : 'Mic STT') : 'Idle');
    }
  }

  // ── TTS ────────────────────────────────────────────────────────────────────
  function pickVoice() {
    if (!synth) return null;
    const voices = synth.getVoices() || [];
    const prefer = [/microsoft (aria|guy|zira|david)/i, /google us english/i, /en-us/i, /english/i];
    for (const re of prefer) {
      const v = voices.find((x) => re.test(x.name) || re.test(x.lang));
      if (v) return v;
    }
    return voices.find((v) => /^en/i.test(v.lang)) || voices[0] || null;
  }

  function speak(text) {
    if (!state.ttsEnabled || !synth || !text) return;
    const clean = String(text)
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/[*_#`>|]/g, ' ')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 400);
    if (!clean || clean.startsWith('RELEVANT MEMORY')) return;
    try { synth.cancel(); } catch (_) {}
    const u = new SpeechSynthesisUtterance(clean);
    const voice = pickVoice();
    if (voice) u.voice = voice;
    u.rate = 1.05;
    u.pitch = 0.95;
    u.onstart = () => { setOrb('speaking'); pulseBars(true); };
    u.onend = () => {
      pulseBars(false);
      setOrb(state.continuous ? 'listening' : 'idle');
      if (state.continuous) startListening({ silent: true });
    };
    u.onerror = () => { pulseBars(false); setOrb('idle'); };
    synth.speak(u);
  }

  function stopSpeaking() {
    try { synth && synth.cancel(); } catch (_) {}
  }

  // ── Local voice commands ───────────────────────────────────────────────────
  function localCommand(raw) {
    const t = (raw || '').toLowerCase().trim();
    if (!t) return null;
    if (/^(astra|hey astra|ok astra|okay astra)[\s,.!?]*$/i.test(t)) {
      return { type: 'ack', speak: 'Yes?', action: () => setOrb('listening') };
    }
    const strip = t.replace(/^(hey |ok |okay )?astra[,:\s]+/i, '').trim();
    if (/^(focus lock|activate focus)/.test(strip)) {
      return {
        type: 'cmd', speak: 'Focus lock on.',
        action: () => {
          const card = document.querySelector('[data-mode="FOCUS LOCK"]');
          if (card && typeof activateMode === 'function') activateMode(card);
          if (typeof toggleTimer === 'function') toggleTimer();
        },
      };
    }
    if (/^(what time is it|time now)/.test(strip)) {
      const s = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      return { type: 'cmd', speak: `It is ${s}.`, action: () => {} };
    }
    if (/^(stop listening|sleep|standby)/.test(strip)) {
      return {
        type: 'cmd', speak: 'Standing by.',
        action: () => { state.continuous = false; stopListening(); setOrb('idle'); },
      };
    }
    if (/^(mute|be quiet|stop talking)/.test(strip)) {
      return { type: 'cmd', speak: '', action: () => { stopSpeaking(); setOrb('idle'); } };
    }
    if (/^(who are you)/.test(strip)) {
      return {
        type: 'cmd',
        speak: 'I am ASTRA, your desktop assistant.',
        action: () => {},
      };
    }
    if (/^(hey |ok |okay )?astra\b/i.test(t) && strip) return { type: 'chat', text: strip };
    if (state.continuous) return { type: 'chat', text: strip || t };
    return { type: 'chat', text: strip || t };
  }

  function pendingLogId() {
    const dash = document.getElementById('view-dashboard');
    if (dash && dash.classList.contains('active')) return 'dash-chat-log';
    return 'full-chat-log';
  }

  function handleTranscript(text, isFinal) {
    if (!text) return;
    setHeard(text);
    if (!isFinal) return;
    const cmd = localCommand(text);
    if (!cmd) return;
    if (cmd.type === 'ack') {
      if (cmd.speak) speak(cmd.speak);
      if (cmd.action) cmd.action();
      return;
    }
    if (cmd.type === 'cmd') {
      if (cmd.action) cmd.action();
      if (cmd.speak) speak(cmd.speak);
      if (typeof appendMsg === 'function') {
        appendMsg(pendingLogId(), 'user', text);
        if (cmd.speak) appendMsg(pendingLogId(), 'astra', cmd.speak);
      }
      return;
    }
    if (cmd.type === 'chat') {
      stopSpeaking();
      setOrb('thinking');
      pulseBars(true);
      if (typeof sendToASTRA === 'function') sendToASTRA(cmd.text, pendingLogId(), 'default');
    }
  }

  // ── WAV encode helpers ─────────────────────────────────────────────────────
  function floatTo16BitPCM(float32) {
    const buf = new ArrayBuffer(float32.length * 2);
    const view = new DataView(buf);
    for (let i = 0; i < float32.length; i++) {
      let s = Math.max(-1, Math.min(1, float32[i]));
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return buf;
  }

  function encodeWav(samples, sampleRate) {
    const pcm = floatTo16BitPCM(samples);
    const buffer = new ArrayBuffer(44 + pcm.byteLength);
    const view = new DataView(buffer);
    const writeStr = (o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
    writeStr(0, 'RIFF');
    view.setUint32(4, 36 + pcm.byteLength, true);
    writeStr(8, 'WAVE');
    writeStr(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, 'data');
    view.setUint32(40, pcm.byteLength, true);
    new Uint8Array(buffer, 44).set(new Uint8Array(pcm));
    return buffer;
  }

  function arrayBufferToBase64(buffer) {
    let binary = '';
    const bytes = new Uint8Array(buffer);
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  }

  // ── Mic capture → WAV → Python STT ─────────────────────────────────────────
  async function startMicCapture() {
    if (state.recording) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setHeard('Microphone API unavailable in this window.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      });
      state.micStream = stream;
      state.recording = true;
      setOrb('listening');
      pulseBars(true);
      setIndicatorSafe(true);
      setHeard('Listening… speak now, then release / click again to stop');

      const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      // Some systems ignore requested rate — read actual
      const sampleRate = ctx.sampleRate || 16000;
      const source = ctx.createMediaStreamSource(stream);
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      const chunks = [];
      let total = 0;
      const maxSamples = sampleRate * 12; // 12s max

      processor.onaudioprocess = (e) => {
        if (!state.recording) return;
        const data = e.inputBuffer.getChannelData(0);
        chunks.push(new Float32Array(data));
        total += data.length;
        if (total >= maxSamples) stopMicCapture();
      };
      source.connect(processor);
      processor.connect(ctx.destination);

      state._audioCtx = ctx;
      state._audioProc = processor;
      state._audioSrc = source;
      state._audioChunks = chunks;
      state._audioSampleRate = sampleRate;
      state._audioTotal = () => total;

      // Auto-stop after 8s of PTT if user doesn't click again
      clearTimeout(state._autoStop);
      state._autoStop = setTimeout(() => {
        if (state.recording) stopMicCapture();
      }, 8000);
    } catch (e) {
      setHeard('Mic permission denied — allow microphone for ASTRA in Windows settings.');
      state.recording = false;
      setOrb('idle');
      pulseBars(false);
      if (typeof addCVEvent === 'function') addCVEvent('speech', 'Mic error: ' + (e.message || e));
    }
  }

  function stopMicCapture() {
    if (!state.recording && !state.micStream) return;
    state.recording = false;
    clearTimeout(state._autoStop);
    pulseBars(false);
    setIndicatorSafe(false);

    try {
      if (state._audioProc) state._audioProc.disconnect();
      if (state._audioSrc) state._audioSrc.disconnect();
      if (state._audioCtx) state._audioCtx.close();
    } catch (_) {}

    if (state.micStream) {
      state.micStream.getTracks().forEach((t) => t.stop());
      state.micStream = null;
    }

    const chunks = state._audioChunks || [];
    const sampleRate = state._audioSampleRate || 16000;
    if (!chunks.length) {
      setHeard('No audio captured.');
      setOrb('idle');
      return;
    }

    // Merge
    let len = 0;
    chunks.forEach((c) => { len += c.length; });
    const merged = new Float32Array(len);
    let off = 0;
    chunks.forEach((c) => { merged.set(c, off); off += c.length; });

    // Simple energy gate — ignore silence
    let peak = 0;
    for (let i = 0; i < merged.length; i += 32) peak = Math.max(peak, Math.abs(merged[i]));
    if (peak < 0.01) {
      setHeard('Too quiet — try again closer to the mic.');
      setOrb('idle');
      return;
    }

    const wav = encodeWav(merged, sampleRate);
    const b64 = arrayBufferToBase64(wav);
    setHeard('Transcribing…');
    setOrb('thinking');

    if (window.astra && window.astra.sendToPython) {
      window.astra.sendToPython({
        type: 'transcribe',
        audio_b64: b64,
        mime: 'audio/wav',
        sample_rate: sampleRate,
      });
      // Timeout if brain never replies
      clearTimeout(state._sttTimeout);
      state._sttTimeout = setTimeout(() => {
        if (state.mode === 'thinking') {
          setHeard('STT timeout — is the brain online? Try pip install openai-whisper');
          setOrb('idle');
        }
      }, 45000);
    } else {
      setHeard('Desktop bridge missing — run ASTRA app, not browser demo.');
      setOrb('idle');
    }

    state._audioChunks = [];
  }

  // ── Web Speech fallback (often broken in Electron) ─────────────────────────
  function ensureRecognition() {
    if (!SR) return null;
    if (state.recognition) return state.recognition;
    const rec = new SR();
    rec.continuous = false;
    rec.interimResults = true;
    rec.lang = 'en-US';
    rec.onstart = () => { setOrb('listening'); pulseBars(true); setIndicatorSafe(true); };
    rec.onresult = (ev) => {
      let interim = '', finalText = '';
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        if (r.isFinal) finalText += r[0].transcript;
        else interim += r[0].transcript;
      }
      if (interim) setHeard(interim);
      if (finalText) handleTranscript(finalText.trim(), true);
    };
    rec.onerror = (ev) => {
      const err = ev.error || 'error';
      if (err !== 'no-speech' && err !== 'aborted') {
        // Fall back to mic capture
        setHeard('Web Speech failed (' + err + ') — using mic capture…');
        state.useWebSpeech = false;
        startMicCapture();
      }
      pulseBars(false);
    };
    rec.onend = () => {
      pulseBars(false);
      setIndicatorSafe(!!state.continuous);
      if (state.continuous && state.mode !== 'thinking' && state.mode !== 'speaking') {
        clearTimeout(state.restartTimer);
        state.restartTimer = setTimeout(() => startListening({ silent: true }), 300);
      } else if (state.mode === 'listening') setOrb('idle');
    };
    state.recognition = rec;
    return rec;
  }

  function startListening(opts = {}) {
    if (!state.voiceEnabled) return;
    stopSpeaking();

    // Toggle stop if already recording
    if (state.recording) {
      stopMicCapture();
      return;
    }

    // Prefer mic capture (reliable in Electron). Web Speech only if user forced it.
    if (state.useWebSpeech && SR) {
      const rec = ensureRecognition();
      if (rec) {
        try { rec.abort(); } catch (_) {}
        try {
          rec.start();
          if (!opts.silent) setHeard('Listening (Web Speech)…');
          return;
        } catch (_) {}
      }
    }
    startMicCapture();
  }

  function stopListening() {
    clearTimeout(state.restartTimer);
    if (state.recording) stopMicCapture();
    try { if (state.recognition) state.recognition.stop(); } catch (_) {}
    setIndicatorSafe(false);
  }

  function toggleContinuous() {
    state.continuous = !state.continuous;
    const btn = $('jv-listen-btn');
    if (btn) btn.classList.toggle('active', state.continuous);
    if (state.continuous) {
      setHeard('Always-listen: click Speak, talk, click again — repeats');
      startListening();
      if (typeof addCVEvent === 'function') addCVEvent('speech', 'Continuous voice ON');
    } else {
      stopListening();
      setOrb('idle');
      if (typeof addCVEvent === 'function') addCVEvent('speech', 'Continuous voice OFF');
    }
  }

  async function toggleCamera() {
    const video = $('jarvis-cam');
    const btn = $('jv-cam-btn');
    if (state.camOn) {
      if (state.stream) state.stream.getTracks().forEach((t) => t.stop());
      state.stream = null;
      if (video) {
        video.srcObject = null;
        video.classList.remove('on');
        if (video.parentElement) video.parentElement.style.display = 'none';
      }
      state.camOn = false;
      if (btn) btn.classList.remove('active');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
      state.stream = stream;
      state.camOn = true;
      if (video) {
        video.srcObject = stream;
        video.classList.add('on');
        if (video.parentElement) video.parentElement.style.display = 'block';
        video.play().catch(() => {});
      }
      if (btn) btn.classList.add('active');
    } catch (e) {
      setHeard('Camera permission denied.');
    }
  }

  function onChatStart() {
    stopSpeaking();
    setOrb('thinking');
    pulseBars(true);
  }

  function onChatResponse(text) {
    clearTimeout(state._sttTimeout);
    pulseBars(false);
    if (text && !String(text).startsWith('RELEVANT MEMORY')) speak(text);
    else setOrb(state.continuous ? 'listening' : 'idle');
  }

  function onSpeechTranscript(text) {
    clearTimeout(state._sttTimeout);
    handleTranscript(text, true);
  }

  function onSpeechError(msg) {
    clearTimeout(state._sttTimeout);
    setHeard(msg || 'Speech error');
    setOrb('idle');
    pulseBars(false);
    if (typeof addCVEvent === 'function') addCVEvent('speech', msg || 'error');
  }

  function boot() {
    if (synth) {
      synth.getVoices();
      if (typeof speechSynthesis !== 'undefined') {
        speechSynthesis.onvoiceschanged = () => synth.getVoices();
      }
    }
    // Respect checkbox if present
    const ttsToggle = $('jv-tts-toggle');
    if (ttsToggle) {
      state.ttsEnabled = !!ttsToggle.checked;
      ttsToggle.addEventListener('change', () => {
        state.ttsEnabled = !!ttsToggle.checked;
        if (!state.ttsEnabled) stopSpeaking();
      });
    }

    setOrb('idle');
    setHeard('Click Speak, talk, click again to send');

    const listenBtn = $('jv-listen-btn');
    if (listenBtn) listenBtn.addEventListener('click', () => toggleContinuous());

    const ptt = $('ptt-ind');
    if (ptt) {
      ptt.style.cursor = 'pointer';
      ptt.title = 'Click: start/stop voice';
      ptt.addEventListener('click', () => startListening());
    }

    const micFab = $('jarvis-mic-fab');
    if (micFab) {
      micFab.addEventListener('click', () => startListening());
      // Hold-to-talk
      micFab.addEventListener('mousedown', (e) => {
        if (e.button === 0 && !state.recording) startMicCapture();
      });
      micFab.addEventListener('mouseup', () => {
        if (state.recording) stopMicCapture();
      });
      micFab.addEventListener('mouseleave', () => {
        if (state.recording) stopMicCapture();
      });
    }

    const camBtn = $('jv-cam-btn');
    if (camBtn) camBtn.addEventListener('click', () => toggleCamera());

    document.addEventListener('keydown', (e) => {
      if (e.altKey && e.code === 'Space') {
        e.preventDefault();
        startListening();
      }
    });

    setTimeout(() => {
      if (typeof setCVStatus === 'function') {
        setCVStatus('cvs-whisper', 'ok', 'Mic STT ready');
      }
      const ind = $('ind-speech');
      if (ind) ind.classList.add('on');
    }, 600);
  }

  window.AstraJarvis = {
    boot,
    speak,
    stopSpeaking,
    startListening,
    stopListening,
    toggleContinuous,
    toggleCamera,
    onChatStart,
    onChatResponse,
    onSpeechTranscript,
    onSpeechError,
    setOrb,
    state,
  };
})();
