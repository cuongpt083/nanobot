const { app, BrowserWindow, ipcMain, globalShortcut, Tray, Menu, nativeImage, dialog, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const { spawn } = require('child_process');

let mainWindow = null;
let quickSummonWindow = null;
let tray = null;
let isQuitting = false;

// ==========================================
// Gateway Process Supervisor
// ==========================================
class GatewaySupervisor {
  constructor() {
    this.child = null;
    this.logs = [];
    this.maxLogs = 500;
    this.startTime = null;
    this.status = 'stopped'; // 'running' | 'stopped' | 'starting' | 'stopping' | 'error'
    this.lastError = null;
    this.healthCheckTimer = null;
    this.healthStatus = 'unknown'; // 'healthy' | 'unhealthy' | 'checking' | 'unknown'
    this.healthLatencyMs = 0;
    this.configPath = path.join(app.getPath('userData'), 'gateway-config.json');
    this.config = this.loadConfig();
  }

  getDefaultConfig() {
    return {
      mode: 'node_embedded', // 'node_embedded' | 'python_cli' | 'custom'
      host: '127.0.0.1',
      port: 3000,
      autoStartOnLaunch: true,
      autoRestartOnCrash: true,
      workingDirectory: path.join(__dirname, '..'),
      pythonPath: 'python3',
      customCommand: '',
      customArgs: [],
      logLevel: 'info',
      envVars: {},
      maxLogLines: 500,
    };
  }

  loadConfig() {
    try {
      if (fs.existsSync(this.configPath)) {
        const raw = fs.readFileSync(this.configPath, 'utf8');
        return { ...this.getDefaultConfig(), ...JSON.parse(raw) };
      }
    } catch (e) {
      console.warn('[Supervisor] Failed to read stored gateway config:', e.message);
    }
    return this.getDefaultConfig();
  }

  saveConfig(newConfig) {
    this.config = { ...this.config, ...newConfig };
    try {
      fs.mkdirSync(path.dirname(this.configPath), { recursive: true });
      fs.writeFileSync(this.configPath, JSON.stringify(this.config, null, 2), 'utf8');
      this.addLog('system', `Gateway configuration saved successfully.`);
      return { success: true, config: this.config };
    } catch (e) {
      this.addLog('stderr', `Failed to save gateway config: ${e.message}`);
      return { success: false, error: e.message };
    }
  }

  addLog(type, message, level = 'info') {
    const entry = {
      id: `log-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`,
      timestamp: Date.now(),
      type,
      message: String(message).trimEnd(),
      level,
    };
    this.logs.push(entry);
    if (this.logs.length > this.maxLogs) {
      this.logs.shift();
    }

    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('desktop:gateway-log', entry);
    }
    return entry;
  }

  clearLogs() {
    this.logs = [];
    this.addLog('system', 'Gateway terminal logs cleared.');
    return true;
  }

  getLogs() {
    return this.logs;
  }

  getState() {
    const uptime = this.startTime && this.status === 'running' ? Math.floor((Date.now() - this.startTime) / 1000) : 0;
    return {
      status: this.status,
      pid: this.child ? this.child.pid : undefined,
      host: this.config.host,
      port: this.config.port,
      mode: this.config.mode,
      uptimeSeconds: uptime,
      memoryUsageMb: this.child ? Math.round(process.memoryUsage().rss / (1024 * 1024)) : 0,
      cpuPercent: this.status === 'running' ? 0.8 : 0,
      startedAt: this.startTime || undefined,
      lastError: this.lastError || undefined,
      url: `http://${this.config.host}:${this.config.port}`,
      healthStatus: this.healthStatus,
      healthLatencyMs: this.healthLatencyMs,
    };
  }

  notifyStateChange() {
    const state = this.getState();
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('desktop:gateway-status-changed', state);
    }
    updateTrayMenu();
  }

  async checkHealth(timeoutMs = 1500) {
    const start = Date.now();
    return new Promise((resolve) => {
      const req = http.get(
        `http://${this.config.host}:${this.config.port}/api/health`,
        { timeout: timeoutMs },
        (res) => {
          this.healthLatencyMs = Date.now() - start;
          if (res.statusCode === 200) {
            this.healthStatus = 'healthy';
            resolve({ ok: true, latencyMs: this.healthLatencyMs, statusCode: res.statusCode });
          } else {
            this.healthStatus = 'unhealthy';
            resolve({ ok: false, latencyMs: this.healthLatencyMs, statusCode: res.statusCode });
          }
        }
      );

      req.on('error', (err) => {
        this.healthLatencyMs = Date.now() - start;
        this.healthStatus = 'unhealthy';
        resolve({ ok: false, error: err.message });
      });

      req.on('timeout', () => {
        req.destroy();
        this.healthLatencyMs = Date.now() - start;
        this.healthStatus = 'unhealthy';
        resolve({ ok: false, error: 'Timeout' });
      });
    });
  }

  async start() {
    if (this.status === 'running' || this.status === 'starting') {
      return { success: true, message: 'Gateway is already running or starting', state: this.getState() };
    }

    this.status = 'starting';
    this.lastError = null;
    this.notifyStateChange();
    this.addLog('system', `Starting Nanobot Gateway in mode [${this.config.mode}] on port ${this.config.port}...`);

    // First check if an existing instance is already responding on the port
    const initialPing = await this.checkHealth(1000);
    if (initialPing.ok) {
      this.status = 'running';
      this.startTime = Date.now();
      this.addLog('system', `Detected active Gateway server responding at http://${this.config.host}:${this.config.port} (Latency: ${initialPing.latencyMs}ms). Connected directly.`);
      this.notifyStateChange();
      this.startHealthPolling();
      return { success: true, message: 'Connected to existing Gateway instance', state: this.getState() };
    }

    try {
      const workingDir = this.config.workingDirectory || path.join(__dirname, '..');
      const env = {
        ...process.env,
        PORT: String(this.config.port),
        HOST: this.config.host,
        NODE_ENV: app.isPackaged ? 'production' : 'development',
        ...this.config.envVars,
      };

      let cmd = '';
      let args = [];

      if (this.config.mode === 'node_embedded') {
        const serverBundle = path.join(workingDir, 'dist', 'server.cjs');
        const serverTs = path.join(workingDir, 'server.ts');

        if (fs.existsSync(serverBundle)) {
          cmd = 'node';
          args = [serverBundle];
        } else if (fs.existsSync(serverTs)) {
          cmd = 'npx';
          args = ['tsx', serverTs];
        } else {
          cmd = 'npm';
          args = ['run', 'dev'];
        }
      } else if (this.config.mode === 'python_cli') {
        cmd = this.config.pythonPath || 'python3';
        args = ['-m', 'nanobot', 'gateway', '--port', String(this.config.port), '--host', this.config.host];
      } else if (this.config.mode === 'custom') {
        cmd = this.config.customCommand || 'npm';
        args = this.config.customArgs || ['run', 'dev'];
      }

      this.addLog('system', `Spawning process: ${cmd} ${args.join(' ')} (CWD: ${workingDir})`);

      this.child = spawn(cmd, args, {
        cwd: workingDir,
        env,
        shell: process.platform === 'win32',
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      this.startTime = Date.now();

      this.child.stdout.on('data', (data) => {
        const text = data.toString();
        this.addLog('stdout', text);
      });

      this.child.stderr.on('data', (data) => {
        const text = data.toString();
        this.addLog('stderr', text, 'warn');
      });

      this.child.on('error', (err) => {
        this.status = 'error';
        this.lastError = err.message;
        this.addLog('stderr', `Process execution error: ${err.message}`, 'error');
        this.notifyStateChange();
      });

      this.child.on('close', (code, signal) => {
        this.addLog('system', `Gateway process exited with code ${code}, signal ${signal}`, code === 0 ? 'info' : 'warn');
        const wasRunning = this.status === 'running';
        this.child = null;
        this.status = 'stopped';
        this.stopHealthPolling();
        this.notifyStateChange();

        if (wasRunning && this.config.autoRestartOnCrash && !isQuitting) {
          this.addLog('system', 'Auto-restart on crash is enabled. Restarting Gateway in 2 seconds...', 'warn');
          setTimeout(() => {
            if (!isQuitting) this.start();
          }, 2000);
        }
      });

      // Poll until server becomes healthy (up to 15 seconds)
      let attempts = 0;
      const maxAttempts = 30;
      const pollInterval = setInterval(async () => {
        attempts++;
        const check = await this.checkHealth(800);
        if (check.ok) {
          clearInterval(pollInterval);
          this.status = 'running';
          this.addLog('system', `Gateway ready and responding at http://${this.config.host}:${this.config.port} (${check.latencyMs}ms)!`);
          this.notifyStateChange();
          this.startHealthPolling();
        } else if (attempts >= maxAttempts) {
          clearInterval(pollInterval);
          if (this.status === 'starting') {
            this.status = 'running'; // Keep running as fallback since child is alive
            this.addLog('system', `Gateway started (PID: ${this.child?.pid}). Health check taking longer than expected.`, 'warn');
            this.notifyStateChange();
            this.startHealthPolling();
          }
        }
      }, 500);

      return { success: true, message: 'Gateway process started successfully', state: this.getState() };
    } catch (err) {
      this.status = 'error';
      this.lastError = err.message;
      this.addLog('stderr', `Failed to launch gateway: ${err.message}`, 'error');
      this.notifyStateChange();
      return { success: false, error: err.message, state: this.getState() };
    }
  }

  async stop() {
    if (!this.child && this.status === 'stopped') {
      return { success: true, message: 'Gateway is already stopped', state: this.getState() };
    }

    this.status = 'stopping';
    this.notifyStateChange();
    this.addLog('system', 'Stopping Gateway process...');
    this.stopHealthPolling();

    if (this.child) {
      try {
        if (process.platform === 'win32') {
          spawn('taskkill', ['/pid', String(this.child.pid), '/f', '/t']);
        } else {
          this.child.kill('SIGTERM');
        }
      } catch (e) {
        console.warn('Error killing child process:', e);
      }
      this.child = null;
    }

    this.status = 'stopped';
    this.healthStatus = 'unknown';
    this.startTime = null;
    this.addLog('system', 'Gateway process stopped.');
    this.notifyStateChange();
    return { success: true, message: 'Gateway stopped', state: this.getState() };
  }

  async restart(newConfig = null) {
    if (newConfig) {
      this.saveConfig(newConfig);
    }
    await this.stop();
    await new Promise((resolve) => setTimeout(resolve, 1000));
    return await this.start();
  }

  startHealthPolling() {
    this.stopHealthPolling();
    this.healthCheckTimer = setInterval(async () => {
      if (this.status === 'running') {
        await this.checkHealth();
        this.notifyStateChange();
      }
    }, 5000);
  }

  stopHealthPolling() {
    if (this.healthCheckTimer) {
      clearInterval(this.healthCheckTimer);
      this.healthCheckTimer = null;
    }
  }
}

const supervisor = new GatewaySupervisor();

// ==========================================
// Window Creation & LifeCycle
// ==========================================
function getAppServerUrl() {
  const cfg = supervisor.config;
  return `http://${cfg.host}:${cfg.port}`;
}

async function createMainWindow() {
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

  const targetUrl = getAppServerUrl();
  mainWindow.loadURL(targetUrl).catch((err) => {
    console.warn('[Electron] Initial loadURL caught error (waiting for server):', err.message);
  });

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

  quickSummonWindow.loadURL(`${getAppServerUrl()}?mode=spotlight`).catch(() => {});

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
  const iconPath = path.join(__dirname, '../public/icon.png');
  let icon = null;
  if (fs.existsSync(iconPath)) {
    icon = nativeImage.createFromPath(iconPath).resize({ width: 18, height: 18 });
  } else {
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  tray.setToolTip('Nanobot Desktop AI Agent & Gateway');
  updateTrayMenu();

  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

function updateTrayMenu() {
  if (!tray) return;
  const state = supervisor.getState();
  const isRunning = state.status === 'running';

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
      label: `Gateway Status: ${state.status.toUpperCase()} (: ${state.port})`,
      enabled: false,
    },
    {
      label: isRunning ? 'Restart Gateway Server' : 'Start Gateway Server',
      click: async () => {
        if (isRunning) {
          await supervisor.restart();
        } else {
          await supervisor.start();
        }
      },
    },
    {
      label: 'Stop Gateway Server',
      enabled: isRunning,
      click: async () => {
        await supervisor.stop();
      },
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
      label: 'Gateway & Server',
      submenu: [
        {
          label: 'Open Gateway Server Manager',
          accelerator: 'CmdOrCtrl+Shift+G',
          click: () => mainWindow?.webContents.send('navigate-tab', 'gateway-manager'),
        },
        {
          label: 'Start Gateway Server',
          click: () => supervisor.start(),
        },
        {
          label: 'Restart Gateway Server',
          click: () => supervisor.restart(),
        },
        {
          label: 'Stop Gateway Server',
          click: () => supervisor.stop(),
        },
        { type: 'separator' },
        {
          label: 'Clear Terminal Logs',
          click: () => supervisor.clearLogs(),
        },
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

// ==========================================
// Global Lifecycle & Startup Orchestration
// ==========================================
app.whenReady().then(async () => {
  // If autoStart is enabled, initialize supervisor before showing window
  if (supervisor.config.autoStartOnLaunch) {
    await supervisor.start();
  }

  await createMainWindow();
  createQuickSummonWindow();
  createTray();

  // Register Global Spotlight Shortcut (Alt+Space or Cmd+Shift+K)
  const ret = globalShortcut.register('Alt+Space', () => {
    toggleQuickSummon();
  });

  if (!ret) {
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

app.on('before-quit', async () => {
  isQuitting = true;
  await supervisor.stop();
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// ==========================================
// IPC Handlers: Desktop System & Gateway
// ==========================================
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

// Gateway Supervisor IPCs
ipcMain.handle('desktop:gateway-get-status', () => {
  return supervisor.getState();
});

ipcMain.handle('desktop:gateway-get-config', () => {
  return supervisor.config;
});

ipcMain.handle('desktop:gateway-save-config', (event, newConfig) => {
  return supervisor.saveConfig(newConfig);
});

ipcMain.handle('desktop:gateway-start', async () => {
  return await supervisor.start();
});

ipcMain.handle('desktop:gateway-stop', async () => {
  return await supervisor.stop();
});

ipcMain.handle('desktop:gateway-restart', async (event, newConfig) => {
  return await supervisor.restart(newConfig);
});

ipcMain.handle('desktop:gateway-get-logs', () => {
  return supervisor.getLogs();
});

ipcMain.handle('desktop:gateway-clear-logs', () => {
  return supervisor.clearLogs();
});

ipcMain.handle('desktop:gateway-ping', async () => {
  return await supervisor.checkHealth();
});
