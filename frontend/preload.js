const { contextBridge, ipcRenderer } = require('electron');

// Securely expose selected APIs to renderer
contextBridge.exposeInMainWorld('api', {

    // ==========================
    // Connection Management
    // ==========================

    getConnections: () =>
        ipcRenderer.invoke('get-connections'),

    saveConnection: (connection) =>
        ipcRenderer.invoke('save-connection', connection),

    testConnection: (id) =>
        ipcRenderer.invoke('api-request', {
            method: 'POST',
            endpoint: `/connections/${id}/test`
        }),

    deleteConnection: (id) =>
        ipcRenderer.invoke('api-request', {
            method: 'DELETE',
            endpoint: `/connections/${id}`
        }),

    // ==========================
    // Database Operations
    // ==========================

    getSchema: (connectionId, refresh = false) =>
        ipcRenderer.invoke('api-request', {
            method: 'GET',
            endpoint: `/connections/${connectionId}/schema?refresh=${refresh}`
        }),

    getTables: (connectionId) =>
        ipcRenderer.invoke('api-request', {
            method: 'GET',
            endpoint: `/connections/${connectionId}/tables`
        }),

    executeQuery: (connectionId, query) =>
        ipcRenderer.invoke('api-request', {
            method: 'POST',
            endpoint: `/connections/${connectionId}/query`,
            body: { query }
        })
});