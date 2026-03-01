function togglePassword(inputId, icon) {
    const input = document.getElementById(inputId);
    if (input.type === 'password') {
        input.type = 'text';
        icon.textContent = '🙈';
    } else {
        input.type = 'password';
        icon.textContent = '👁️';
    }
}

// Auth Tab Switching
document.getElementById('login-tab').addEventListener('click', () => {
    document.getElementById('login-tab').classList.add('active');
    document.getElementById('signup-tab').classList.remove('active');
    document.getElementById('login-form').classList.remove('hidden');
    document.getElementById('signup-form').classList.add('hidden');
});

document.getElementById('signup-tab').addEventListener('click', () => {
    document.getElementById('signup-tab').classList.add('active');
    document.getElementById('login-tab').classList.remove('active');
    document.getElementById('signup-form').classList.remove('hidden');
    document.getElementById('login-form').classList.add('hidden');
});

// Login
document.getElementById('login-btn').addEventListener('click', () => {
    const email = document.getElementById('login-email').value;
    const password = document.getElementById('login-password').value;
    if (email && password) {
       document.getElementById('login-screen').style.display = 'none';
    } else {
        alert('Please enter email and password');
    }
});

// Sign Up
document.getElementById('signup-btn').addEventListener('click', () => {
    const name = document.getElementById('signup-name').value;
    const company = document.getElementById('signup-company').value;
    const email = document.getElementById('signup-email').value;
    const password = document.getElementById('signup-password').value;
    if (name && company && email && password) {
        alert('Account created! Please login.');
        document.getElementById('login-tab').click();
    } else {
        alert('Please fill all fields');
    }
});

// Logout
document.getElementById('logout-btn').addEventListener('click', () => {
    document.getElementById('login-screen').style.display = 'flex';
});

// Profile dropdown toggle
document.getElementById('user-avatar-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    document.getElementById('profile-dropdown').classList.toggle('hidden');
});

// Close when clicking outside
document.addEventListener('click', () => {
    document.getElementById('profile-dropdown').classList.add('hidden');
});

// Prevent closing when clicking inside dropdown
document.getElementById('profile-dropdown').addEventListener('click', (e) => {
    e.stopPropagation();
});

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
    
    bindEvents() {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => this.switchView(e.target.closest('.nav-item').dataset.view));
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
    
    setupNavigation() {
        this.switchView('query');
    }
    
    switchView(viewName) {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.remove('active');
            if (item.dataset.view === viewName) item.classList.add('active');
        });
        
        document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
        document.getElementById(`${viewName}-view`).classList.add('active');
        
        if (viewName === 'connections') this.loadConnections();
        else if (viewName === 'schema') this.populateSchemaConnectionSelect();
        else if (viewName === 'reports') this.populateReportConnectionSelect();
    }
    
    async apiRequest(method, endpoint, data = null) {
        try {
            const config = { method, headers: { 'Content-Type': 'application/json' } };
            if (data && (method === 'POST' || method === 'PUT')) {
                config.body = JSON.stringify(data);
            }
            const response = await fetch(`/api/v1${endpoint}`, config);
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            this.showToast('Failed to connect to server', 'error');
            return { error: error.message };
        }
    }

    async loadConnections() {
        const result = await this.apiRequest('GET', '/connections');
        if (result.error) { this.showToast('Failed to load connections', 'error'); return; }
        this.connections = Array.isArray(result) ? result : [];
        this.renderConnections();
        this.populateConnectionSelects();
    }
    
    renderConnections() {
        const container = document.getElementById('connections-list');
        if (this.connections.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted); text-align: center; padding: 40px;">No connections yet. Click "Add New Connection" to get started.</p>';
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
        const selects = ['query-connection', 'schema-connection', 'report-connection'];
        selects.forEach(selectId => {
            const select = document.getElementById(selectId);
            if (!select) return;
            const currentValue = select.value;
            select.innerHTML = '<option value="">Select a connection...</option>';
            this.connections.forEach(conn => {
                const option = document.createElement('option');
                option.value = conn.id;
                option.textContent = `${conn.name} (${conn.database})`;
                select.appendChild(option);
            });
            if (currentValue) select.value = currentValue;
        });
    }
    
    populateSchemaConnectionSelect() {
        this.populateConnectionSelects();
        document.getElementById('schema-connection').addEventListener('change', (e) => {
            if (e.target.value) this.loadSchema();
        });
    }
    
    populateReportConnectionSelect() {
        this.populateConnectionSelects();
    }
    
    openConnectionModal() {
        document.getElementById('modal-overlay').classList.remove('hidden');
        document.getElementById('connection-form').reset();
        document.getElementById('conn-dialect').addEventListener('change', (e) => {
            const portInput = document.getElementById('conn-port');
            if (e.target.value === 'postgresql') portInput.value = '5432';
            else if (e.target.value === 'mysql') portInput.value = '3306';
            else if (e.target.value === 'mariadb') portInput.value = '3306';
        });
    }
    
    closeConnectionModal() {
        document.getElementById('modal-overlay').classList.add('hidden');
    }
    
    async saveConnection(e) {
        e.preventDefault();
        const connection = {
            name: document.getElementById('conn-name').value,
            dialect: document.getElementById('conn-dialect').value,
            host: document.getElementById('conn-host').value,
            port: parseInt(document.getElementById('conn-port').value),
            database: document.getElementById('conn-database').value,
            username: document.getElementById('conn-username').value,
            password: document.getElementById('conn-password').value,
        };
        const result = await this.apiRequest('POST', '/connections', connection);
        if (result.error) { this.showToast(result.error, 'error'); return; }
        this.closeConnectionModal();
        this.loadConnections();
        this.showToast('Connection saved successfully', 'success');
    }
    
    async testNewConnection() {
        const connection = {
            name: document.getElementById('conn-name').value || 'Test',
            dialect: document.getElementById('conn-dialect').value,
            host: document.getElementById('conn-host').value,
            port: parseInt(document.getElementById('conn-port').value),
            database: document.getElementById('conn-database').value,
            username: document.getElementById('conn-username').value,
            password: document.getElementById('conn-password').value,
        };
        const result = await this.apiRequest('POST', '/connections', connection);
        if (result.status === 'connected') {
            this.showToast('Connection successful!', 'success');
        } else {
            this.showToast(`Connection failed: ${result.message || 'Unknown error'}`, 'error');
        }
    }
    
    async testConnection(connectionId) {
        const result = await this.apiRequest('POST', `/connections/${connectionId}/test`);
        if (result.success) {
            this.showToast('Connection test successful!', 'success');
        } else {
            this.showToast(`Connection failed: ${result.message}`, 'error');
        }
    }
    
    async deleteConnection(connectionId) {
        if (!confirm('Are you sure you want to delete this connection?')) return;
        const result = await this.apiRequest('DELETE', `/connections/${connectionId}`);
        if (!result.error) {
            this.loadConnections();
            this.showToast('Connection deleted', 'success');
        } else {
            this.showToast('Failed to delete connection', 'error');
        }
    }
    
    async executeQuery() {
        const connectionId = document.getElementById('query-connection').value;
        const naturalQuery = document.getElementById('natural-query').value.trim();
        
        if (!connectionId) { this.showToast('Please select a database connection', 'warning'); return; }
        if (!naturalQuery) { this.showToast('Please enter a query', 'warning'); return; }
        
        const btn = document.getElementById('execute-query');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="btn-icon">⏳</span> Processing...';
        btn.disabled = true;
        
        try {
            const request = {
                connection_id: connectionId,
                natural_language: naturalQuery,
                include_explanation: document.getElementById('include-explanation').checked,
            };
            const result = await this.apiRequest('POST', '/query', request);
            if (result.error) { this.showToast(result.error, 'error'); return; }
            if (!result.success) { this.showToast(`Query failed: ${result.error_message}`, 'error'); return; }
            
            this.currentQuery = result;
            this.displayResults(result);
            this.showToast(`Query executed: ${result.row_count} rows`, 'success');
        } catch (error) {
            this.showToast('Failed to execute query', 'error');
            console.error(error);
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    }
    
    displayResults(result) {
        const resultsSection = document.getElementById('query-results');
        resultsSection.classList.remove('hidden');
        
        document.getElementById('execution-time').textContent = `⏱ ${result.execution_time_ms.toFixed(2)}ms`;
        document.getElementById('row-count').textContent = `📊 ${result.row_count} rows`;
        
        const showSQL = document.getElementById('show-sql').checked;
        const sqlDiv = document.getElementById('generated-sql');
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
        
        const thead = document.getElementById('results-head');
        const tbody = document.getElementById('results-body');
        thead.innerHTML = '<tr>' + result.columns.map(col => `<th>${this.escapeHtml(col)}</th>`).join('') + '</tr>';
        const displayRows = result.results.slice(0, 1000);
        tbody.innerHTML = displayRows.map(row => {
            return '<tr>' + result.columns.map(col => `<td>${this.escapeHtml(String(row[col] ?? ''))}</td>`).join('') + '</tr>';
        }).join('');
        
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    
    async exportResults(format) {
        if (!this.currentQuery) { this.showToast('No query results to export', 'warning'); return; }
        try {
            const request = {
                query_id: this.currentQuery.query_id,
                format: format,
                filename: `query_export_${Date.now()}`,
            };
            const result = await this.apiRequest('POST', '/export', request);
            if (result.success) {
                this.showToast(`Exported to ${format.toUpperCase()} successfully!`, 'success');
            } else {
                this.showToast(`Export failed: ${result.error || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            this.showToast('Failed to export results', 'error');
        }
    }
    
    copySQL() {
        const sql = document.getElementById('sql-code').textContent;
        navigator.clipboard.writeText(sql).then(() => {
            this.showToast('SQL copied to clipboard', 'success');
        });
    }
    
    async loadSchema(forceRefresh = false) {
        const connectionId = document.getElementById('schema-connection').value;
        if (!connectionId) { this.showToast('Please select a connection', 'warning'); return; }
        const result = await this.apiRequest('GET', `/connections/${connectionId}/schema?refresh=${forceRefresh}`);
        if (result.error) { this.showToast('Failed to load schema', 'error'); return; }
        this.renderSchema(result);
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
                    <span style="color: var(--text-muted); font-size: 12px; font-weight: normal;">
                        (${table.row_count || 0} rows)
                    </span>
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
        
        if (schemaData.relationships && schemaData.relationships.length > 0) {
            container.innerHTML += `
                <div class="schema-table">
                    <div class="schema-table-name">
                        <span class="table-icon">🔗</span>
                        Relationships (${schemaData.relationships.length})
                    </div>
                    <div class="schema-columns">
                        ${schemaData.relationships.map(rel => `
                            <div class="schema-column">
                                <span class="schema-column-name">
                                    ${this.escapeHtml(rel.from_table)}.${this.escapeHtml(rel.from_column)}
                                </span>
                                <span class="schema-column-type">→ ${this.escapeHtml(rel.to_table)}.${this.escapeHtml(rel.to_column)}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }
    }
    
    async generateSummaryReport() {
        const connectionId = document.getElementById('report-connection').value;
        if (!connectionId) { this.showToast('Please select a connection', 'warning'); return; }
        const result = await this.apiRequest('GET', `/reports/summary/${connectionId}`);
        if (result.error) { this.showToast('Failed to generate report', 'error'); return; }
        this.showToast('Summary report generated successfully', 'success');
        console.log('Summary:', result);
    }
    
    async sendTestAlert() {
        const title = document.getElementById('test-alert-title').value.trim();
        const message = document.getElementById('test-alert-message').value.trim();
        const channels = [];
        if (document.getElementById('channel-email').checked) channels.push('email');
        if (document.getElementById('channel-slack').checked) channels.push('slack');
        if (!title || !message) { this.showToast('Please fill in title and message', 'warning'); return; }
        if (channels.length === 0) { this.showToast('Please select at least one channel', 'warning'); return; }
        const result = await this.apiRequest('POST', '/alerts/send', { title, message, channels });
        const hasSuccess = Object.values(result).some(v => v === true);
        if (hasSuccess) {
            this.showToast('Test alert sent successfully', 'success');
        } else {
            this.showToast('Failed to send test alert', 'error');
        }
    }
    
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
        setTimeout(() => { toast.remove(); }, 5000);
    }
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

const app = new AICopilotApp();

