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
        this.renderSavedQueries();
        this.loadTheme();
        this.initKeyboardShortcuts();
        this.renderHistory();
    }

    // ── Auth Token ──────────────────────────────────────────────────────────
    getToken() {
        const session = localStorage.getItem('prism_session');
        if (session) {
            try {
                const parsed = JSON.parse(session);
                return parsed.token || localStorage.getItem('access_token') || 'dev-token';
            } catch { return 'dev-token'; }
        }
        return localStorage.getItem('access_token') || 'dev-token';
    }

    authHeaders() {
        return {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.getToken()}`
        };
    }

    async authFetch(url, options = {}) {
        const token = this.getToken();
        const headers = {
            ...options.headers,
            'Content-Type': options.headers?.['Content-Type'] || 'application/json'
        };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const res = await fetch(url, { ...options, headers });

        if (res.status === 401) {
            localStorage.removeItem('access_token');
        }

        return res;
    }

    // ── Event Bindings ──────────────────────────────────────────────────────
    bindEvents() {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) =>
                this.switchView(e.target.closest('.nav-item').dataset.view));
        });

        document.getElementById('execute-query').addEventListener('click', () => this.executeQuery());
        document.getElementById('natural-query').addEventListener('input', (e) => {
            clearTimeout(this._suggestionTimer);
            this._suggestionTimer = setTimeout(() => {
                this.getQuerySuggestions(e.target.value);
            }, 500);
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.query-input-container')) {
                document.getElementById('suggestions-box').style.display = 'none';
            }
        });

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
        else if (viewName === 'exports') this.loadQueryHistory();
        else if (viewName === 'dashboard') this.renderDashboard();
        else if (viewName === 'alerts') {
            this.renderAlertRules();
            this.renderAlertHistory();
            this.populateConnectionSelects();
        }
    }

    // ── Connections ─────────────────────────────────────────────────────────
    async loadConnections() {
        try {
            const res = await this.authFetch(`${API}/connections`); // ✅ auth
            if (!res) return;
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
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🔌</div>
                    <div class="empty-state-text">No connections yet</div>
                    <div class="empty-state-sub">Click "Add New Connection" to get started</div>
                </div>`;
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
                    <span class="status-dot ${conn.status === 'connected' ? 'connected' : ''}"></span>
                    <span>${conn.status === 'connected' ? 'Connected' : 'Disconnected'}</span>
                </div>
                <div class="connection-card-actions">
                    <button class="btn-secondary" onclick="app.testConnection('${conn.id}')">🔌 Test</button>
                    <button class="btn-danger" onclick="app.deleteConnection('${conn.id}')">🗑 Delete</button>
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
            const res = await this.authFetch(`${API}/connections`, { // ✅ auth
                method: 'POST',
                body: JSON.stringify(connection)
            });
            if (!res) return;
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
            const res = await this.authFetch(`${API}/connections`, { // ✅ auth
                method: 'POST',
                body: JSON.stringify(connection)
            });
            if (!res) return;
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
            const res = await this.authFetch(`${API}/connections/${connectionId}/test`, { // ✅ auth
                method: 'POST'
            });
            if (!res) return;
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
            const res = await this.authFetch(`${API}/connections/${connectionId}`, { // ✅ auth
                method: 'DELETE'
            });
            if (!res) return;
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
            const res = await this.authFetch(`${API}/query`, { // ✅ auth
                method: 'POST',
                body: JSON.stringify({
                    connection_id: connectionId,
                    natural_language: naturalQuery,
                    include_explanation: includeExpl
                })
            });
            if (!res) return;
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

        this.renderChart(result);
        this.saveToHistory(
            document.getElementById('natural-query').value,
            result.row_count,
            `${result.execution_time_ms?.toFixed(2)}ms`
        );
        this.renderHistory();
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // ── Query History ────────────────────────────────────────────────────────
    saveToHistory(query, rowCount, executionTime) {
        const history = JSON.parse(localStorage.getItem('query_history') || '[]');
        history.unshift({ query, rowCount, executionTime, timestamp: new Date().toLocaleString() });
        if (history.length > 50) history.pop();
        localStorage.setItem('query_history', JSON.stringify(history));
    }

    renderHistory() {
        const history = JSON.parse(localStorage.getItem('query_history') || '[]');
        const container = document.getElementById('history-list');
        if (!container) return;
        if (history.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🕓</div>
                    <div class="empty-state-text">No query history yet</div>
                    <div class="empty-state-sub">Queries you run will appear here</div>
                </div>`;
            return;
        }
        container.innerHTML = history.map((h, i) => `
            <div class="history-card" onclick="app.rerunQuery(${i})">
                <div class="history-card-meta">
                    <span class="history-card-time">🕓 ${h.timestamp}</span>
                    <span class="history-card-stats">
                        <span class="stat-badge">📊 ${h.rowCount} rows</span>
                        <span class="stat-badge">⏱ ${h.executionTime}</span>
                    </span>
                </div>
                <div class="history-card-query">${this.escapeHtml(h.query)}</div>
            </div>
        `).join('');
    }

    rerunQuery(indexOrText) {
        if (typeof indexOrText === 'number') {
            const history = JSON.parse(localStorage.getItem('query_history') || '[]');
            const h = history[indexOrText];
            if (!h) return;
            this.switchView('query');
            document.getElementById('natural-query').value = h.query;
            this.showToast('Query loaded! Click Execute to run.', 'info');
        } else {
            this.switchView('query');
            document.getElementById('natural-query').value = indexOrText;
            this.showToast('Query loaded! Click Execute to run.', 'info');
        }
    }

    // ── Search Results ───────────────────────────────────────────────────────
    searchResults(query) {
        if (!this.currentQuery) return;
        const rows = this.currentQuery.results;
        const filtered = query.trim() === '' ? rows : rows.filter(row =>
            Object.values(row).some(val =>
                String(val).toLowerCase().includes(query.toLowerCase())
            )
        );

        document.getElementById('results-body').innerHTML =
            filtered.map(row =>
                '<tr>' + this.currentQuery.columns.map(col =>
                    `<td>${this.escapeHtml(String(row[col] ?? ''))}</td>`
                ).join('') + '</tr>'
            ).join('');

        document.getElementById('row-count').textContent = `📊 ${filtered.length} rows`;
    }

    // ── Theme Toggle ─────────────────────────────────────────────────────────
    toggleTheme() {
        const body = document.body;
        const btn = document.getElementById('theme-toggle');
        const isLight = body.classList.toggle('light-mode');
        btn.textContent = isLight ? '🌙 Dark Mode' : '☀️ Light Mode';
        localStorage.setItem('theme', isLight ? 'light' : 'dark');
    }

    loadTheme() {
        const theme = localStorage.getItem('theme');
        if (theme === 'light') {
            document.body.classList.add('light-mode');
            const btn = document.getElementById('theme-toggle');
            if (btn) btn.textContent = '🌙 Dark Mode';
        }
    }

    // ── Keyboard Shortcuts ───────────────────────────────────────────────────
    initKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 'Enter') {
                e.preventDefault();
                document.getElementById('execute-query')?.click();
            }
            if (e.ctrlKey && e.key === 'k') {
                e.preventDefault();
                document.getElementById('natural-query')?.focus();
            }
            if (e.ctrlKey && e.key === '/') {
                e.preventDefault();
                app.toggleTheme();
            }
        });
    }

    // ── AI Query Suggestions ─────────────────────────────────────────────────
    async getQuerySuggestions(input) {
        if (input.length < 3) {
            document.getElementById('suggestions-box').style.display = 'none';
            return;
        }
        try {
            const res = await this.authFetch(`${API}/suggestions`, { // ✅ auth
                method: 'POST',
                body: JSON.stringify({ input })
            });
            if (!res) return;
            const data = await res.json();
            this.showSuggestions(data.suggestions || []);
        } catch (e) {
            document.getElementById('suggestions-box').style.display = 'none';
        }
    }

    showSuggestions(suggestions) {
        const box = document.getElementById('suggestions-box');
        if (!suggestions.length) { box.style.display = 'none'; return; }
        box.style.display = 'block';
        box.innerHTML = suggestions.map(s => `
            <div class="suggestion-item" onclick="app.applySuggestion('${s.replace(/'/g, "\\'")}')">
                <span class="suggestion-icon">💡</span>
                <span>${this.escapeHtml(s)}</span>
            </div>
        `).join('');
    }

    applySuggestion(text) {
        document.getElementById('natural-query').value = text;
        document.getElementById('suggestions-box').style.display = 'none';
        document.getElementById('natural-query').focus();
    }

    // ── Templates ────────────────────────────────────────────────────────────
    loadTemplate(value) {
        if (!value) return;
        document.getElementById('natural-query').value = value;
        document.getElementById('template-select').value = '';
        this.showToast('Template loaded! Click Execute to run.', 'info');
    }

    // ── Saved Queries ────────────────────────────────────────────────────────
    async saveQuery() {
        const query = document.getElementById('natural-query').value.trim();
        if (!query) { this.showToast('Please enter a query first', 'warning'); return; }

        const name = query.slice(0, 50);
        const saved = JSON.parse(localStorage.getItem('savedQueries') || '[]');
        if (saved.some(s => s.query === query)) {
            this.showToast('Query already saved!', 'warning');
            return;
        }
        saved.push({ name, query, savedAt: new Date().toISOString() });
        localStorage.setItem('savedQueries', JSON.stringify(saved));
        this.renderSavedQueries();
        this.showToast('Query saved! Click the tag to reuse it.', 'success');
    }

    renderSavedQueries() {
        const saved = JSON.parse(localStorage.getItem('savedQueries') || '[]');
        const bar = document.getElementById('saved-queries-bar');
        if (!bar) return;

        if (saved.length === 0) {
            bar.innerHTML = '';
            bar.style.display = 'none';
            return;
        }
        bar.style.display = 'flex';
        bar.innerHTML = saved.map((q, i) => `
            <div class="saved-query-tag">
                <span class="saved-query-label" onclick="app.loadSavedQuery(${i})">⭐ ${this.escapeHtml(q.name)}</span>
                <button class="saved-query-remove" onclick="app.deleteSavedQuery(${i})">×</button>
            </div>
        `).join('');
    }

    loadSavedQuery(index) {
        const saved = JSON.parse(localStorage.getItem('savedQueries') || '[]');
        if (saved[index]) {
            document.getElementById('natural-query').value = saved[index].query;
            this.showToast('Query loaded! Click Execute to run.', 'info');
        }
    }

    deleteSavedQuery(index) {
        const saved = JSON.parse(localStorage.getItem('savedQueries') || '[]');
        saved.splice(index, 1);
        localStorage.setItem('savedQueries', JSON.stringify(saved));
        this.renderSavedQueries();
        this.showToast('Query deleted', 'success');
    }

    // ── Dashboard ────────────────────────────────────────────────────────────
    pinToDashboard() {
        if (!this.currentQuery) { this.showToast('Run a query first!', 'warning'); return; }

        const pinned = JSON.parse(localStorage.getItem('pinnedCharts') || '[]');
        const chartType = document.getElementById('chart-type').value;
        const xCol = document.getElementById('chart-x-axis').value;
        const yCol = document.getElementById('chart-y-axis').value;

        const pin = {
            id: Date.now(),
            title: this.currentQuery.natural_language.slice(0, 50),
            chartType, xCol, yCol,
            columns: this.currentQuery.columns,
            results: this.currentQuery.results,
            pinnedAt: new Date().toISOString()
        };

        if (pinned.some(p => p.title === pin.title)) {
            this.showToast('Already pinned!', 'warning');
            return;
        }

        pinned.push(pin);
        localStorage.setItem('pinnedCharts', JSON.stringify(pinned));
        this.showToast('Chart pinned to Dashboard!', 'success');
    }

    renderDashboard() {
        const pinned = JSON.parse(localStorage.getItem('pinnedCharts') || '[]');
        const container = document.getElementById('dashboard-content');
        if (!container) return;

        if (pinned.length === 0) {
            container.innerHTML = `
                <div class="empty-state" style="grid-column:1/-1;">
                    <div class="empty-state-icon">📌</div>
                    <div class="empty-state-text">No pinned charts yet</div>
                    <div class="empty-state-sub">Run a query and click "Pin to Dashboard"</div>
                </div>`;
            return;
        }

        container.innerHTML = pinned.map((pin, i) => `
            <div class="dashboard-card">
                <div class="dashboard-card-header">
                    <div class="dashboard-card-title">📌 ${this.escapeHtml(pin.title)}</div>
                    <button class="dashboard-card-unpin" onclick="app.unpinChart(${i})">×</button>
                </div>
                <canvas id="dashboard-chart-${pin.id}" height="200"></canvas>
            </div>
        `).join('');

        pinned.forEach(pin => {
            const canvas = document.getElementById(`dashboard-chart-${pin.id}`);
            if (!canvas) return;
            const labels = pin.results.map(r => String(r[pin.xCol] ?? ''));
            const data = pin.results.map(r => parseFloat(r[pin.yCol]) || 0);
            const colors = ['#4472C4','#E8455A','#28C864','#F5A623','#9B59B6'];
            new Chart(canvas, {
                type: pin.chartType,
                data: {
                    labels,
                    datasets: [{
                        label: pin.yCol,
                        data,
                        backgroundColor: pin.chartType === 'bar' ? colors[0] : colors.slice(0, data.length),
                        borderColor: pin.chartType === 'line' ? colors[0] : 'transparent',
                        borderWidth: pin.chartType === 'line' ? 2 : 0,
                        tension: 0.4,
                    }]
                },
                options: {
                    responsive: true,
                    plugins: { legend: { labels: { color: '#a0aec0' } } },
                    scales: pin.chartType === 'pie' || pin.chartType === 'doughnut' ? {} : {
                        x: { ticks: { color: '#a0aec0' }, grid: { color: '#2d3748' } },
                        y: { ticks: { color: '#a0aec0' }, grid: { color: '#2d3748' } }
                    }
                }
            });
        });
    }

    unpinChart(index) {
        const pinned = JSON.parse(localStorage.getItem('pinnedCharts') || '[]');
        pinned.splice(index, 1);
        localStorage.setItem('pinnedCharts', JSON.stringify(pinned));
        this.renderDashboard();
        this.showToast('Chart unpinned!', 'success');
    }

    // ── Charts ──────────────────────────────────────────────────────────────
    renderChart(result) {
        const chartSection = document.getElementById('chart-section');
        const columns = result.columns;
        const rows = result.results;

        const xSelect = document.getElementById('chart-x-axis');
        const ySelect = document.getElementById('chart-y-axis');
        xSelect.innerHTML = columns.map(col => `<option value="${col}">${col}</option>`).join('');
        ySelect.innerHTML = columns.map(col => `<option value="${col}">${col}</option>`).join('');

        const numericCol = columns.find(col => rows.some(r => !isNaN(parseFloat(r[col]))));
        if (numericCol) ySelect.value = numericCol;

        chartSection.classList.remove('hidden');
        this.updateChart(result);

        document.getElementById('chart-type').onchange = () => this.updateChart(result);
        document.getElementById('chart-x-axis').onchange = () => this.updateChart(result);
        document.getElementById('chart-y-axis').onchange = () => this.updateChart(result);
    }

    updateChart(result) {
        const chartType = document.getElementById('chart-type').value;
        const xCol = document.getElementById('chart-x-axis').value;
        const yCol = document.getElementById('chart-y-axis').value;
        const rows = result.results;

        const labels = rows.map(r => String(r[xCol] ?? ''));
        const data = rows.map(r => parseFloat(r[yCol]) || 0);
        const colors = [
            '#4472C4','#E8455A','#28C864','#F5A623','#9B59B6',
            '#1ABC9C','#E67E22','#3498DB','#E91E63','#00BCD4'
        ];

        const canvas = document.getElementById('results-chart');
        if (window._prismChart) window._prismChart.destroy();

        window._prismChart = new Chart(canvas, {
            type: chartType,
            data: {
                labels,
                datasets: [{
                    label: yCol,
                    data,
                    backgroundColor: chartType === 'bar' ? colors[0] : colors.slice(0, data.length),
                    borderColor: chartType === 'line' ? colors[0] : 'transparent',
                    borderWidth: chartType === 'line' ? 2 : 0,
                    fill: false,
                    tension: 0.4,
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { labels: { color: '#a0aec0' } } },
                scales: chartType === 'pie' || chartType === 'doughnut' ? {} : {
                    x: { ticks: { color: '#a0aec0' }, grid: { color: '#2d3748' } },
                    y: { ticks: { color: '#a0aec0' }, grid: { color: '#2d3748' } }
                }
            }
        });
    }

    getChartImage() {
        const canvas = document.getElementById('results-chart');
        if (!canvas) return null;
        try { return canvas.toDataURL('image/png'); }
        catch (e) { return null; }
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
            const res = await this.authFetch(`${API}/export`, { // ✅ auth
                method: 'POST',
                body: JSON.stringify({
                    query_id: this.currentQuery.query_id,
                    format: format,
                    filename: `query_export_${Date.now()}`,
                    chart_image: format === 'pdf' ? this.getChartImage() : null
                })
            });
            if (!res) return;
            const result = await res.json();

            if (result.success && result.filepath) {
                this.showToast(`✅ ${format.toUpperCase()} saved! Opening...`, 'success');
                if (window.api && window.api.openFile) {
                    window.api.openFile(result.filepath);
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

    // ── Query History (Exports view) ─────────────────────────────────────────
    async loadQueryHistory() {
        try {
            const res = await this.authFetch(`${API}/query/history?limit=50`); // ✅ auth
            if (!res) return;
            const result = await res.json();
            this.renderQueryHistory(result.history || []);
        } catch (err) {
            this.showToast('Failed to load query history', 'error');
        }
    }

    renderQueryHistory(history) {
        const container = document.getElementById('exports-list');
        if (!container) return;

        if (history.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📋</div>
                    <div class="empty-state-text">No query history yet</div>
                    <div class="empty-state-sub">Run some queries first!</div>
                </div>`;
            return;
        }

        container.innerHTML = `
            <div style="padding:20px;">
                <h3 style="color:var(--text-primary);margin-bottom:16px;font-size:15px;font-weight:600;">Query History</h3>
                ${history.map(q => `
                    <div class="history-card" onclick="app.rerunQuery('${this.escapeHtml(q.natural_language)}')">
                        <div class="history-card-meta">
                            <span class="history-card-time">🕓 ${new Date(q.timestamp).toLocaleString()}</span>
                            <span class="history-card-stats">
                                <span class="stat-badge">⏱ ${q.execution_time_ms?.toFixed(0)}ms</span>
                                <span class="stat-badge">📊 ${q.row_count} rows</span>
                                <span class="stat-badge" style="color:${q.success ? 'var(--success)' : 'var(--error)'}">
                                    ${q.success ? '✓ Success' : '✕ Failed'}
                                </span>
                            </span>
                        </div>
                        <div class="history-card-query">${this.escapeHtml(q.natural_language)}</div>
                        ${q.generated_sql ? `
                            <div style="margin-top:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-muted);background:var(--bg-elevated);padding:8px 10px;border-radius:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                                ${this.escapeHtml(q.generated_sql)}
                            </div>` : ''}
                    </div>
                `).join('')}
            </div>
        `;
    }

    // ── Schema ──────────────────────────────────────────────────────────────
    async loadSchema(forceRefresh = false) {
        const connectionId = document.getElementById('schema-connection').value;
        if (!connectionId) { this.showToast('Please select a connection', 'warning'); return; }
        try {
            const res = await this.authFetch( // ✅ auth
                `${API}/connections/${connectionId}/schema?force_refresh=${forceRefresh}`
            );
            if (!res) return;
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
            const res = await this.authFetch(`${API}/reports/summary`, { // ✅ auth
                method: 'POST',
                body: JSON.stringify({ connection_id: connectionId })
            });
            if (!res) return;
            const result = await res.json();
            if (result.error) { this.showToast('Failed to generate report', 'error'); return; }
            this.showToast('Summary report generated successfully', 'success');
        } catch (err) {
            this.showToast('Failed to generate report', 'error');
        }
    }

    // ── Alerts ──────────────────────────────────────────────────────────────
    async sendTestAlert() {
        const title   = document.getElementById('test-alert-title').value.trim();
        const message = document.getElementById('test-alert-message').value.trim();
        const channels = [];
        if (document.getElementById('channel-email').checked) channels.push('email');
        if (document.getElementById('channel-slack').checked) channels.push('slack');

        if (!title || !message) { this.showToast('Please fill in title and message', 'warning'); return; }
        if (channels.length === 0) { this.showToast('Please select at least one channel', 'warning'); return; }

        try {
            const res = await this.authFetch(`${API}/alerts/test`, { // ✅ auth
                method: 'POST',
                body: JSON.stringify({ title, message, channels })
            });
            if (!res) return;
            const result = await res.json();
            const hasSuccess = Object.values(result).some(v => v === true);
            if (hasSuccess) {
                this.showToast('Test alert sent!', 'success');
                this.addAlertHistory(title, message, channels, true);
            } else {
                this.showToast('Failed to send test alert', 'error');
            }
        } catch (err) {
            this.showToast('Failed to send test alert', 'error');
        }
    }

    createAlertRule() {
        const name      = document.getElementById('alert-name').value.trim();
        const connId    = document.getElementById('alert-connection').value;
        const query     = document.getElementById('alert-query').value.trim();
        const condition = document.getElementById('alert-condition').value;
        const threshold = document.getElementById('alert-threshold').value;
        const frequency = document.getElementById('alert-frequency').value;
        const channels  = [];
        if (document.getElementById('alert-channel-email').checked) channels.push('email');
        if (document.getElementById('alert-channel-slack').checked) channels.push('slack');

        if (!name)      { this.showToast('Please enter an alert name', 'warning'); return; }
        if (!connId)    { this.showToast('Please select a connection', 'warning'); return; }
        if (!query)     { this.showToast('Please enter a query to monitor', 'warning'); return; }
        if (!threshold) { this.showToast('Please enter a threshold value', 'warning'); return; }
        if (channels.length === 0) { this.showToast('Please select at least one channel', 'warning'); return; }

        const rules = JSON.parse(localStorage.getItem('alert_rules') || '[]');
        const rule = {
            id: Date.now(), name, connId, query, condition,
            threshold: parseFloat(threshold), channels,
            frequency: parseInt(frequency), active: true,
            createdAt: new Date().toLocaleString(), triggeredCount: 0
        };

        rules.push(rule);
        localStorage.setItem('alert_rules', JSON.stringify(rules));

        document.getElementById('alert-name').value = '';
        document.getElementById('alert-query').value = '';
        document.getElementById('alert-threshold').value = '';

        this.renderAlertRules();
        this.showToast(`Alert rule "${name}" created!`, 'success');
    }

    renderAlertRules() {
        const rules = JSON.parse(localStorage.getItem('alert_rules') || '[]');
        const container = document.getElementById('alert-rules-list');
        const countEl   = document.getElementById('alert-rules-count');
        if (!container) return;

        if (countEl) countEl.textContent = `${rules.length} rule${rules.length !== 1 ? 's' : ''}`;

        if (rules.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🔔</div>
                    <div class="empty-state-text">No alert rules yet</div>
                    <div class="empty-state-sub">Create one above to start monitoring your data</div>
                </div>`;
            return;
        }

        const conditionLabels = { less_than: '<', greater_than: '>', equals: '=', not_equals: '≠' };

        container.innerHTML = rules.map((rule, i) => `
            <div class="alert-rule-card ${rule.active ? 'active-rule' : 'paused-rule'}">
                <div class="alert-rule-dot ${rule.active ? 'active' : 'paused'}"></div>
                <div class="alert-rule-body">
                    <div class="alert-rule-name">${this.escapeHtml(rule.name)}</div>
                    <div class="alert-rule-query">"${this.escapeHtml(rule.query)}" ${conditionLabels[rule.condition]} ${rule.threshold}</div>
                    <div class="alert-rule-meta">
                        Every ${rule.frequency >= 60 ? rule.frequency/60 + 'h' : rule.frequency + 'min'}
                        · ${rule.channels.join(', ')}
                        · Triggered ${rule.triggeredCount}x
                    </div>
                </div>
                <div class="alert-rule-actions">
                    <button class="btn-secondary" onclick="app.toggleAlertRule(${i})">
                        ${rule.active ? '⏸ Pause' : '▶ Resume'}
                    </button>
                    <button class="btn-danger" onclick="app.deleteAlertRule(${i})">🗑 Delete</button>
                </div>
            </div>
        `).join('');
    }

    toggleAlertRule(index) {
        const rules = JSON.parse(localStorage.getItem('alert_rules') || '[]');
        rules[index].active = !rules[index].active;
        localStorage.setItem('alert_rules', JSON.stringify(rules));
        this.renderAlertRules();
        this.showToast(rules[index].active ? 'Alert resumed' : 'Alert paused', 'info');
    }

    deleteAlertRule(index) {
        if (!confirm('Delete this alert rule?')) return;
        const rules = JSON.parse(localStorage.getItem('alert_rules') || '[]');
        const name = rules[index].name;
        rules.splice(index, 1);
        localStorage.setItem('alert_rules', JSON.stringify(rules));
        this.renderAlertRules();
        this.showToast(`"${name}" deleted`, 'success');
    }

    addAlertHistory(title, message, channels, success) {
        const history = JSON.parse(localStorage.getItem('alert_history') || '[]');
        history.unshift({ title, message, channels, success, timestamp: new Date().toLocaleString() });
        if (history.length > 20) history.pop();
        localStorage.setItem('alert_history', JSON.stringify(history));
        this.renderAlertHistory();
    }

    renderAlertHistory() {
        const history = JSON.parse(localStorage.getItem('alert_history') || '[]');
        const container = document.getElementById('alert-history-list');
        if (!container) return;

        if (history.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📭</div>
                    <div class="empty-state-text">No alerts triggered yet</div>
                    <div class="empty-state-sub">Sent alerts will appear here</div>
                </div>`;
            return;
        }

        container.innerHTML = history.map(h => `
            <div class="alert-history-item">
                <span class="alert-history-icon">${h.success ? '✅' : '❌'}</span>
                <div class="alert-history-body">
                    <div class="alert-history-title">${this.escapeHtml(h.title)}</div>
                    <div class="alert-history-meta">${h.timestamp} · ${h.channels.join(', ')}</div>
                </div>
            </div>
        `).join('');
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