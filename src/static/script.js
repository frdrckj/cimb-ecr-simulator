class ECRSimulator {
    constructor() {
        this.settings = {};
        this.isConnected = false;
        this.transactionHistory = [];
        this.mode = 'native';
        this.initializeElements();
        this.bindEvents();
        this.loadSettings();
        this.updateStatus();
        this.fetchHistory();
    }

    initializeElements() {
        this.transactionTypeSelect = document.getElementById('transactionType');
        this.amountInput = document.getElementById('amount');
        this.additionalFields = document.getElementById('additionalFields');
        this.invoiceNoInput = document.getElementById('invoiceNo');
        this.requestArea = document.getElementById('requestArea');
        this.responseArea = document.getElementById('responseArea');
        this.sendBtn = document.getElementById('sendBtn');
        this.openBtn = document.getElementById('openBtn');
        this.communicationSelect = document.getElementById('communication');
        this.serialPortSelect = document.getElementById('serialPort');
        this.socketIpInput = document.getElementById('socketIp');
        this.socketPortInput = document.getElementById('socketPort');
        this.speedBaudSelect = document.getElementById('speedBaud');
        this.dataBitsInput = document.getElementById('dataBits');
        this.stopBitsSelect = document.getElementById('stopBits');
        this.paritySelect = document.getElementById('parity');
        this.enableRestApiCheck = document.getElementById('enableRestApi');
        this.enableSslCheck = document.getElementById('enableSsl');
        this.edcSerialNumberInput = document.getElementById('edcSerialNumber');
        this.saveSettingsBtn = document.getElementById('saveSettings');
        this.statusIndicator = document.getElementById('statusIndicator');
        this.historyContainer = document.getElementById('historyContainer');
    }

    bindEvents() {
        this.sendBtn.addEventListener('click', () => this.sendTransaction());
        this.openBtn.addEventListener('click', () => this.toggleConnection());
        this.saveSettingsBtn.addEventListener('click', () => this.saveSettings());
        this.transactionTypeSelect.addEventListener('change', () => {
            this.showAdditionalFields();
            this.updateRequest();
        });
        this.amountInput.addEventListener('input', () => this.updateRequest());
        this.amountInput.addEventListener('blur', () => this.formatAmount());
        this.invoiceNoInput.addEventListener('input', () => this.updateRequest());
    }

    showAdditionalFields() {
        const type = this.transactionTypeSelect.value;
        if (type === 'VOID' || type === 'REFUND' || type === 'REPRINT' || type === 'QRIS REFUND') {
            this.additionalFields.style.display = 'block';
        } else {
            this.additionalFields.style.display = 'none';
        }
    }

    async loadSettings() {
        try {
            const response = await fetch('/api/settings');
            if (response.ok) {
                this.settings = await response.json();
                this.populateSettingsForm();
                this.mode = this.settings.enable_rest_api ? 'rest' : 'native';
            }
        } catch (error) {
            console.error('Error loading settings:', error);
        }
    }

    populateSettingsForm() {
        this.communicationSelect.value = this.settings.communication || 'Serial';
        this.serialPortSelect.value = this.settings.serial_port || '';
        this.socketIpInput.value = this.settings.socket_ip || '127.0.0.1';
        this.socketPortInput.value = this.settings.socket_port || '9001';
        this.speedBaudSelect.value = this.settings.speed_baud || '9600';
        this.dataBitsInput.value = this.settings.data_bits || '8';
        this.stopBitsSelect.value = this.settings.stop_bits || '1';
        this.paritySelect.value = this.settings.parity || 'None';
        this.enableRestApiCheck.checked = this.settings.enable_rest_api || false;
        this.enableSslCheck.checked = this.settings.enable_ssl || false;
        this.edcSerialNumberInput.value = this.settings.edc_serial_number || '';
    }

    async saveSettings() {
        const settings = {
            communication: this.communicationSelect.value,
            serial_port: this.serialPortSelect.value,
            socket_ip: this.socketIpInput.value,
            socket_port: this.socketPortInput.value,
            speed_baud: this.speedBaudSelect.value,
            data_bits: this.dataBitsInput.value,
            stop_bits: this.stopBitsSelect.value,
            parity: this.paritySelect.value,
            enable_rest_api: this.enableRestApiCheck.checked,
            enable_ssl: this.enableSslCheck.checked,
            edc_serial_number: this.edcSerialNumberInput.value
        };
        try {
            const response = await fetch('/api/settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(settings)
            });
            if (response.ok) {
                this.settings = settings;
                this.mode = this.settings.enable_rest_api ? 'rest' : 'native';
                this.showNotification('Settings saved successfully', 'success');
                const modal = bootstrap.Modal.getInstance(document.getElementById('settingsModal'));
                modal.hide();
            } else {
                this.showNotification('Error saving settings', 'error');
            }
        } catch (error) {
            this.showNotification('Error saving settings', 'error');
        }
    }

    async updateRequest() {
        const transaction_type = this.transactionTypeSelect.value;
        const amount = this.amountInput.value || '0.00';
        const invoiceNo = this.invoiceNoInput.value || '';
        try {
            const response = await fetch('/api/build_request', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({transaction_type, amount, invoiceNo})
            });
            const result = await response.json();
            this.requestArea.value = result.request;
            this.requestType = result.type;
        } catch (error) {
            this.requestArea.value = 'Error generating request';
        }
    }

    formatAmount() {
        let value = this.amountInput.value.replace(/[^0-9.]/g, '');
        if (value && !isNaN(value)) {
            value = parseFloat(value).toFixed(2);
            this.amountInput.value = value;
        }
        this.updateRequest();
    }

    async sendTransaction() {
        const transaction_type = this.transactionTypeSelect.value;
        const amount = this.amountInput.value;
        if (!amount || parseFloat(amount) <= 0) {
            this.showNotification('Please enter a valid amount', 'error');
            return;
        }
        this.setLoading(true);
        try {
            if (this.mode === 'rest') {
                const username = 'VBF4C1MB';
                const password = 'VFI' + this.settings.edc_serial_number;
                const auth = btoa(username + ':' + password);
                const req_body = JSON.parse(this.requestArea.value);
                let res = await fetch('/api/transaction/cimb', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': 'Basic ' + auth
                    },
                    body: JSON.stringify(req_body)
                });
                if (!res.ok) {
                    const err = await res.text();
                    throw new Error(`Error: ${res.status} - ${err}`);
                }
                const {trxId} = await res.json();
                const startTime = Date.now();
                const poll = setInterval(async () => {
                    if (Date.now() - startTime > 60000) {
                        clearInterval(poll);
                        this.displayResponse({error: 'Polling timeout'}, 'error');
                        this.setLoading(false);
                        return;
                    }
                    res = await fetch('/api/result/cimb', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Basic ' + auth
                        },
                        body: JSON.stringify({trxId})
                    });
                    if (res.status === 503) return;
                    clearInterval(poll);
                    if (!res.ok) {
                        const err = await res.text();
                        this.displayResponse({error: `Error: ${res.status} - ${err}`}, 'error');
                        this.setLoading(false);
                        return;
                    }
                    const result = await res.json();
                    this.displayResponse(result, 'success');
                    this.fetchHistory();
                    this.setLoading(false);
                }, 1000);
            } else {
                const res = await fetch('/api/process', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        transaction_type,
                        amount,
                        invoiceNo: this.invoiceNoInput.value || null
                    })
                });
                const result = await res.json();
                if (!res.ok) {
                    throw new Error(result.error);
                }
                this.displayResponse(result, 'success');
                this.addToHistory(transaction_type, amount, result);
                this.setLoading(false);
            }
        } catch (error) {
            this.displayResponse({error: error.message}, 'error');
            this.setLoading(false);
        }
    }

    displayResponse(response, type) {
        let responseText;
        if (type === 'success') {
            if (this.requestType === 'json') {
                responseText = JSON.stringify(response, null, 2);
            } else {
                responseText = response.response_hex;
            }
            this.responseArea.className = 'form-control response-success';
        } else {
            responseText = `ERROR: ${response.error || 'Unknown error occurred'}`;
            this.responseArea.className = 'form-control response-error';
        }
        this.responseArea.value = responseText;
    }

    addToHistory(transactionType, amount, response) {
        const historyItem = {
            id: Date.now(),
            timestamp: new Date().toLocaleString(),
            transaction_type: transactionType,
            amount: amount,
            status: response.status || 'SUCCESS',
            transaction_id: response.trxId || 'N/A'
        };
        this.transactionHistory.unshift(historyItem);
        this.updateHistoryDisplay();
    }

    async fetchHistory() {
        if (this.mode !== 'rest') return;
        try {
            const response = await fetch('/api/history');
            if (response.ok) {
                this.transactionHistory = await response.json();
                this.updateHistoryDisplay();
            }
        } catch (error) {
            console.error('Error fetching history:', error);
        }
    }

    updateHistoryDisplay() {
        if (this.transactionHistory.length === 0) {
            this.historyContainer.innerHTML = '<div class="history-item"><small class="text-muted">No transactions yet</small></div>';
            return;
        }
        const historyHtml = this.transactionHistory.map(item => `
            <div class="history-item">
                <div class="transaction-info">${item.transaction_type} - ${item.amount}</div>
                <div class="transaction-details">
                    ${item.timestamp} | ${item.status} | ID: ${item.transaction_id}
                </div>
            </div>
        `).join('');
        this.historyContainer.innerHTML = historyHtml;
    }

    async toggleConnection() {
        this.showNotification(this.isConnected ? 'Disconnecting from ECR device...' : 'Attempting to connect...', 'info');
        try {
            const response = await fetch('/api/connect', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    settings: this.settings,
                    action: this.isConnected ? 'disconnect' : 'connect'
                })
            });
            const result = await response.json();
            if (response.ok) {
                this.isConnected = result.connected;
                this.showNotification(result.message || (result.connected ? 'Connected to ECR device' : 'Disconnected from ECR device'), result.connected ? 'success' : 'info');
            } else {
                this.isConnected = false;
                this.showNotification(result.error || 'Failed to connect to ECR device', 'error');
            }
        } catch (error) {
            this.isConnected = False;
            this.showNotification(`Connection failed: ${error.message}`, 'error');
        }
        this.updateStatus();
    }

    updateStatus() {
        const statusDot = this.statusIndicator.querySelector('.status-dot');
        const statusText = this.statusIndicator.querySelector('span:last-child');
        if (this.isConnected) {
            statusDot.className = 'status-dot online';
            statusText.textContent = 'ONLINE';
            this.openBtn.textContent = 'Close';
            this.openBtn.className = 'btn btn-warning';
        } else {
            statusDot.className = 'status-dot offline';
            statusText.textContent = 'OFFLINE';
            this.openBtn.textContent = 'Open';
            this.openBtn.className = 'btn btn-success';
        }
    }

    setLoading(loading) {
        this.sendBtn.disabled = loading;
        this.sendBtn.innerHTML = loading ? '<span class="spinner"></span> Processing...' : 'Send';
    }

    showNotification(message, type) {
        const toast = document.createElement('div');
        toast.className = `alert alert-${type === 'success' ? 'success' : type === 'error' ? 'danger' : 'info'} position-fixed`;
        toast.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        toast.innerHTML = `${message} <button type="button" class="btn-close" onclick="this.parentElement.remove()"></button>`;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new ECRSimulator();
});
