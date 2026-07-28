const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('astra', {
  // Store
  getStore: (key) => ipcRenderer.invoke('get-store', key),
  setStore: (key, val) => ipcRenderer.invoke('set-store', key, val),
  getAllStore: () => ipcRenderer.invoke('get-all-store'),

  // Window controls
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),
  openExternal: (url) => ipcRenderer.send('open-external', url),

  // Python brain bridge
  sendToPython: (msg) => ipcRenderer.send('send-to-python', msg),

  // Listeners
  on: (channel, fn) => {
    const allowed = ['python-event','ws-event','ptt-start','activate-mode'];
    if (allowed.includes(channel)) ipcRenderer.on(channel, (_, data) => fn(data));
  },
  off: (channel) => ipcRenderer.removeAllListeners(channel),
});
