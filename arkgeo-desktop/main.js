const { app, BrowserWindow, ipcMain, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const net = require('net');
const http = require('http');
const fs = require('fs');

const isDev = !app.isPackaged;
const BACKEND_STARTUP_TIMEOUT = 90000;

let mainWindow = null;
let backendProcess = null;
let backendPort = null;

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
    server.on('error', reject);
  });
}

function waitForBackend(port, timeout = BACKEND_STARTUP_TIMEOUT) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    // Give the backend 10 seconds to initialize before first health check.
    // The unified registry + CAI tools import takes ~10-15s on first boot.
    const INITIAL_DELAY = 10000;
    console.log(`[ARK] Waiting ${INITIAL_DELAY/1000}s for backend initialization...`);
    setTimeout(() => {
      const check = () => {
        const elapsed = Math.round((Date.now() - start) / 1000);
        const req = http.get(`http://127.0.0.1:${port}/api/v1/health`, (res) => {
          if (res.statusCode === 200) {
            console.log(`[ARK] Backend healthy at ${elapsed}s`);
            resolve(true);
          } else {
            retry();
          }
        });
        req.on('error', (err) => {
          console.log(`[ARK] Health check at ${elapsed}s: ${err.message}`);
          retry();
        });
        req.setTimeout(5000, () => {
          req.destroy();
          retry();
        });
      };
      const retry = () => {
        if (Date.now() - start > timeout) {
          reject(new Error('Backend startup timed out'));
        } else {
          setTimeout(check, 2000);
        }
      };
      check();
    }, INITIAL_DELAY);
  });
}

function getBackendPaths() {
  let backendDir, venvPython, resourcesPath, bundledBinary;

  if (isDev) {
    backendDir = path.join(__dirname, '..', 'arkgeo-backend');
    venvPython = path.join(backendDir, '.venv', 'bin', 'python');
    resourcesPath = path.join(__dirname, 'backend');
  } else {
    resourcesPath = path.join(process.resourcesPath);
    backendDir = path.join(resourcesPath, 'arkgeo-backend');
    venvPython = path.join(backendDir, '.venv', 'bin', 'python');
  }

  bundledBinary = process.platform === 'win32'
    ? path.join(resourcesPath, 'arkgeo-server.exe')
    : path.join(resourcesPath, 'arkgeo-server');

  return { bundledBinary, venvPython, backendDir, resourcesPath };
}

function startBackend(port) {
  return new Promise((resolve, reject) => {
    const { bundledBinary, venvPython, backendDir } = getBackendPaths();

    if (fs.existsSync(bundledBinary)) {
      console.log('[ARK] Starting bundled backend...');
      backendProcess = spawn(bundledBinary, [], {
        cwd: backendDir,
        env: {
          ...process.env,
          ARKGEO_HOST: '127.0.0.1',
          ARKGEO_PORT: String(port),
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } else if (fs.existsSync(venvPython)) {
      console.log('[ARK] Bundled backend not found, using system Python...');
      backendProcess = spawn(venvPython, [
        '-m', 'uvicorn', 'main:app',
        '--host', '127.0.0.1',
        '--port', String(port),
      ], {
        cwd: backendDir,
        env: {
          ...process.env,
          ARKGEO_HOST: '127.0.0.1',
          ARKGEO_PORT: String(port),
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } else {
      reject(new Error(
        'No Python environment found. Install Python 3.12+ and run:\n' +
        '  cd arkgeo-backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt'
      ));
      return;
    }

    backendProcess.stdout?.on('data', (data) => {
      console.log(`[ARK Backend] ${data.toString().trim()}`);
    });
    backendProcess.stderr?.on('data', (data) => {
      console.error(`[ARK Backend] ${data.toString().trim()}`);
    });
    backendProcess.on('error', (err) => {
      console.error('[ARK] Backend process error:', err);
      reject(err);
    });
    backendProcess.on('exit', (code, signal) => {
      console.log(`[ARK] Backend exited with code ${code}, signal ${signal}`);
      backendProcess = null;
    });

    console.log('[ARK] Waiting for backend health check...');
    waitForBackend(port).then(() => {
      console.log('[ARK] Backend is healthy.');
      resolve();
    }).catch((err) => {
      console.error('[ARK] Backend health check failed:', err.message);
      reject(err);
    });
  });
}

function stopBackend() {
  if (backendProcess) {
    console.log('[ARK] Stopping backend...');
    backendProcess.kill('SIGTERM');
    setTimeout(() => {
      if (backendProcess) {
        backendProcess.kill('SIGKILL');
      }
    }, 3000);
    backendProcess = null;
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: 'THE ARK — Integrated Security Environment',
    backgroundColor: '#0B0F17',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 16 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
    },
    show: false,
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  let frontendPath;
  if (isDev) {
    frontendPath = path.join(__dirname, '..', 'arkgeo-investigator-web', 'dist', 'index.html');
  } else {
    frontendPath = path.join(process.resourcesPath, 'app', 'index.html');
  }

  console.log(`[ARK] Loading frontend from: ${frontendPath}`);
  mainWindow.loadFile(frontendPath);

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

ipcMain.handle('ark:get-status', () => ({
  backendPort,
  backendRunning: backendProcess !== null,
  isDev,
}));

ipcMain.handle('ark:get-backend-port', () => backendPort);

// Synchronous handler — preload calls this via sendSync before renderer JS runs.
// The backend is already started by this point, so backendPort is set.
ipcMain.on('ark:get-backend-port-sync', (event) => {
  event.returnValue = backendPort;
});

app.whenReady().then(async () => {
  try {
    backendPort = await findFreePort();
    console.log(`[ARK] Starting backend on port ${backendPort}...`);
    console.log(`[ARK] isDev=${isDev}`);
    console.log(`[ARK] __dirname=${__dirname}`);

    const paths = getBackendPaths();
    console.log(`[ARK] bundledBinary=${paths.bundledBinary} exists=${fs.existsSync(paths.bundledBinary)}`);
    console.log(`[ARK] venvPython=${paths.venvPython} exists=${fs.existsSync(paths.venvPython)}`);
    console.log(`[ARK] backendDir=${paths.backendDir} exists=${fs.existsSync(paths.backendDir)}`);

    await startBackend(backendPort);

    createWindow();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    });
  } catch (err) {
    console.error('[ARK] Failed to start:', err);
    app.quit();
  }
});

app.on('window-all-closed', () => {
  stopBackend();
  app.quit();
});

app.on('before-quit', () => {
  stopBackend();
});
