/**
 * ASTRA browser bridge — replaces Electron preload.
 * Connects UI ↔ Python brain over WebSocket.
 */
(function () {
  'use strict';

  const WS_URL = (location.protocol === 'https:' ? 'wss://' : 'ws://')
    + (location.hostname || '127.0.0.1')
    + ':' + (window.ASTRA_WS_PORT || '8788');

  const listeners = {
    'python-event': [],
    'ws-event': [],
    'ptt-start': [],
    'activate-mode': [],
  };

  let socket = null;
  let reconnectTimer = null;
  let outbox = [];
  let storeCache = {};

  try {
    storeCache = JSON.parse(localStorage.getItem('astra_store') || '{}') || {};
  } catch (_) {
    storeCache = {};
  }

  function persistStore() {
    try { localStorage.setItem('astra_store', JSON.stringify(storeCache)); } catch (_) {}
  }

  function fire(channel, data) {
    (listeners[channel] || []).forEach((fn) => {
      try { fn(data); } catch (e) { console.warn('listener', channel, e); }
    });
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return;
    }
    try {
      socket = new WebSocket(WS_URL);
    } catch (e) {
      console.error('WS create failed', e);
      scheduleReconnect();
      return;
    }

    socket.onopen = () => {
      console.log('[ASTRA] connected', WS_URL);
      fire('python-event', JSON.stringify({ type: 'brain_status', status: 'online', detail: 'websocket' }));
      // flush outbox
      while (outbox.length) {
        try { socket.send(outbox.shift()); } catch (_) { break; }
      }
      // probe
      send({ type: 'ping' });
      send({ type: 'health' });
      send({ type: 'rag_stats' });
      send({ type: 'mcp_status' });
    };

    socket.onmessage = (ev) => {
      const raw = ev.data;
      // Brain events are JSON strings (same as Electron python-event)
      fire('python-event', raw);
      try {
        const data = JSON.parse(raw);
        fire('ws-event', data);
      } catch (_) {}
    };

    socket.onclose = () => {
      console.warn('[ASTRA] disconnected — reconnecting…');
      fire('python-event', JSON.stringify({ type: 'brain_status', status: 'offline', detail: 'ws closed' }));
      scheduleReconnect();
    };

    socket.onerror = () => {
      try { socket.close(); } catch (_) {}
    };
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 1500);
  }

  function send(msg) {
    const payload = typeof msg === 'string' ? msg : JSON.stringify(msg);
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(payload);
    } else {
      outbox.push(payload);
      if (outbox.length > 100) outbox.shift();
      connect();
    }
  }

  window.astra = {
    // Store (localStorage)
    getStore: async (key) => storeCache[key],
    setStore: async (key, val) => { storeCache[key] = val; persistStore(); return true; },
    getAllStore: async () => ({ ...storeCache }),

    // Window chrome (no-op in browser — hide via CSS)
    minimize: () => {},
    maximize: () => {},
    close: () => { window.close(); },
    openExternal: (url) => { window.open(url, '_blank', 'noopener'); },

    // Brain
    sendToPython: (msg) => send(msg),

    on: (channel, fn) => {
      if (!listeners[channel]) listeners[channel] = [];
      listeners[channel].push(fn);
    },
    off: (channel) => {
      if (listeners[channel]) listeners[channel] = [];
    },

    // helpers
    isWeb: true,
    reconnect: connect,
    get wsUrl() { return WS_URL; },
  };

  document.documentElement.classList.add('astra-web');
  document.addEventListener('DOMContentLoaded', () => {
    document.body.classList.add('astra-web');
    // Hide native window controls that only made sense in Electron
    document.querySelectorAll('.win-btns').forEach((el) => { el.style.display = 'none'; });
    const tb = document.getElementById('tb-drag');
    if (tb) tb.style.webkitAppRegion = 'initial';
  });

  connect();
})();
