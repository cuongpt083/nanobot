const { contextBridge, ipcRenderer } = require('electron');

const listenerMap = new Map();

contextBridge.exposeInMainWorld('nanobotDesktop', {
  isElectron: true,
  getInfo: () => ipcRenderer.invoke('desktop:get-info'),
  selectFolder: () => ipcRenderer.invoke('desktop:select-folder'),
  openExternal: (url) => ipcRenderer.invoke('desktop:open-external', url),
  toggleSpotlight: () => ipcRenderer.invoke('desktop:toggle-spotlight'),
  sendNotification: (payload) => ipcRenderer.invoke('desktop:notify', payload),

  // Window Controls Bridge
  minimizeWindow: () => ipcRenderer.invoke('desktop:window-minimize'),
  maximizeWindow: () => ipcRenderer.invoke('desktop:window-maximize'),
  closeWindow: () => ipcRenderer.invoke('desktop:window-close'),
  isMaximized: () => ipcRenderer.invoke('desktop:window-is-maximized'),
  setAlwaysOnTop: (flag) => ipcRenderer.invoke('desktop:set-always-on-top', flag),

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

  // First-run Environment Setup & Provisioning Bridge
  setup: {
    getStatus: () => ipcRenderer.invoke('desktop:setup-get-status'),
    runSetup: (options) => ipcRenderer.invoke('desktop:setup-run', options),
    onProgress: (callback) => {
      const handler = (event, data) => callback(data);
      ipcRenderer.on('desktop:setup-progress', handler);
      return () => ipcRenderer.removeListener('desktop:setup-progress', handler);
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
      'desktop:setup-progress',
    ];
    if (validChannels.includes(channel)) {
      const handler = (event, ...args) => callback(...args);
      if (!listenerMap.has(channel)) {
        listenerMap.set(channel, new Map());
      }
      listenerMap.get(channel).set(callback, handler);
      ipcRenderer.on(channel, handler);
    }
  },
  off: (channel, callback) => {
    if (listenerMap.has(channel)) {
      const channelListeners = listenerMap.get(channel);
      if (channelListeners.has(callback)) {
        const handler = channelListeners.get(callback);
        ipcRenderer.removeListener(channel, handler);
        channelListeners.delete(callback);
      }
    }
  },
});

