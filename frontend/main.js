const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
 
let mainWindow;
 
// ── Persistent connections file ──────────────────────────────────────────────
const connectionsFile = path.join(app.getPath('userData'), 'connections.json');
 
function loadConnections() {
    try {
        if (fs.existsSync(connectionsFile)) {
            return JSON.parse(fs.readFileSync(connectionsFile, 'utf8'));
        }
    } catch (e) { console.error('Failed to load connections:', e); }
    return {};
}
 
function saveConnectionsToDisk(data) {
    try {
        fs.writeFileSync(connectionsFile, JSON.stringify(data, null, 2));
    } catch (e) { console.error('Failed to save connections:', e); }
}
 
let connections = loadConnections();
 
// ── Window ───────────────────────────────────────────────────────────────────
function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        minWidth: 1200,
        minHeight: 700,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js'),
            webSecurity: false
        },
        backgroundColor: '#1a1a2e',
        show: false
    });
 
    mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
 
    mainWindow.once('ready-to-show', () => mainWindow.show());
    mainWindow.on('closed', () => { mainWindow = null; });
}
 
app.whenReady().then(createWindow);
 
app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});
 
app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
 
// ── API Base ─────────────────────────────────────────────────────────────────
const API_BASE = 'http://localhost:8000/api/v1';
 
// ── Open File (for exports) ───────────────────────────────────────────────────
ipcMain.handle('open-file', async (event, filepath) => {
    try {
        const absolutePath = path.resolve(filepath);
        const error = await shell.openPath(absolutePath);
        if (error) {
            console.error('Failed to open file:', error);
            return { success: false, error };
        }
        return { success: true };
    } catch (err) {
        return { success: false, error: err.message };
    }
});
 
// ── Generic API request ──────────────────────────────────────────────────────
ipcMain.handle('api-request', async (event, { method, endpoint, data }) => {
    const url = `${API_BASE}${endpoint}`;
    const config = {
        method,
        headers: { 'Content-Type': 'application/json' }
    };
    if (data && ['POST', 'PUT', 'PATCH'].includes(method)) {
        config.body = JSON.stringify(data);
    }
    try {
        const response = await fetch(url, config);
        return await response.json();
    } catch (error) {
        return { error: error.message };
    }
});
 
// ── Auth ─────────────────────────────────────────────────────────────────────
ipcMain.handle('auth-login', async (event, { email, password }) => {
    try {
        const res = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (res.ok) return { success: true, user: data };
        return { success: false, message: data.detail || 'Invalid email or password' };
    } catch (err) {
        return { success: false, message: 'Cannot reach server. Is the backend running?' };
    }
});
 
ipcMain.handle('auth-signup', async (event, { name, company, email, password }) => {
    try {
        const res = await fetch(`${API_BASE}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, company, email, password })
        });
        const data = await res.json();
        if (res.ok) return { success: true };
        return { success: false, message: data.detail || 'Registration failed' };
    } catch (err) {
        return { success: false, message: 'Cannot reach server. Is the backend running?' };
    }
});
 
// ── Connections ───────────────────────────────────────────────────────────────
ipcMain.handle('get-connections', async () => {
    return Object.values(connections);
});
 
ipcMain.handle('save-connection', async (event, connection) => {
    try {
        const res = await fetch(`${API_BASE}/connections`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(connection)
        });
        const saved = await res.json();
        if (saved.id) {
            connections[saved.id] = saved;
            saveConnectionsToDisk(connections);
        }
        return saved;
    } catch (err) {
        return { error: err.message };
    }
});
 
ipcMain.handle('delete-connection', async (event, id) => {
    try {
        await fetch(`${API_BASE}/connections/${id}`, { method: 'DELETE' });
        delete connections[id];
        saveConnectionsToDisk(connections);
        return { success: true };
    } catch (err) {
        return { error: err.message };
    }
});
 
ipcMain.handle('test-connection', async (event, id) => {
    try {
        const res = await fetch(`${API_BASE}/connections/${id}/test`, { method: 'POST' });
        return await res.json();
    } catch (err) {
        return { error: err.message };
    }
});
// ── Save File Dialog ──────────────────────────────────────────────────────────
ipcMain.handle('save-file', async (event, { filename, content }) => {
    try {
        const { filePath } = await dialog.showSaveDialog(mainWindow, {
            title: 'Save Queries',
            defaultPath: path.join(app.getPath('desktop'), filename),
            filters: [{ name: 'JSON Files', extensions: ['json'] }]
        });
        if (!filePath) return { success: false };
        fs.writeFileSync(filePath, content, 'utf8');
        return { success: true, filePath };
    } catch (err) {
        return { success: false, error: err.message };
    }
});