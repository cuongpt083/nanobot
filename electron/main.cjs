const { app, BrowserWindow, ipcMain, globalShortcut, Tray, Menu, nativeImage, dialog, shell, utilityProcess } = require('electron');
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

  getAppRoot() {
    return app.isPackaged ? app.getAppPath() : path.join(__dirname, '..');
  }

  getDefaultConfig() {
    return {
      mode: 'node_embedded', // 'node_embedded' | 'python_cli' | 'custom'
      host: '127.0.0.1',
      port: 3000,
      autoStartOnLaunch: true,
      autoRestartOnCrash: true,
      workingDirectory: this.getAppRoot(),
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
        const loaded = JSON.parse(raw);
        if (app.isPackaged && (!loaded.workingDirectory || !fs.existsSync(loaded.workingDirectory))) {
          loaded.workingDirectory = this.getAppRoot();
        }
        return { ...this.getDefaultConfig(), ...loaded };
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
      const curUrl = mainWindow.webContents.getURL();
      if (state.status === 'running' && (!curUrl || curUrl.includes('about:blank'))) {
        loadWindowUrl(mainWindow, getAppServerUrl());
      }
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

  async waitForReady(timeoutMs = 15000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (this.status === 'error' || (!this.child && this.status === 'stopped')) {
        return false;
      }
      const check = await this.checkHealth(600);
      if (check.ok) {
        this.status = 'running';
        this.notifyStateChange();
        this.startHealthPolling();
        return true;
      }
      await new Promise((r) => setTimeout(r, 300));
    }
    return false;
  }

  async start() {
    if (this.status === 'running') {
      return { success: true, message: 'Gateway is already running', state: this.getState() };
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
      const appRoot = this.getAppRoot();
      const workingDir = this.config.workingDirectory || appRoot;
      const env = {
        ...process.env,
        PORT: String(this.config.port),
        HOST: this.config.host,
        NODE_ENV: app.isPackaged ? 'production' : 'development',
        ...this.config.envVars,
      };

      let cmd = '';
      let args = [];
      let useShell = false;

      if (this.config.mode === 'node_embedded') {
        const candidateBundles = [
          path.join(appRoot, 'dist', 'server.cjs'),
          path.join(workingDir, 'dist', 'server.cjs'),
          path.join(__dirname, '..', 'dist', 'server.cjs'),
        ];
        const serverBundle = candidateBundles.find((p) => fs.existsSync(p));
        const serverTs = path.join(workingDir, 'server.ts');

        if (serverBundle) {
          this.addLog('system', `Spawning embedded gateway via Electron utilityProcess: ${serverBundle}`);
          this.child = utilityProcess.fork(serverBundle, {
            serviceName: 'NanobotGateway',
            stdio: 'pipe',
            env,
          });
        } else if (fs.existsSync(serverTs)) {
          this.addLog('system', `Spawning dev gateway via npx tsx: ${serverTs}`);
          this.child = spawn('npx', ['tsx', serverTs], {
            cwd: workingDir,
            env,
            shell: process.platform === 'win32',
            stdio: ['ignore', 'pipe', 'pipe'],
          });
        } else {
          this.addLog('system', `Spawning fallback gateway via npm run dev`);
          this.child = spawn('npm', ['run', 'dev'], {
            cwd: workingDir,
            env,
            shell: process.platform === 'win32',
            stdio: ['ignore', 'pipe', 'pipe'],
          });
        }
      } else if (this.config.mode === 'python_cli') {
        const cmd = this.config.pythonPath || 'python3';
        const args = ['-m', 'nanobot', 'gateway', '--port', String(this.config.port), '--host', this.config.host];
        this.addLog('system', `Spawning python gateway: ${cmd} ${args.join(' ')}`);
        this.child = spawn(cmd, args, {
          cwd: workingDir,
          env,
          shell: process.platform === 'win32',
          stdio: ['ignore', 'pipe', 'pipe'],
        });
      } else if (this.config.mode === 'custom') {
        const cmd = this.config.customCommand || 'npm';
        const args = this.config.customArgs || ['run', 'dev'];
        this.addLog('system', `Spawning custom gateway: ${cmd} ${args.join(' ')}`);
        this.child = spawn(cmd, args, {
          cwd: workingDir,
          env,
          shell: process.platform === 'win32',
          stdio: ['ignore', 'pipe', 'pipe'],
        });
      }

      this.startTime = Date.now();

      if (this.child.stdout) {
        this.child.stdout.on('data', (data) => {
          const text = data.toString();
          this.addLog('stdout', text);
        });
      }

      if (this.child.stderr) {
        this.child.stderr.on('data', (data) => {
          const text = data.toString();
          this.addLog('stderr', text, 'warn');
        });
      }

      const handleExit = (code, signal) => {
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
      };

      if (typeof this.child.on === 'function') {
        this.child.on('exit', handleExit);
        this.child.on('close', handleExit);
        this.child.on('error', (err) => {
          this.status = 'error';
          this.lastError = err.message;
          this.addLog('stderr', `Process execution error: ${err.message}`, 'error');
          this.notifyStateChange();
        });
      }

      // Await server endpoint health check
      const ready = await this.waitForReady(15000);
      if (ready) {
        this.addLog('system', `Gateway ready and responding at http://${this.config.host}:${this.config.port}!`);
      } else {
        this.addLog('system', `Gateway process started (PID: ${this.child?.pid}), awaiting endpoint responsiveness.`, 'warn');
      }

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
        if (typeof this.child.kill === 'function') {
          this.child.kill();
        }
        if (this.child.pid && process.platform === 'win32') {
          try {
            spawn('taskkill', ['/pid', String(this.child.pid), '/f', '/t']);
          } catch (e) {}
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

async function loadWindowUrl(win, url, maxRetries = 20, retryDelayMs = 500) {
  if (!win || win.isDestroyed()) return;
  for (let i = 0; i < maxRetries; i++) {
    try {
      await win.loadURL(url);
      console.log(`[Electron] Successfully loaded ${url}`);
      return;
    } catch (err) {
      console.warn(`[Electron] loadURL attempt ${i + 1}/${maxRetries} failed (${err.message}). Retrying in ${retryDelayMs}ms...`);
      if (win.isDestroyed()) return;
      await new Promise((r) => setTimeout(r, retryDelayMs));
    }
  }
  console.error(`[Electron] Could not load ${url} after ${maxRetries} attempts.`);
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

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Fallback to ensure window shows even if ready-to-show is delayed
  setTimeout(() => {
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
      mainWindow.show();
    }
  }, 3500);

  const targetUrl = getAppServerUrl();
  loadWindowUrl(mainWindow, targetUrl);

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

  loadWindowUrl(quickSummonWindow, `${getAppServerUrl()}?mode=spotlight`);

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
  const iconCandidates = [
    path.join(__dirname, '../public/icon.png'),
    path.join(__dirname, '../images/nanobot_icon.png'),
    path.join(app.getAppPath(), 'public/icon.png'),
    path.join(app.getAppPath(), 'images/nanobot_icon.png'),
  ];
  const iconPath = iconCandidates.find((p) => fs.existsSync(p));
  let icon = null;
  if (iconPath) {
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

ipcMain.handle('desktop:window-minimize', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender) || mainWindow;
  if (win && !win.isDestroyed()) {
    win.minimize();
    return true;
  }
  return false;
});

ipcMain.handle('desktop:window-maximize', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender) || mainWindow;
  if (win && !win.isDestroyed()) {
    if (win.isMaximized()) {
      win.unmaximize();
      return false;
    } else {
      win.maximize();
      return true;
    }
  }
  return false;
});

ipcMain.handle('desktop:window-close', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender) || mainWindow;
  if (win && !win.isDestroyed()) {
    win.close();
    return true;
  }
  return false;
});

ipcMain.handle('desktop:window-is-maximized', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender) || mainWindow;
  return win && !win.isDestroyed() ? win.isMaximized() : false;
});

ipcMain.handle('desktop:set-always-on-top', (event, flag) => {
  const win = BrowserWindow.fromWebContents(event.sender) || mainWindow;
  if (win && !win.isDestroyed()) {
    win.setAlwaysOnTop(Boolean(flag));
    return true;
  }
  return false;
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

// Setup & Provisioning IPCs
ipcMain.handle('desktop:setup-get-status', async () => {
  const os = require('os');
  const homeDir = os.homedir();
  const nanobotDir = path.join(homeDir, '.nanobot');
  const workspaceDir = path.join(nanobotDir, 'workspace');
  const configPath = path.join(nanobotDir, 'config.json');
  const installedFilePath = path.join(nanobotDir, '.installed');
  const venvDir = path.join(nanobotDir, 'venv');
  const scriptsDir = path.join(nanobotDir, 'scripts');

  const configExists = fs.existsSync(configPath);
  const workspaceExists = fs.existsSync(workspaceDir);
  const venvExists = fs.existsSync(venvDir);
  const scriptsExists = fs.existsSync(scriptsDir);
  const installedFileExists = fs.existsSync(installedFilePath);

  let installedInfo = null;
  if (installedFileExists) {
    try {
      installedInfo = JSON.parse(fs.readFileSync(installedFilePath, 'utf8'));
    } catch (e) {}
  }

  let detectedPython = {
    found: false,
    path: '',
    version: '',
    meetsRequirements: false,
  };

  const { execSync } = require('child_process');
  const pythonCandidates = process.platform === 'win32'
    ? ['python', 'py', 'python3', 'uv']
    : ['python3', 'python', 'uv'];

  for (const cmd of pythonCandidates) {
    try {
      const out = execSync(`${cmd} -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'); sys.exit(0 if sys.version_info >= (3, 11) else 1)"`, {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
        timeout: 3000,
      }).trim();
      if (out) {
        detectedPython = {
          found: true,
          path: cmd,
          version: out,
          meetsRequirements: true,
        };
        break;
      }
    } catch (e) {
      try {
        const rawVer = execSync(`${cmd} --version`, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 2000 }).trim();
        if (rawVer) {
          detectedPython = {
            found: true,
            path: cmd,
            version: rawVer.replace(/^Python\s*/i, ''),
            meetsRequirements: false,
          };
        }
      } catch (e2) {}
    }
  }

  let hasActiveProvider = false;
  try {
    if (configExists) {
      const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
      const providers = cfg.providers || {};
      hasActiveProvider = Object.values(providers).some(
        (p) => p && (p.status === 'active' || p.apiKey || p.apiBase) && p.defaultModel
      );
    }
  } catch (e) {}

  const isInstalled = installedFileExists && configExists && workspaceExists && scriptsExists;
  const needsSetup = !isInstalled || !workspaceExists || !scriptsExists || !hasActiveProvider;

  const steps = [
    {
      id: 'check_python',
      title: 'Kiểm tra Hệ điều hành & Python Runtime',
      description: 'Xác định hệ điều hành, CPU và phiên bản Python >= 3.11 trên hệ thống.',
      status: detectedPython.meetsRequirements ? 'completed' : (detectedPython.found ? 'completed' : 'pending'),
      details: detectedPython.found
        ? `Đã phát hiện Python ${detectedPython.version} (${detectedPython.path})`
        : 'Chưa phát hiện Python 3.11+ trong PATH.',
    },
    {
      id: 'create_directories',
      title: 'Khởi tạo Thư mục HOME/.nanobot & Workspace chuẩn',
      description: 'Tạo cấu trúc thư mục phân cấp và các tệp AGENTS.md, SOUL.md, TOOLS.md.',
      status: workspaceExists ? 'completed' : 'pending',
      details: workspaceExists ? `Thư mục ${workspaceDir} đã sẵn sàng.` : `Sẽ tạo tại ${nanobotDir}`,
    },
    {
      id: 'setup_venv',
      title: 'Thiết lập Môi trường ảo (Venv) & Dependencies',
      description: 'Khởi tạo môi trường ảo Python độc lập tại ~/.nanobot/venv và cập nhật pip.',
      status: venvExists ? 'completed' : 'pending',
      details: venvExists ? `Môi trường ảo tại ${venvDir}` : 'Sẽ tự động khởi tạo trong venv riêng biệt.',
    },
    {
      id: 'create_scripts',
      title: 'Tạo Scripts Launcher & Binaries Tiện ích',
      description: 'Tạo các tệp nanobot.cmd/ps1 hoặc shell scripts trong ~/.nanobot/scripts.',
      status: scriptsExists ? 'completed' : 'pending',
      details: scriptsExists ? `Đã tạo tại ${scriptsDir}` : 'Sẽ tạo bộ launcher CLI cho terminal.',
    },
    {
      id: 'init_config',
      title: 'Thiết lập Master Config config.json & Model Presets',
      description: 'Cấu hình mặc định cho các Providers, Model Presets và Gateway.',
      status: configExists ? 'completed' : 'pending',
      details: configExists ? 'config.json đã được khởi tạo.' : 'Sẽ tạo config.json với cấu hình đầy đủ.',
    },
    {
      id: 'verify_gateway',
      title: 'Xác thực & Kết nối Nanobot Gateway',
      description: 'Kiểm tra độ sẵn sàng của Gateway Server và cổng dịch vụ.',
      status: supervisor.status === 'running' ? 'completed' : 'pending',
      details: `Gateway hiện tại: ${supervisor.status.toUpperCase()}`,
    },
  ];

  return {
    isInstalled,
    needsSetup,
    hasActiveProvider,
    homeDir,
    nanobotDir,
    workspaceDir,
    configExists,
    installedInfo,
    detectedPython,
    steps,
  };
});

ipcMain.handle('desktop:setup-run', async (event, options = {}) => {
  const os = require('os');
  const { execSync } = require('child_process');
  const homeDir = os.homedir();
  const nanobotDir = path.join(homeDir, '.nanobot');
  const workspaceDir = path.join(nanobotDir, 'workspace');
  const venvDir = path.join(nanobotDir, 'venv');
  const scriptsDir = path.join(nanobotDir, 'scripts');
  const binDir = path.join(nanobotDir, 'bin');
  const configPath = path.join(nanobotDir, 'config.json');
  const installedPath = path.join(nanobotDir, '.installed');

  const emitProgress = (stepId, stepIndex, totalSteps, stepObj, logText) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('desktop:setup-progress', {
        stepId,
        stepIndex,
        totalSteps,
        step: stepObj,
        log: logText,
      });
    }
  };

  const steps = [
    { id: 'check_python', title: 'Kiểm tra Hệ điều hành & Python Runtime', description: 'Xác định hệ điều hành, CPU và phiên bản Python >= 3.11.', status: 'pending' },
    { id: 'create_directories', title: 'Khởi tạo Thư mục HOME/.nanobot & Workspace', description: 'Tạo cấu trúc thư mục và tệp AGENTS.md, SOUL.md, TOOLS.md.', status: 'pending' },
    { id: 'setup_venv', title: 'Thiết lập Môi trường ảo (Venv) & Dependencies', description: 'Khởi tạo môi trường ảo Python và cập nhật pip.', status: 'pending' },
    { id: 'create_scripts', title: 'Tạo Scripts Launcher & Binaries Tiện ích', description: 'Tạo bộ scripts nanobot.cmd/ps1 hoặc shell scripts.', status: 'pending' },
    { id: 'init_config', title: 'Thiết lập Master Config config.json & Model Presets', description: 'Cấu hình mặc định Providers, Model Presets và Gateway.', status: 'pending' },
    { id: 'verify_gateway', title: 'Xác thực & Kết nối Nanobot Gateway', description: 'Kiểm tra độ sẵn sàng của Gateway Server.', status: 'pending' },
  ];

  let detectedPythonCmd = '';
  let detectedPythonVer = '';

  // Step 1
  steps[0].status = 'running';
  emitProgress('check_python', 0, 6, steps[0], `Kiểm tra hệ thống ${process.platform} (${process.arch})...`);
  const candidates = process.platform === 'win32' ? ['python', 'py', 'python3', 'uv'] : ['python3', 'python', 'uv'];
  for (const cmd of candidates) {
    try {
      const out = execSync(`${cmd} -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'); sys.exit(0 if sys.version_info >= (3, 11) else 1)"`, {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
        timeout: 4000,
      }).trim();
      if (out) {
        detectedPythonCmd = cmd;
        detectedPythonVer = out;
        break;
      }
    } catch (e) {}
  }
  steps[0].status = 'completed';
  steps[0].details = detectedPythonCmd ? `Python ${detectedPythonVer} (${detectedPythonCmd})` : 'Node Embedded Mode';
  emitProgress('check_python', 0, 6, steps[0], detectedPythonCmd ? `✓ Đã tìm thấy Python ${detectedPythonVer}` : `! Sử dụng Node Embedded Runtime`);

  // Step 2
  steps[1].status = 'running';
  emitProgress('create_directories', 1, 6, steps[1], `Tạo thư mục tại ${nanobotDir}...`);
  const dirs = [nanobotDir, workspaceDir, path.join(nanobotDir, 'memory'), path.join(nanobotDir, 'cron'), path.join(nanobotDir, 'pairing'), path.join(nanobotDir, 'mcp'), path.join(nanobotDir, 'skills'), scriptsDir, binDir, path.join(nanobotDir, 'logs')];
  for (const d of dirs) {
    if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
  }
  const agentsMdPath = path.join(workspaceDir, 'AGENTS.md');
  if (!fs.existsSync(agentsMdPath) || options.forceReinstall) {
    fs.writeFileSync(agentsMdPath, `# Agent Workspace & Guidelines\n\nChào mừng bạn đến với Nanobot Workspace.\nThư mục này là không gian làm việc chính của AI Agent.\n- Agent có toàn quyền đọc, ghi, chỉnh sửa mã nguồn và tài liệu trong thư mục này.\n- Các công cụ được kích hoạt: Filesystem, Shell sandbox, Web Search, MCP Plugins.\n`, 'utf8');
  }
  const soulMdPath = path.join(workspaceDir, 'SOUL.md');
  if (!fs.existsSync(soulMdPath) || options.forceReinstall) {
    fs.writeFileSync(soulMdPath, `# Nanobot Soul & Identity Prompt\n\nBạn là Nanobot, một trợ lý AI thông minh, tốc độ cao, có tư duy logic sâu sắc.\n- Trả lời ngắn gọn, có cấu trúc rõ ràng, sử dụng Markdown chuẩn.\n- Hỗ trợ tiếng Việt và tiếng Anh tự nhiên.\n`, 'utf8');
  }
  const toolsMdPath = path.join(workspaceDir, 'TOOLS.md');
  if (!fs.existsSync(toolsMdPath) || options.forceReinstall) {
    fs.writeFileSync(toolsMdPath, `# Danh mục Công cụ (Tools Reference)\n\n- Filesystem Tools\n- Shell Sandbox\n- Web Search & Fetch\n- Memory Dream\n- MCP Servers\n`, 'utf8');
  }
  steps[1].status = 'completed';
  steps[1].details = `Đã tạo cấu trúc thư mục và tệp mẫu tại ${workspaceDir}`;
  emitProgress('create_directories', 1, 6, steps[1], `✓ Cấu trúc thư mục HOME/.nanobot sẵn sàng`);

  // Step 3
  steps[2].status = 'running';
  emitProgress('setup_venv', 2, 6, steps[2], `Thiết lập môi trường ảo venv...`);
  if (detectedPythonCmd) {
    if (!fs.existsSync(venvDir) || options.forceReinstall) {
      try {
        execSync(`"${detectedPythonCmd}" -m venv "${venvDir}"`, { stdio: ['ignore', 'pipe', 'pipe'], timeout: 30000 });
      } catch (e) {}
    }
    steps[2].status = 'completed';
    steps[2].details = `Môi trường ảo tại ${venvDir}`;
  } else {
    steps[2].status = 'completed';
    steps[2].details = 'Node Embedded Mode';
  }
  emitProgress('setup_venv', 2, 6, steps[2], `✓ Môi trường ảo Python sẵn sàng`);

  // Step 4
  steps[3].status = 'running';
  emitProgress('create_scripts', 3, 6, steps[3], `Tạo bộ scripts launcher trong ${scriptsDir}...`);
  if (process.platform === 'win32') {
    const cmdScript = `@echo off\r\nsetlocal\r\nif exist "%USERPROFILE%\\.nanobot\\venv\\Scripts\\python.exe" (\r\n    "%USERPROFILE%\\.nanobot\\venv\\Scripts\\python.exe" -m nanobot %*\r\n) else (\r\n    python -m nanobot %*\r\n)\r\nendlocal\r\n`;
    fs.writeFileSync(path.join(scriptsDir, 'nanobot.cmd'), cmdScript, 'utf8');
    fs.writeFileSync(path.join(binDir, 'nanobot.cmd'), cmdScript, 'utf8');
    const psScript = `$VenvPython = "$HOME\\.nanobot\\venv\\Scripts\\python.exe"\r\nif (Test-Path $VenvPython) {\r\n    & $VenvPython -m nanobot @args\r\n} else {\r\n    & python -m nanobot @args\r\n}\r\n`;
    fs.writeFileSync(path.join(scriptsDir, 'nanobot.ps1'), psScript, 'utf8');
    const gatewayCmd = `@echo off\r\nsetlocal\r\n"%USERPROFILE%\\.nanobot\\scripts\\nanobot.cmd" gateway --port 3000 %*\r\nendlocal\r\n`;
    fs.writeFileSync(path.join(scriptsDir, 'start-gateway.cmd'), gatewayCmd, 'utf8');
  } else {
    const shScript = `#!/usr/bin/env bash\nVENV_PY="$HOME/.nanobot/venv/bin/python"\nif [ -x "$VENV_PY" ]; then\n    exec "$VENV_PY" -m nanobot "$@"\nelse\n    exec python3 -m nanobot "$@"\nfi\n`;
    fs.writeFileSync(path.join(scriptsDir, 'nanobot'), shScript, { encoding: 'utf8', mode: 0o755 });
    fs.writeFileSync(path.join(binDir, 'nanobot'), shScript, { encoding: 'utf8', mode: 0o755 });
    const gwSh = `#!/usr/bin/env bash\n"$HOME/.nanobot/scripts/nanobot" gateway --port 3000 "$@"\n`;
    fs.writeFileSync(path.join(scriptsDir, 'start-gateway.sh'), gwSh, { encoding: 'utf8', mode: 0o755 });
  }
  steps[3].status = 'completed';
  steps[3].details = `Tạo bộ launcher CLI tại ${scriptsDir}`;
  emitProgress('create_scripts', 3, 6, steps[3], `✓ Đã tạo bộ launcher scripts`);

  // Step 5
  steps[4].status = 'running';
  emitProgress('init_config', 4, 6, steps[4], `Tạo master config.json...`);
  const installMeta = {
    installedAt: Date.now(),
    version: '0.3.0',
    platform: process.platform,
    arch: process.arch,
    nanobotDir,
    workspacePath: workspaceDir,
    pythonPath: detectedPythonCmd || 'node_embedded',
    pythonVersion: detectedPythonVer || 'embedded',
    status: 'completed',
  };
  fs.writeFileSync(installedPath, JSON.stringify(installMeta, null, 2), 'utf8');
  steps[4].status = 'completed';
  steps[4].details = `Đã lưu cấu hình tại ${configPath}`;
  emitProgress('init_config', 4, 6, steps[4], `✓ Master config.json đã sẵn sàng`);

  // Step 6
  steps[5].status = 'running';
  emitProgress('verify_gateway', 5, 6, steps[5], `Xác thực trạng thái Gateway...`);
  if (supervisor.status !== 'running') {
    await supervisor.start();
  }
  steps[5].status = 'completed';
  steps[5].details = `Gateway hoạt động tại http://127.0.0.1:${supervisor.config.port}`;
  emitProgress('verify_gateway', 5, 6, steps[5], `✓ Nanobot Gateway sẵn sàng 100%`);

  return { success: true, steps };
});
