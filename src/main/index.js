const { app, BrowserWindow, ipcMain, globalShortcut, Tray, Menu, shell, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const WebSocket = require('ws');

// electron-store v8 is ESM-only — load safely with fallback
let store = {
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
    } catch (e) { console.warn('store.set failed', e.message); }
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

let mainWindow, tray, pythonProcess, wsServer;

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
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    title: 'ASTRA',
  };
  if (fs.existsSync(iconPath)) opts.icon = iconPath;

  mainWindow = new BrowserWindow(opts);
  mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));
  mainWindow.once('ready-to-show', () => mainWindow.show());

  if (process.argv.includes('--dev')) {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }
}

function resolvePython() {
  // Prefer Windows `py` launcher, then python, then python3
  const candidates = process.platform === 'win32'
    ? ['py', 'python', 'python3']
    : ['python3', 'python'];
  return candidates[0];
}

function startPythonBrain() {
  const scriptPath = path.join(__dirname, '../brain/server.py');
  if (!fs.existsSync(scriptPath)) {
    console.warn('[Python] server.py not found');
    return;
  }

  const py = resolvePython();
  const args = process.platform === 'win32' && py === 'py'
    ? ['-3', scriptPath]
    : [scriptPath];

  try {
    pythonProcess = spawn(py, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: {
        ...process.env,
        PYTHONPATH: path.join(__dirname, '../brain'),
        PYTHONUNBUFFERED: '1',
      },
      windowsHide: true,
    });
  } catch (e) {
    console.warn('[Python] Failed to spawn:', e.message);
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

  pythonProcess.stderr.on('data', (data) => {
    console.error('[Python]', data.toString());
  });

  pythonProcess.on('error', (err) => {
    console.error('[Python] spawn error:', err.message);
  });

  pythonProcess.on('close', (code) => {
    console.log('[Python] Process exited:', code);
    pythonProcess = null;
  });
}

function startWSServer() {
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
    wsServer.on('error', (err) => {
      console.warn('[WS] Server error (port may be in use):', err.message);
    });
  } catch (e) {
    console.warn('[WS] Could not start server:', e.message);
  }
}

function setupTray() {
  try {
    const iconPath = getIconPath();
    let image = fs.existsSync(iconPath)
      ? nativeImage.createFromPath(iconPath)
      : nativeImage.createEmpty();
    if (image.isEmpty()) {
      // 16x16 transparent placeholder so tray still works
      image = nativeImage.createFromDataURL(
        'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAFUlEQVQ4T2NkYGD4z0AEYBxVSF+FAB5cAYf1YcQhAAAAAElFTkSuQmCC'
      );
    }
    tray = new Tray(image);
    const menu = Menu.buildFromTemplate([
      { label: 'Open ASTRA', click: () => { if (mainWindow) mainWindow.show(); } },
      { label: 'Focus Lock', click: () => { if (mainWindow) mainWindow.webContents.send('activate-mode', 'FOCUS LOCK'); } },
      { type: 'separator' },
      { label: 'Quit', click: () => app.quit() },
    ]);
    tray.setToolTip('ASTRA Online');
    tray.setContextMenu(menu);
    tray.on('click', () => {
      if (!mainWindow) return;
      mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
    });
  } catch (e) {
    console.warn('[Tray] setup failed:', e.message);
  }
}

function registerShortcuts() {
  try {
    globalShortcut.register('Alt+Space', () => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('ptt-start');
    });
    globalShortcut.register('CommandOrControl+Shift+A', () => {
      if (!mainWindow || mainWindow.isDestroyed()) return;
      mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
    });
    globalShortcut.register('CommandOrControl+Shift+F', () => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('activate-mode', 'FOCUS LOCK');
    });
  } catch (e) {
    console.warn('[Shortcuts] registration failed:', e.message);
  }
}

// IPC handlers
ipcMain.handle('get-store', (_, key) => store.get(key));
ipcMain.handle('set-store', (_, key, val) => { store.set(key, val); return true; });
ipcMain.handle('get-all-store', () => store.store);

ipcMain.on('window-minimize', () => mainWindow && mainWindow.minimize());
ipcMain.on('window-maximize', () => {
  if (!mainWindow) return;
  mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize();
});
ipcMain.on('window-close', () => mainWindow && mainWindow.hide());
ipcMain.on('open-external', (_, url) => shell.openExternal(url));

ipcMain.on('send-to-python', (_, msg) => {
  if (pythonProcess && pythonProcess.stdin && pythonProcess.stdin.writable) {
    try {
      pythonProcess.stdin.write(JSON.stringify(msg) + '\n');
    } catch (e) {
      console.warn('[Python] write failed:', e.message);
    }
  }
});

app.whenReady().then(() => {
  loadEnvFile();
  createWindow();
  setupTray();
  registerShortcuts();
  startWSServer();
  try { startPythonBrain(); } catch (e) { console.warn('Python brain not started:', e.message); }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
  else if (mainWindow) mainWindow.show();
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  if (pythonProcess) {
    try { pythonProcess.kill(); } catch (_) {}
  }
  if (wsServer) {
    try { wsServer.close(); } catch (_) {}
  }
});
