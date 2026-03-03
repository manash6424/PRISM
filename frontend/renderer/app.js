
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
    
    // Event Bindings
    bindEvents() {
        // Navigation
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => this.switchView(e.target.closest('.nav-item').dataset.view));
        });
        
        // Query execution
        document.getElementById('execute-query').addEventListener('click', () => this.executeQuery());
        document.getElementById('natural-query').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.ctrlKey) {
                this.executeQuery();
            }
        });
        
        // Connection modal
        document.getElementById('add-connection').addEventListener('click', () => this.openConnectionModal());
        document.getElementById('close-modal').addEventListener('click', () => this.closeConnectionModal());
        document.getElementById('modal-overlay').addEventListener('click', (e) => {
            if (e.target.id === 'modal-overlay') this.closeConnectionModal();
        });
        document.getElementById('connection-form').addEventListener('submit', (e) => this.saveConnection(e));
        document.getElementById('test-connection-btn').addEventListener('click', () => this.testNewConnection());
        
        // Export buttons
        document.getElementById('export-csv').addEventListener('click', () => this.exportResults('csv'));
        document.getElementById('export-excel').addEventListener('click', () => this.exportResults('xlsx'));
        document.getElementById('export-pdf').addEventListener('click', () => this.exportResults('pdf'));
        
        // Copy SQL
        document.getElementById('copy-sql').addEventListener('click', () => this.copySQL());
        
        // Schema refresh
        document.getElementById('refresh-schema').addEventListener('click', () => this.loadSchema(true));
        
        // Report generation
        document.getElementById('generate-summary').addEventListener('click', () => this.generateSummaryReport());
        
        // Alert testing
        document.getElementById('send-test-alert').addEventListener('click', () => this.sendTestAlert());
    }
    
    // Navigation
    setupNavigation() {
        const defaultView = 'query';
        this.switchView(defaultView);
    }
    
    switchView(viewName) {
        // Update nav items
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.remove('active');
            if (item.dataset.view === viewName) {
                item.classList.add('active');
            }
        });
        
        // Update views
        document.querySelectorAll('.view').forEach(view => {
            view.classList.remove('active');
        });
        document.getElementById(`${viewName}-view`).classList.add('active');
        
        // Load view-specific data
        if (viewName === 'connections') {
            this.loadConnections();
        } else if (viewName === 'schema') {
            this.populateSchemaConnectionSelect();
        } else if (viewName === 'reports') {
            this.populateReportConnectionSelect();
        }
    }
    
    // API Calls
    async apiRequest(method, endpoint, data = null) {
        try {
            const config = {
                method,
                headers: { 'Content-Type': 'application/json' }
            };
            
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
// Connection Management
    async loadConnections() {
        const result = await this.apiRequest('GET', '/connections');
        
        if (result.error) {
            this.showToast('Failed to load connections', 'error');
            return;
        }
        
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
        
        // Set default port based on dialect
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
        
        if (result.error) {
            this.showToast(result.error, 'error');
            return;
        }
        
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
    
    // Query Execution
    async executeQuery() {
        const connectionId = document.getElementById('query-connection').value;
        const naturalQuery = document.getElementById('natural-query').value.trim();
        
        if (!connectionId) {
            this.showToast('Please select a database connection', 'warning');
            return;
        }
        
        if (!naturalQuery) {
            this.showToast('Please enter a query', 'warning');
            return;
        }
        
        // Show loading state
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
            
            if (result.error) {
                this.showToast(result.error, 'error');
                return;
            }
            
            if (!result.success) {
                this.showToast(`Query failed: ${result.error_message}`, 'error');
                return;
            }
            
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
        
        // Execution info
        document.getElementById('execution-time').textContent = `⏱ ${result.execution_time_ms.toFixed(2)}ms`;
        document.getElementById('row-count').textContent = `📊 ${result.row_count} rows`;
        
        // Generated SQL
        const showSQL = document.getElementById('show-sql').checked;
        const sqlDiv = document.getElementById('generated-sql');
        
        if (showSQL && result.generated_sql) {
            sqlDiv.classList.remove('hidden');
            document.getElementById('sql-code').textContent = result.generated_sql;
        } else {
            sqlDiv.classList.add('hidden');
        }
        
        // Explanation
        const explainDiv = document.getElementById('sql-explanation');
        const includeExplanation = document.getElementById('include-explanation').checked;
        
        if (includeExplanation && result.explanation) {
            explainDiv.classList.remove('hidden');
            document.getElementById('explanation-text').textContent = result.explanation;
        } else {
            explainDiv.classList.add('hidden');
        }
        
        // Table
        const thead = document.getElementById('results-head');
        const tbody = document.getElementById('results-body');
        
        // Headers
        thead.innerHTML = '<tr>' + result.columns.map(col => `<th>${this.escapeHtml(col)}</th>`).join('') + '</tr>';
        
        // Body (limit to 1000 rows for display)
        const displayRows = result.results.slice(0, 1000);
        tbody.innerHTML = displayRows.map(row => {
            return '<tr>' + result.columns.map(col => `<td>${this.escapeHtml(String(row[col] ?? ''))}</td>`).join('') + '</tr>';
        }).join('');
        
        // Scroll to results
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    
    // Export
    async exportResults(format) {
        if (!this.currentQuery) {
            this.showToast('No query results to export', 'warning');
            return;
        }
        
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
    
    // Schema
    async loadSchema(forceRefresh = false) {
        const connectionId = document.getElementById('schema-connection').value;
        
        if (!connectionId) {
            this.showToast('Please select a connection', 'warning');
            return;
        }
        
        const result = await this.apiRequest('GET', `/connections/${connectionId}/schema?refresh=${forceRefresh}`);
        
        if (result.error) {
            this.showToast('Failed to load schema', 'error');
            return;
        }
        
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
        
        // Show relationships if available
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
    
    // Reports
    async generateSummaryReport() {
        const connectionId = document.getElementById('report-connection').value;
        
        if (!connectionId) {
            this.showToast('Please select a connection', 'warning');
            return;
        }
        
        const result = await this.apiRequest('GET', `/reports/summary/${connectionId}`);
        
        if (result.error) {
            this.showToast('Failed to generate report', 'error');
            return;
        }
        
        this.showToast('Summary report generated successfully', 'success');
        console.log('Summary:', result);
    }
    
    // Alerts
    async sendTestAlert() {
        const title = document.getElementById('test-alert-title').value.trim();
        const message = document.getElementById('test-alert-message').value.trim();
        
        const channels = [];
        if (document.getElementById('channel-email').checked) channels.push('email');
        if (document.getElementById('channel-slack').checked) channels.push('slack');
        
        if (!title || !message) {
            this.showToast('Please fill in title and message', 'warning');
            return;
        }
        
        if (channels.length === 0) {
            this.showToast('Please select at least one channel', 'warning');
            return;
        }
        
        const result = await this.apiRequest('POST', '/alerts/send', {
            title,
            message,
            channels
        });
        
        const hasSuccess = Object.values(result).some(v => v === true);
        
        if (hasSuccess) {
            this.showToast('Test alert sent successfully', 'success');
        } else {
            this.showToast('Failed to send test alert', 'error');
        }
    }
    
    // Toast Notifications
    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        const icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };
        
        toast.innerHTML = `
            <span class="toast-icon">${icons[type]}</span>
            <span class="toast-message">${this.escapeHtml(message)}</span>
            <button class="toast-close" onclick="this.parentElement.remove()">×</button>
        `;
        
        container.appendChild(toast);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            toast.remove();
        }, 5000);
    }
    
    // Utility
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize app
const app = new AICopilotApp();
