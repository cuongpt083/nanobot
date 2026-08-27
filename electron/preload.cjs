const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('nanobotDesktop', {
  isElectron: true,
  getInfo: () => ipcRenderer.invoke('desktop:get-info'),
  selectFolder: () => ipcRenderer.invoke('desktop:select-folder'),
  openExternal: (url) => ipcRenderer.invoke('desktop:open-external', url),
  toggleSpotlight: () => ipcRenderer.invoke('desktop:toggle-spotlight'),
  sendNotification: (payload) => ipcRenderer.invoke('desktop:notify', payload),

  // Gateway Process Management Bridge
  gateway: {
    getStatus: () => ipcRenderer.invoke('desktop:gateway-get-status'),
    getConfig: () => ipcRenderer.invoke('desktop:gateway-get-config'),
    saveConfig: (config) => ipcRenderer.invoke('desktop:gateway-save-config', config),
    start: () => ipcRenderer.invoke('desktop:gateway-start'),
    stop: () => ipcRenderer.invoke('desktop:gateway-stop'),
    restart: (config) => ipcRenderer.invoke('desktop:gateway-restart', config),
    getLogs: () => ipcRenderer.invoke('desktop:gateway-get-logs'),
    clearLogs: () => ipcRenderer.invoke('desktop:gateway-clear-logs'),
    ping: () => ipcRenderer.invoke('desktop:gateway-ping'),
    onLog: (callback) => {
      const handler = (event, data) => callback(data);
      ipcRenderer.on('desktop:gateway-log', handler);
      return () => ipcRenderer.removeListener('desktop:gateway-log', handler);
    },
    onStatusChange: (callback) => {
      const handler = (event, data) => callback(data);
      ipcRenderer.on('desktop:gateway-status-changed', handler);
      return () => ipcRenderer.removeListener('desktop:gateway-status-changed', handler);
    },
  },

  on: (channel, callback) => {
    const validChannels = [
      'new-chat',
      'open-settings',
      'workspace-selected',
      'navigate-tab',
      'trigger-dream-sync',
      'reload-mcp',
      'desktop:gateway-log',
      'desktop:gateway-status-changed',
    ];
    if (validChannels.includes(channel)) {
      ipcRenderer.on(channel, (event, ...args) => callback(...args));
    }
  },
  off: (channel, callback) => {
    ipcRenderer.removeListener(channel, callback);
  },
});
