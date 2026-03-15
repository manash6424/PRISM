const API = 'http://localhost:8000/api/v1';
 
class AICopilotApp {
    constructor() {
        this.connections = [];
        this.currentConnection = null;
        this.currentQuery = null;
        this.init();
    }
 
    init() {
        this.bindEvents();
        this.loadConnections();
        this.setupNavigation();
    }
 
    // ── Event Bindings ──────────────────────────────────────────────────────
    bindEvents() {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) =>
                this.switchView(e.target.closest('.nav-item').dataset.view));
        });
 
        document.getElementById('execute-query').addEventListener('click', () => this.executeQuery());
        document.getElementById('natural-query').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.ctrlKey) this.executeQuery();
        });
 
        document.getElementById('add-connection').addEventListener('click', () => this.openConnectionModal());
        document.getElementById('close-modal').addEventListener('click', () => this.closeConnectionModal());
        document.getElementById('modal-overlay').addEventListener('click', (e) => {
            if (e.target.id === 'modal-overlay') this.closeConnectionModal();
        });
        document.getElementById('connection-form').addEventListener('submit', (e) => this.saveConnection(e));
        document.getElementById('test-connection-btn').addEventListener('click', () => this.testNewConnection());
 
        document.getElementById('export-csv').addEventListener('click', () => this.exportResults('csv'));
        document.getElementById('export-excel').addEventListener('click', () => this.exportResults('xlsx'));
        document.getElementById('export-pdf').addEventListener('click', () => this.exportResults('pdf'));
 
        document.getElementById('copy-sql').addEventListener('click', () => this.copySQL());
        document.getElementById('refresh-schema').addEventListener('click', () => this.loadSchema(true));
        document.getElementById('generate-summary').addEventListener('click', () => this.generateSummaryReport());
        document.getElementById('send-test-alert').addEventListener('click', () => this.sendTestAlert());
    }
 
    // ── Navigation ──────────────────────────────────────────────────────────
    setupNavigation() {
        this.switchView('query');
    }
 
    switchView(viewName) {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.view === viewName);
        });
        document.querySelectorAll('.view').forEach(view => {
            view.classList.remove('active');
        });
        const target = document.getElementById(`${viewName}-view`);
        if (target) target.classList.add('active');
 
        if (viewName === 'connections') this.loadConnections();
        else if (viewName === 'schema') this.populateSchemaConnectionSelect();
        else if (viewName === 'reports') this.populateReportConnectionSelect();
    }
 
    // ── Connections ─────────────────────────────────────────────────────────
    async loadConnections() {
        try {
            const res = await fetch(`${API}/connections`);
            const result = await res.json();
            this.connections = Array.isArray(result) ? result : [];
            this.renderConnections();
            this.populateConnectionSelects();
        } catch (err) {
            this.showToast('Failed to load connections', 'error');
        }
    }
 
    renderConnections() {
        const container = document.getElementById('connections-list');
        if (this.connections.length === 0) {
            container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px;">No connections yet. Click "Add New Connection" to get started.</p>';
            return;
        }
        container.innerHTML = this.connections.map(conn => `
            <div class="connection-card" data-id="${conn.id}">
                <div class="connection-card-header">
                    <div class="connection-card-title">${this.escapeHtml(conn.name)}</div>
                    <div class="connection-card-type">${conn.dialect}</div>
                </div>
                <div class="connection-card-details">
                    <p><strong>Host:</strong> ${this.escapeHtml(conn.host)}</p>
                    <p><strong>Database:</strong> ${this.escapeHtml(conn.database)}</p>
                </div>
                <div class="connection-card-status">
                    <span class="status-dot ${conn.status}"></span>
                    <span>${conn.status === 'connected' ? 'Connected' : 'Disconnected'}</span>
                </div>
                <div class="connection-card-actions">
                    <button class="btn-secondary" onclick="app.testConnection('${conn.id}')">Test</button>
                    <button class="btn-secondary" onclick="app.deleteConnection('${conn.id}')">Delete</button>
                </div>
            </div>
        `).join('');
    }
 
    populateConnectionSelects() {
        ['query-connection', 'schema-connection', 'report-connection'].forEach(selectId => {
            const select = document.getElementById(selectId);
            if (!select) return;
            const currentValue = select.value;
            select.innerHTML = '<option value="">Select a connection...</option>';
            this.connections.forEach(conn => {
                const opt = document.createElement('option');
                opt.value = conn.id;
                opt.textContent = `${conn.name} (${conn.database})`;
                select.appendChild(opt);
            });
            if (currentValue) select.value = currentValue;
        });
    }
 
    populateSchemaConnectionSelect() {
        this.populateConnectionSelects();
        const sel = document.getElementById('schema-connection');
        sel.onchange = (e) => { if (e.target.value) this.loadSchema(); };
    }
 
    populateReportConnectionSelect() {
        this.populateConnectionSelects();
    }
 
    openConnectionModal() {
        document.getElementById('modal-overlay').classList.remove('hidden');
        document.getElementById('connection-form').reset();
        document.getElementById('conn-dialect').onchange = (e) => {
            const port = document.getElementById('conn-port');
            if (e.target.value === 'postgresql') port.value = '5432';
            else if (['mysql', 'mariadb'].includes(e.target.value)) port.value = '3306';
        };
    }
 
    closeConnectionModal() {
        document.getElementById('modal-overlay').classList.add('hidden');
    }
 
    async saveConnection(e) {
        e.preventDefault();
        const connection = {
            name:     document.getElementById('conn-name').value,
            dialect:  document.getElementById('conn-dialect').value,
            host:     document.getElementById('conn-host').value,
            port:     parseInt(document.getElementById('conn-port').value),
            database: document.getElementById('conn-database').value,
            username: document.getElementById('conn-username').value,
            password: document.getElementById('conn-password').value,
        };
        try {
            const res = await fetch(`${API}/connections`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(connection)
            });
            const result = await res.json();
            if (result.error) { this.showToast(result.error, 'error'); return; }
            this.closeConnectionModal();
            this.loadConnections();
            this.showToast('Connection saved successfully!', 'success');
        } catch (err) {
            this.showToast('Failed to save connection', 'error');
        }
    }
 
    async testNewConnection() {
        const connection = {
            name:     document.getElementById('conn-name').value || 'Test',
            dialect:  document.getElementById('conn-dialect').value,
            host:     document.getElementById('conn-host').value,
            port:     parseInt(document.getElementById('conn-port').value),
            database: document.getElementById('conn-database').value,
            username: document.getElementById('conn-username').value,
            password: document.getElementById('conn-password').value,
        };
        try {
            const res = await fetch(`${API}/connections`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(connection)
            });
            const result = await res.json();
            if (result.status === 'connected') {
                this.showToast('Connection successful!', 'success');
            } else {
                this.showToast(`Connection failed: ${result.message || 'Unknown error'}`, 'error');
            }
        } catch (err) {
            this.showToast('Failed to test connection', 'error');
        }
    }
 
    async testConnection(connectionId) {
        try {
            const res = await fetch(`${API}/connections/${connectionId}/test`, { method: 'POST' });
            const result = await res.json();
            if (result.success) {
                this.showToast('Connection test successful!', 'success');
            } else {
                this.showToast(`Connection failed: ${result.message}`, 'error');
            }
        } catch (err) {
            this.showToast('Failed to test connection', 'error');
        }
    }
 
    async deleteConnection(connectionId) {
        if (!confirm('Are you sure you want to delete this connection?')) return;
        try {
            const res = await fetch(`${API}/connections/${connectionId}`, { method: 'DELETE' });
            if (res.ok) {
                this.loadConnections();
                this.showToast('Connection deleted', 'success');
            } else {
                this.showToast('Failed to delete connection', 'error');
            }
        } catch (err) {
            this.showToast('Failed to delete connection', 'error');
        }
    }
 
    // ── Query ───────────────────────────────────────────────────────────────
    async executeQuery() {
        const connectionId = document.getElementById('query-connection').value;
        const naturalQuery = document.getElementById('natural-query').value.trim();
        const includeExpl  = document.getElementById('include-explanation').checked;
 
        if (!connectionId) { this.showToast('Please select a database connection', 'warning'); return; }
        if (!naturalQuery)  { this.showToast('Please enter a query', 'warning'); return; }
 
        const btn = document.getElementById('execute-query');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="btn-icon">⏳</span> Processing...';
        btn.disabled = true;
 
        try {
            const res = await fetch(`${API}/query`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    connection_id: connectionId,
                    natural_language: naturalQuery,
                    include_explanation: includeExpl
                })
            });
            const result = await res.json();
 
            if (!res.ok || result.error) { this.showToast(result.detail || result.error || 'Query failed', 'error'); return; }
            if (!result.success) { this.showToast(`Query failed: ${result.error_message}`, 'error'); return; }
 
            this.currentQuery = result;
            this.displayResults(result);
            this.showToast(`Query executed: ${result.row_count} rows`, 'success');
        } catch (error) {
            this.showToast('Failed to execute query', 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    }
 
    displayResults(result) {
        const resultsSection = document.getElementById('query-results');
        resultsSection.classList.remove('hidden');
 
        document.getElementById('execution-time').textContent = `⏱ ${result.execution_time_ms?.toFixed(2)}ms`;
        document.getElementById('row-count').textContent = `📊 ${result.row_count} rows`;
 
        const showSQL = document.getElementById('show-sql').checked;
        const sqlDiv  = document.getElementById('generated-sql');
        if (showSQL && result.generated_sql) {
            sqlDiv.classList.remove('hidden');
            document.getElementById('sql-code').textContent = result.generated_sql;
        } else {
            sqlDiv.classList.add('hidden');
        }
 
        const explainDiv = document.getElementById('sql-explanation');
        if (document.getElementById('include-explanation').checked && result.explanation) {
            explainDiv.classList.remove('hidden');
            document.getElementById('explanation-text').textContent = result.explanation;
        } else {
            explainDiv.classList.add('hidden');
        }
 
        document.getElementById('results-head').innerHTML =
            '<tr>' + result.columns.map(col => `<th>${this.escapeHtml(col)}</th>`).join('') + '</tr>';
 
        document.getElementById('results-body').innerHTML =
            result.results.slice(0, 1000).map(row =>
                '<tr>' + result.columns.map(col =>
                    `<td>${this.escapeHtml(String(row[col] ?? ''))}</td>`
                ).join('') + '</tr>'
            ).join('');
 
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
 
    // ── Export ──────────────────────────────────────────────────────────────
    async exportResults(format) {
        if (!this.currentQuery) { this.showToast('No query results to export', 'warning'); return; }
 
        const btnId = format === 'xlsx' ? 'export-excel' : `export-${format}`;
        const btn = document.getElementById(btnId);
        const originalText = btn.innerHTML;
        btn.innerHTML = '⏳ Exporting...';
        btn.disabled = true;
 
        try {
            const res = await fetch(`${API}/export`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query_id: this.currentQuery.query_id,
                    format: format,
                    filename: `query_export_${Date.now()}`
                })
            });
            const result = await res.json();
 
            if (result.success && result.filepath) {
                // Open the file using Electron shell
                if (window.api && window.api.openFile) {
                    await window.api.openFile(result.filepath);
                    this.showToast(`${format.toUpperCase()} opened successfully!`, 'success');
                } else {
                    this.showToast(`Saved to: ${result.filepath}`, 'success');
                }
            } else {
                this.showToast(`Export failed: ${result.error || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            this.showToast('Failed to export results', 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    }
 
    copySQL() {
        const sql = document.getElementById('sql-code').textContent;
        navigator.clipboard.writeText(sql).then(() => {
            this.showToast('SQL copied to clipboard', 'success');
        });
    }
 
    // ── Schema ──────────────────────────────────────────────────────────────
    async loadSchema(forceRefresh = false) {
        const connectionId = document.getElementById('schema-connection').value;
        if (!connectionId) { this.showToast('Please select a connection', 'warning'); return; }
        try {
            const res = await fetch(`${API}/connections/${connectionId}/schema?force_refresh=${forceRefresh}`);
            const result = await res.json();
            if (result.error) { this.showToast('Failed to load schema', 'error'); return; }
            this.renderSchema(result);
        } catch (err) {
            this.showToast('Failed to load schema', 'error');
        }
    }
 
    renderSchema(schemaData) {
        const container = document.getElementById('schema-content');
        if (!schemaData.tables || schemaData.tables.length === 0) {
            container.innerHTML = '<div class="schema-placeholder">No tables found</div>';
            return;
        }
        container.innerHTML = schemaData.tables.map(table => `
            <div class="schema-table">
                <div class="schema-table-name">
                    <span class="table-icon">📋</span>
                    ${this.escapeHtml(table.name)}
                    <span style="color:var(--text-muted);font-size:12px;font-weight:normal;">(${table.row_count || 0} rows)</span>
                </div>
                <div class="schema-columns">
                    ${table.columns.map(col => `
                        <div class="schema-column">
                            <span class="schema-column-name">
                                ${this.escapeHtml(col.name)}
                                ${col.is_primary_key ? '<span class="schema-pk">PK</span>' : ''}
                            </span>
                            <span class="schema-column-type">${this.escapeHtml(col.data_type)} ${col.is_nullable ? 'NULL' : 'NOT NULL'}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `).join('');
    }
 
    // ── Reports ─────────────────────────────────────────────────────────────
    async generateSummaryReport() {
        const connectionId = document.getElementById('report-connection').value;
        if (!connectionId) { this.showToast('Please select a connection', 'warning'); return; }
        try {
            const res = await fetch(`${API}/reports/summary`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ connection_id: connectionId })
            });
            const result = await res.json();
            if (result.error) { this.showToast('Failed to generate report', 'error'); return; }
            this.showToast('Summary report generated successfully', 'success');
        } catch (err) {
            this.showToast('Failed to generate report', 'error');
        }
    }
 
    // ── Alerts ──────────────────────────────────────────────────────────────
    async sendTestAlert() {
        const title    = document.getElementById('test-alert-title').value.trim();
        const message  = document.getElementById('test-alert-message').value.trim();
        const channels = [];
        if (document.getElementById('channel-email').checked) channels.push('email');
        if (document.getElementById('channel-slack').checked) channels.push('slack');
 
        if (!title || !message) { this.showToast('Please fill in title and message', 'warning'); return; }
        if (channels.length === 0) { this.showToast('Please select at least one channel', 'warning'); return; }
 
        try {
            const res = await fetch(`${API}/alerts/test`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title, message, channels })
            });
            const result = await res.json();
            const hasSuccess = Object.values(result).some(v => v === true);
            if (hasSuccess) {
                this.showToast('Test alert sent successfully', 'success');
            } else {
                this.showToast('Failed to send test alert', 'error');
            }
        } catch (err) {
            this.showToast('Failed to send test alert', 'error');
        }
    }
 
    // ── Toast ───────────────────────────────────────────────────────────────
    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
        toast.innerHTML = `
            <span class="toast-icon">${icons[type]}</span>
            <span class="toast-message">${this.escapeHtml(message)}</span>
            <button class="toast-close" onclick="this.parentElement.remove()">×</button>
        `;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 5000);
    }
 
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}
 
const app = new AICopilotApp();