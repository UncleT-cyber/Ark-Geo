const { contextBridge, ipcRenderer } = require('electron');

// Synchronous port resolution — MUST complete before renderer JS executes.
// The backend is already started and healthy by the time createWindow() loads
// the frontend, so sendSync returns immediately with the cached port.
let cachedPort = null;
try {
  cachedPort = ipcRenderer.sendSync('ark:get-backend-port-sync');
} catch {
  // Fallback: fire-and-forget async if sync fails (shouldn't happen)
  ipcRenderer.invoke('ark:get-backend-port').then((port) => {
    cachedPort = port;
  }).catch(() => {});
}

contextBridge.exposeInMainWorld('ark', {
  getStatus: () => ipcRenderer.invoke('ark:get-status'),
  getBackendPort: () => Promise.resolve(cachedPort ?? ipcRenderer.invoke('ark:get-backend-port')),
  isElectron: true,
  get backendPort() {
    return cachedPort;
  },
});
