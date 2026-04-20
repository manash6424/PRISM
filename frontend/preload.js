const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {

    // ── Auth ────────────────────────────────────────────────────────────────
    login: (email, password) =>
        ipcRenderer.invoke('auth-login', { email, password }),

    signup: (name, company, email, password) =>
        ipcRenderer.invoke('auth-signup', { name, company, email, password }),

    setToken: (token) =>                          // ✅ NEW
        ipcRenderer.invoke('auth-set-token', token),

    logout: () =>                                  // ✅ NEW
        ipcRenderer.invoke('auth-logout'),

    // ── Connections ──────────────────────────────────────────────────────────
    getConnections: () =>
        ipcRenderer.invoke('get-connections'),

    saveConnection: (connection) =>
        ipcRenderer.invoke('save-connection', connection),

    deleteConnection: (id) =>
        ipcRenderer.invoke('delete-connection', id),

    testConnection: (id) =>
        ipcRenderer.invoke('test-connection', id),

    // ── Database Operations ──────────────────────────────────────────────────
    getSchema: (connectionId, refresh = false) =>
        ipcRenderer.invoke('api-request', {
            method: 'GET',
            endpoint: `/connections/${connectionId}/schema?refresh=${refresh}`
        }),

    executeQuery: (connectionId, query, includeExplanation = true) =>
        ipcRenderer.invoke('api-request', {
            method: 'POST',
            endpoint: '/query',
            data: {
                connection_id: connectionId,
                natural_language: query,
                include_explanation: includeExplanation
            }
        }),

    exportResults: (queryId, format, filename) =>
        ipcRenderer.invoke('api-request', {
            method: 'POST',
            endpoint: '/export',
            data: { query_id: queryId, format, filename }
        }),

    generateReport: (connectionId) =>
        ipcRenderer.invoke('api-request', {
            method: 'GET',
            endpoint: `/reports/summary/${connectionId}`
        }),

    sendAlert: (title, message, channels) =>
        ipcRenderer.invoke('api-request', {
            method: 'POST',
            endpoint: '/alerts/send',
            data: { title, message, channels }
        }),

    // ── File Operations ──────────────────────────────────────────────────────
    openFile: (filepath) =>
        ipcRenderer.invoke('open-file', filepath),

    saveFile: (filename, content) =>
        ipcRenderer.invoke('save-file', { filename, content }),
});