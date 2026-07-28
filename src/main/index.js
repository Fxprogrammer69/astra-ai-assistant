const { app, BrowserWindow, ipcMain, globalShortcut, Tray, Menu, shell, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

// ── Crash / lifecycle log (Desktop-safe diagnostics) ─────────────────────────
const LOG = path.join(__dirname, '../../astra-runtime.log');
function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  try { fs.appendFileSync(LOG, line); } catch (_) {}
  try { console.log(msg); } catch (_) {}
}
process.on('uncaughtException', (e) => log('uncaughtException: ' + (e && e.stack ? e.stack : e)));
process.on('unhandledRejection', (e) => log('unhandledRejection: ' + e));
process.on('exit', (code) => log('process.exit code=' + code));
app.on('quit', () => log('app.quit'));
app.on('before-quit', () => log('before-quit'));
app.on('will-quit', () => log('will-quit'));
app.on('window-all-closed', () => log('window-all-closed'));
log('main starting electron=' + process.versions.electron);

// Optional deps
let WebSocket = null;
try {
  WebSocket = require('ws');
} catch (e) {
  log('ws module missing: ' + e.message);
}

// Simple JSON file store (avoids ESM electron-store issues)
const store = {
  get: (k) => {
    try {
      const p = path.join(app.getPath('userData'), 'config.json');
      if (!fs.existsSync(p)) return undefined;
      return JSON.parse(fs.readFileSync(p, 'utf8'))[k];
    } catch { return undefined; }
  },
  set: (k, v) => {
    try {
      const p = path.join(app.getPath('userData'), 'config.json');
      let data = {};
      if (fs.existsSync(p)) data = JSON.parse(fs.readFileSync(p, 'utf8'));
      data[k] = v;
      fs.writeFileSync(p, JSON.stringify(data, null, 2));
    } catch (e) { log('store.set failed ' + e.message); }
  },
  get store() {
    try {
      const p = path.join(app.getPath('userData'), 'config.json');
      if (!fs.existsSync(p)) return {};
      return JSON.parse(fs.readFileSync(p, 'utf8'));
    } catch { return {}; }
  },
};

function loadEnvFile() {
  const envPath = path.join(__dirname, '../../.env');
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith('#')) continue;
    const i = t.indexOf('=');
    if (i === -1) continue;
    const key = t.slice(0, i).trim();
    const val = t.slice(i + 1).trim();
    if (key && process.env[key] === undefined) process.env[key] = val;
  }
}

let mainWindow = null;
let tray = null;
let pythonProcess = null;
let wsServer = null;
let isQuitting = false;

function getIconPath() {
  return path.join(__dirname, '../../assets/icon.png');
}

function createWindow() {
  const iconPath = getIconPath();
  const opts = {
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    frame: false,
    transparent: false,
    backgroundColor: '#050810',
    show: true, // show immediately — avoid invisible hang
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
    title: 'ASTRA',
  };
  if (fs.existsSync(iconPath)) opts.icon = iconPath;

  mainWindow = new BrowserWindow(opts);
  log('BrowserWindow created');

  mainWindow.webContents.on('did-fail-load', (_e, code, desc, url) => {
    log('did-fail-load ' + code + ' ' + desc + ' ' + url);
  });
  mainWindow.webContents.on('did-finish-load', () => log('did-finish-load'));
  mainWindow.webContents.on('render-process-gone', (_e, details) => {
    log('renderer gone ' + JSON.stringify(details));
  });
  mainWindow.on('close', (e) => {
    // Keep app in tray unless user is quitting
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
      log('window hide (close intercepted)');
    } else {
      log('window close allowed (quitting)');
    }
  });
  mainWindow.on('closed', () => {
    log('window closed event');
    mainWindow = null;
  });

  const html = path.join(__dirname, '../renderer/index.html');
  log('loadFile ' + html);
  mainWindow.loadFile(html).catch((err) => log('loadFile error ' + err));
}

function startPythonBrain() {
  const scriptPath = path.join(__dirname, '../brain/server.py');
  if (!fs.existsSync(scriptPath)) {
    log('python server.py missing');
    return;
  }

  // Prefer py -3 on Windows
  const isWin = process.platform === 'win32';
  const cmd = isWin ? 'py' : 'python3';
  const args = isWin ? ['-3', scriptPath] : [scriptPath];

  try {
    pythonProcess = spawn(cmd, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: {
        ...process.env,
        PYTHONPATH: path.join(__dirname, '../brain'),
        PYTHONUNBUFFERED: '1',
      },
      windowsHide: true,
      detached: false,
    });
    log('python spawned pid=' + pythonProcess.pid);
  } catch (e) {
    log('python spawn failed: ' + e.message);
    return;
  }

  let buf = '';
  pythonProcess.stdout.on('data', (data) => {
    buf += data.toString();
    const lines = buf.split(/\r?\n/);
    buf = lines.pop() || '';
    for (const line of lines) {
      const msg = line.trim();
      if (msg && mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('python-event', msg);
      }
    }
  });
  pythonProcess.stderr.on('data', (data) => log('[Python stderr] ' + data.toString().slice(0, 500)));
  pythonProcess.on('error', (err) => log('python error: ' + err.message));
  pythonProcess.on('close', (code) => {
    log('python exited code=' + code);
    pythonProcess = null;
  });
}

function startWSServer() {
  if (!WebSocket) return;
  try {
    wsServer = new WebSocket.Server({ port: 9001 });
    wsServer.on('connection', (ws) => {
      ws.on('message', (msg) => {
        try {
          const data = JSON.parse(msg.toString());
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('ws-event', data);
          }
        } catch (_) {}
      });
    });
    wsServer.on('error', (err) => log('ws error: ' + err.message));
    log('ws listening on 9001');
  } catch (e) {
    log('ws start failed: ' + e.message);
  }
}

function setupTray() {
  try {
    const iconPath = getIconPath();
    let image = fs.existsSync(iconPath)
      ? nativeImage.createFromPath(iconPath)
      : nativeImage.createEmpty();
    if (image.isEmpty()) {
      image = nativeImage.createFromDataURL(
        'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAFUlEQVQ4T2NkYGD4z0AEYBxVSF+FAB5cAYf1YcQhAAAAAElFTkSuQmCC'
      );
    }
    tray = new Tray(image);
    const menu = Menu.buildFromTemplate([
      {
        label: 'Open ASTRA',
        click: () => {
          if (mainWindow) {
            mainWindow.show();
            mainWindow.focus();
          }
        },
      },
      {
        label: 'Focus Lock',
        click: () => {
          if (mainWindow) mainWindow.webContents.send('activate-mode', 'FOCUS LOCK');
        },
      },
      { type: 'separator' },
      {
        label: 'Quit',
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ]);
    tray.setToolTip('ASTRA Online');
    tray.setContextMenu(menu);
    tray.on('click', () => {
      if (!mainWindow) return;
      if (mainWindow.isVisible()) mainWindow.hide();
      else {
        mainWindow.show();
        mainWindow.focus();
      }
    });
    log('tray ready');
  } catch (e) {
    log('tray failed: ' + e.message);
  }
}

function registerShortcuts() {
  try {
    globalShortcut.register('Alt+Space', () => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('ptt-start');
    });
    globalShortcut.register('CommandOrControl+Shift+A', () => {
      if (!mainWindow || mainWindow.isDestroyed()) return;
      if (mainWindow.isVisible()) mainWindow.hide();
      else {
        mainWindow.show();
        mainWindow.focus();
      }
    });
    globalShortcut.register('CommandOrControl+Shift+F', () => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('activate-mode', 'FOCUS LOCK');
      }
    });
    log('shortcuts registered');
  } catch (e) {
    log('shortcuts failed: ' + e.message);
  }
}

// IPC
ipcMain.handle('get-store', (_, key) => store.get(key));
ipcMain.handle('set-store', (_, key, val) => {
  store.set(key, val);
  return true;
});
ipcMain.handle('get-all-store', () => store.store);

ipcMain.on('window-minimize', () => mainWindow && mainWindow.minimize());
ipcMain.on('window-maximize', () => {
  if (!mainWindow) return;
  if (mainWindow.isMaximized()) mainWindow.unmaximize();
  else mainWindow.maximize();
});
ipcMain.on('window-close', () => {
  if (mainWindow) mainWindow.hide();
});
ipcMain.on('open-external', (_, url) => shell.openExternal(url));
ipcMain.on('send-to-python', (_, msg) => {
  if (pythonProcess && pythonProcess.stdin && pythonProcess.stdin.writable) {
    try {
      pythonProcess.stdin.write(JSON.stringify(msg) + '\n');
    } catch (e) {
      log('python write failed: ' + e.message);
    }
  }
});

// Prevent second instance from weird multi-launch kills; focus existing
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  log('second instance — quitting this one');
  app.quit();
} else {
  app.on('second-instance', () => {
    log('second-instance focus');
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    log('app.whenReady');
    try { loadEnvFile(); } catch (e) { log('loadEnv ' + e.message); }
    try { createWindow(); } catch (e) { log('createWindow ' + e.stack); }
    try { setupTray(); } catch (e) { log('setupTray ' + e.stack); }
    try { registerShortcuts(); } catch (e) { log('shortcuts ' + e.stack); }
    try { startWSServer(); } catch (e) { log('ws ' + e.stack); }
    // Delay python so UI comes up first
    setTimeout(() => {
      try { startPythonBrain(); } catch (e) { log('python ' + e.stack); }
    }, 1500);
    setInterval(() => log('heartbeat visible=' + !!(mainWindow && mainWindow.isVisible())), 5000);
  });
}

// Do NOT quit when window is hidden — only on explicit Quit from tray
app.on('window-all-closed', (e) => {
  log('window-all-closed (ignored — stay in tray)');
  // prevent default quit on Windows
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
  else if (mainWindow) mainWindow.show();
});

app.on('will-quit', () => {
  isQuitting = true;
  try { globalShortcut.unregisterAll(); } catch (_) {}
  if (pythonProcess) {
    try { pythonProcess.kill(); } catch (_) {}
  }
  if (wsServer) {
    try { wsServer.close(); } catch (_) {}
  }
});
