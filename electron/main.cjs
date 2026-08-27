const { app, BrowserWindow, ipcMain, globalShortcut, Tray, Menu, nativeImage, dialog, shell } = require('electron');
const path = require('path');
const fs = require('fs');

let mainWindow = null;
let quickSummonWindow = null;
let tray = null;
let isQuitting = false;

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;
const PORT = process.env.PORT || 3000;
const SERVER_URL = isDev ? `http://localhost:${PORT}` : `http://localhost:${PORT}`;

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 640,
    title: 'Nanobot Desktop',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    trafficLightPosition: { x: 14, y: 14 },
    backgroundColor: '#09090b',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
    },
  });

  mainWindow.loadURL(SERVER_URL);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
      return false;
    }
  });

  setupAppMenu();
}

function createQuickSummonWindow() {
  quickSummonWindow = new BrowserWindow({
    width: 680,
    height: 480,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  quickSummonWindow.loadURL(`${SERVER_URL}?mode=spotlight`);

  quickSummonWindow.on('blur', () => {
    if (quickSummonWindow && !quickSummonWindow.webContents.isDevToolsOpened()) {
      quickSummonWindow.hide();
    }
  });
}

function toggleQuickSummon() {
  if (!quickSummonWindow) {
    createQuickSummonWindow();
  }
  if (quickSummonWindow.isVisible()) {
    quickSummonWindow.hide();
  } else {
    quickSummonWindow.center();
    quickSummonWindow.show();
    quickSummonWindow.focus();
  }
}

function createTray() {
  // Create a minimal 16x16 tray icon representation
  const iconPath = path.join(__dirname, '../public/icon.png');
  let icon = null;
  if (fs.existsSync(iconPath)) {
    icon = nativeImage.createFromPath(iconPath).resize({ width: 18, height: 18 });
  } else {
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  tray.setToolTip('Nanobot AI Agent Gateway (Active)');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show Nanobot Desktop',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    {
      label: 'Quick Summon (Alt + Space)',
      click: toggleQuickSummon,
    },
    { type: 'separator' },
    {
      label: 'MCP Servers Status: 5 Active',
      enabled: false,
    },
    {
      label: 'Memory Status: Synced',
      enabled: false,
    },
    { type: 'separator' },
    {
      label: 'Open Workspace Folder...',
      click: async () => {
        const res = await dialog.showOpenDialog(mainWindow, {
          properties: ['openDirectory'],
        });
        if (!res.canceled && res.filePaths[0]) {
          shell.openPath(res.filePaths[0]);
        }
      },
    },
    {
      label: 'Nanobot Documentation',
      click: () => shell.openExternal('https://github.com/nanobot-ai/nanobot'),
    },
    { type: 'separator' },
    {
      label: 'Quit Nanobot',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

function setupAppMenu() {
  const isMac = process.platform === 'darwin';
  const template = [
    ...(isMac
      ? [
          {
            label: 'Nanobot',
            submenu: [
              { role: 'about', label: 'About Nanobot Desktop' },
              { type: 'separator' },
              {
                label: 'Preferences...',
                accelerator: 'Cmd+,',
                click: () => mainWindow?.webContents.send('open-settings'),
              },
              { type: 'separator' },
              { role: 'services' },
              { type: 'separator' },
              { role: 'hide' },
              { role: 'hideOthers' },
              { role: 'unhide' },
              { type: 'separator' },
              {
                label: 'Quit Nanobot',
                accelerator: 'Cmd+Q',
                click: () => {
                  isQuitting = true;
                  app.quit();
                },
              },
            ],
          },
        ]
      : []),
    {
      label: 'File',
      submenu: [
        {
          label: 'New Agent Chat',
          accelerator: 'CmdOrCtrl+N',
          click: () => mainWindow?.webContents.send('new-chat'),
        },
        {
          label: 'Open Workspace Folder...',
          accelerator: 'CmdOrCtrl+O',
          click: async () => {
            const res = await dialog.showOpenDialog(mainWindow, {
              properties: ['openDirectory'],
            });
            if (!res.canceled && res.filePaths[0]) {
              mainWindow?.webContents.send('workspace-selected', res.filePaths[0]);
            }
          },
        },
        { type: 'separator' },
        isMac ? { role: 'close' } : { role: 'quit' },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' },
      ],
    },
    {
      label: 'MCP & Tools',
      submenu: [
        {
          label: 'Open MCP Servers Config',
          accelerator: 'CmdOrCtrl+Shift+M',
          click: () => mainWindow?.webContents.send('navigate-tab', 'mcp'),
        },
        {
          label: 'Trigger Dream Memory Sync',
          accelerator: 'CmdOrCtrl+Shift+D',
          click: () => mainWindow?.webContents.send('trigger-dream-sync'),
        },
        {
          label: 'Reload Active MCP Tool Registry',
          accelerator: 'CmdOrCtrl+Shift+R',
          click: () => mainWindow?.webContents.send('reload-mcp'),
        },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        ...(isMac
          ? [{ type: 'separator' }, { role: 'front' }, { type: 'separator' }, { role: 'window' }]
          : [{ role: 'close' }]),
      ],
    },
    {
      role: 'help',
      submenu: [
        {
          label: 'Nanobot Documentation',
          click: () => shell.openExternal('https://github.com/nanobot-ai/nanobot'),
        },
        {
          label: 'Model Context Protocol (MCP) Spec',
          click: () => shell.openExternal('https://modelcontextprotocol.io'),
        },
      ],
    },
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

// Global Application Lifecycle
app.whenReady().then(() => {
  createMainWindow();
  createQuickSummonWindow();
  createTray();

  // Register Global Spotlight Shortcut (Alt+Space or Option+Space)
  const ret = globalShortcut.register('Alt+Space', () => {
    toggleQuickSummon();
  });

  if (!ret) {
    console.warn('Global shortcut Alt+Space registration failed, fallback to Cmd+Shift+K');
    globalShortcut.register('CommandOrControl+Shift+K', toggleQuickSummon);
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    } else if (mainWindow) {
      mainWindow.show();
    }
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// IPC Communications
ipcMain.handle('desktop:get-info', () => {
  return {
    isElectron: true,
    platform: process.platform,
    version: app.getVersion(),
    arch: process.arch,
    homeDir: app.getPath('home'),
    appDataDir: app.getPath('userData'),
    isPackaged: app.isPackaged,
  };
});

ipcMain.handle('desktop:select-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled) return null;
  return result.filePaths[0];
});

ipcMain.handle('desktop:open-external', async (event, url) => {
  await shell.openExternal(url);
  return true;
});

ipcMain.handle('desktop:toggle-spotlight', () => {
  toggleQuickSummon();
  return true;
});

ipcMain.handle('desktop:notify', (event, { title, body }) => {
  const { Notification } = require('electron');
  if (Notification.isSupported()) {
    new Notification({ title: title || 'Nanobot', body }).show();
    return true;
  }
  return false;
});
