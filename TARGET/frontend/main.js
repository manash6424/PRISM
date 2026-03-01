const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const isDev = process.env.NODE_ENV === 'development';

let mainWindow;

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        minWidth: 1200,
        minHeight: 700,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js')
        },
        titleBarStyle: 'hiddenInset',
        backgroundColor: '#1a1a2e',
        show: false
    });

    // Load the app
    const startUrl = isDev 
        ? 'http://localhost:3000' 
        : `file://${path.join(__dirname, 'renderer/index.html')}`;
    
    mainWindow.loadURL(startUrl);

    // Show window when ready
    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
    }
});

// API communication
const API_BASE = 'http://localhost:8000/api/v1';

// Store for connections
let connections = [];

ipcMain.handle('api-request', async (event, options) => {
    const { method, endpoint, data } = options;
    const url = `${API_BASE}${endpoint}`;
    
    const config = {
        method,
        headers: {
            'Content-Type': 'application/json',
        }
    };
    
    if (data && (method === 'POST' || method === 'PUT')) {
        config.body = JSON.stringify(data);
    }
    
    try {
        const response = await fetch(url, config);
        return await response.json();
    } catch (error) {
        return { error: error.message };
    }
});

ipcMain.handle('get-connections', async () => {
    return connections;
});

ipcMain.handle('save-connection', async (event, connection) => {
    const result = await fetch(`${API_BASE}/connections`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(connection)
    });
    const saved = await result.json();
    connections.push(saved);
    return saved;
});
