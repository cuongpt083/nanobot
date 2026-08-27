const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('nanobotDesktop', {
  isElectron: true,
  getInfo: () => ipcRenderer.invoke('desktop:get-info'),
  selectFolder: () => ipcRenderer.invoke('desktop:select-folder'),
  openExternal: (url) => ipcRenderer.invoke('desktop:open-external', url),
  toggleSpotlight: () => ipcRenderer.invoke('desktop:toggle-spotlight'),
  sendNotification: (payload) => ipcRenderer.invoke('desktop:notify', payload),
  on: (channel, callback) => {
    const validChannels = [
      'new-chat',
      'open-settings',
      'workspace-selected',
      'navigate-tab',
      'trigger-dream-sync',
      'reload-mcp',
    ];
    if (validChannels.includes(channel)) {
      ipcRenderer.on(channel, (event, ...args) => callback(...args));
    }
  },
  off: (channel, callback) => {
    ipcRenderer.removeListener(channel, callback);
  },
});
