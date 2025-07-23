/**
 * CSV Merger - Main Application Logic
 * Alpine.js application with modular component support
 */

// Global error handler to catch Alpine.js issues
window.addEventListener('error', function(event) {
    console.error('Global error caught:', event.error);
});

// Ensure Socket.IO is available
if (typeof io === 'undefined') {
    console.error('Socket.IO not loaded');
    window.io = function() {
        console.warn('Socket.IO not available, returning mock');
        return {
            on: function() {},
            emit: function() {},
            connected: false,
            disconnect: function() {}
        };
    };
}

// Main Alpine.js application function
function csvMergerApp() {
    return {
        // Authentication & Session
        isAuthenticated: false,
        isLoggedIn: false,
        currentUserId: '',
        userName: '',
        sessionId: null,
        session: { id: null, user_id: null },
        isLoading: false,
        
        // Connection Status
        socketStatus: 'disconnected',
        socketStatusText: 'Disconnected',
        webSocketState: 'Disconnected',
        socket: null,
        healthStatus: { status: 'unknown', message: 'Checking...' },
        
        // File Management
        uploadedFiles: [],
        totalRecordCount: 0,
        uploadProgress: { show: false, percentage: 0, message: '' },
        uploadErrors: [],
        
        // Job Configuration
        tableType: 'people',
        processingMode: 'download',
        webhookUrl: '',
        webhookRateLimit: 10,
        webhookLimit: 0,
        processingStarting: false,
        
        // Status Indicators
        webhookStatus: { tested: false, success: false, message: '' },
        n8nStatus: { tested: false, success: false, message: '' },
        
        // Current Job & Progress
        currentJob: null,
        n8nMappingData: null,
        jobs: [],
        jobHistory: [], // Add missing jobHistory property
        
        // UI State
        showJobHistory: false,
        showMappingDetails: false,
        showDebugInfo: false,
        completedJobs: [],
        
        // Notifications
        notifications: [],
        notificationId: 0,

        // Initialization
        init() {
            console.log('🚀 CSV Merger App Initializing...');
            try {
                this.checkStoredLogin();
                this.checkSystemHealth();
                this.loadStoredSettings();
            } catch (error) {
                console.error('Initialization error:', error);
                this.showNotification('App initialization failed', 'error');
            }
        },

        // =========================
        // AUTHENTICATION
        // =========================

        checkStoredLogin() {
            try {
                const storedUserId = localStorage.getItem('csv_merger_user_id');
                if (storedUserId) {
                    console.log('👤 Found stored user ID:', storedUserId);
                    this.userName = storedUserId;
                    // Auto-login with stored credentials
                    this.autoLogin(storedUserId);
                }
            } catch (error) {
                console.error('Error checking stored login:', error);
            }
        },

        autoLogin(userId) {
            console.log('🔄 Auto-logging in user:', userId);
            this.isLoading = true;
            fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    this.isLoggedIn = true;
                    this.isAuthenticated = true;
                    this.currentUserId = data.user_id;
                    this.session.user_id = data.user_id;
                    this.session.id = data.session_id;
                    console.log('✅ Auto-login successful for:', data.user_id);
                    
                    // Connect WebSocket after auto-login
                    setTimeout(() => {
                        this.connectWebSocket();
                    }, 500);
                } else {
                    console.log('❌ Auto-login failed, clearing stored credentials');
                    localStorage.removeItem('csv_merger_user_id');
                }
            })
            .catch(err => {
                console.error('Auto-login error:', err);
                localStorage.removeItem('csv_merger_user_id');
            })
            .finally(() => {
                this.isLoading = false;
            });
        },

        login() {
            if (!this.userName || this.userName.trim() === '') {
                this.showNotification('Please enter a user name.', 'error');
                return;
            }
            this.isLoading = true;
            fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: this.userName.trim() })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    this.isLoggedIn = true;
                    this.isAuthenticated = true; // For backward compatibility
                    this.currentUserId = data.user_id;
                    this.session.user_id = data.user_id;
                    this.session.id = data.session_id;
                    
                    // Store in localStorage for persistence
                    localStorage.setItem('csv_merger_user_id', data.user_id);
                    
                    this.showNotification(`Logged in as ${data.user_id}.`, 'success');
                    
                    // Wait a moment for session to be established, then connect WebSocket
                    setTimeout(() => {
                        this.connectWebSocket();
                    }, 500);
                } else {
                    this.showNotification(`Login failed: ${data.error}`, 'error');
                }
            })
            .catch(err => {
                this.showNotification('An error occurred during login.', 'error');
                console.error('Login error:', err);
            })
            .finally(() => {
                this.isLoading = false;
            });
        },

        logout() {
            this.isLoading = true;
            fetch('/api/logout', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    this.isLoggedIn = false;
                    this.isAuthenticated = false;
                    this.currentUserId = '';
                    this.userName = '';
                    this.session.user_id = null;
                    this.session.id = null;
                    this.jobs = [];
                    this.completedJobs = [];
                    this.jobHistory = [];
                    
                    // Clear localStorage
                    localStorage.removeItem('csv_merger_user_id');
                    
                    if (this.socket) {
                        this.socket.disconnect();
                    }
                    this.showNotification('Logged out successfully.', 'success');
                } else {
                    this.showNotification('Logout failed.', 'error');
                }
            })
            .catch(err => {
                this.showNotification('An error occurred during logout.', 'error');
                console.error('Logout error:', err);
            })
            .finally(() => {
                this.isLoading = false;
            });
        },

        // =========================
        // WEBSOCKET CONNECTION
        // =========================

        connectWebSocket() {
            if (this.socket && this.socket.connected) {
                console.log('WebSocket already connected.');
                return;
            }
            
            console.log('🔌 Connecting to WebSocket...');
            this.socketStatus = 'connecting';
            this.socketStatusText = 'Connecting...';
            
            try {
                this.socket = io({
                    transports: ['websocket'],
                    reconnectionAttempts: 5,
                    reconnectionDelay: 1000,
                });

                this.socket.on('connect', () => {
                    console.log('✅ WebSocket connected:', this.socket.id);
                    this.socketStatus = 'connected';
                    this.socketStatusText = 'Connected';
                    this.webSocketState = 'Connected';
                    // Request session jobs after connection
                    this.socket.emit('get_session_jobs');
                });

                this.socket.on('connected', (data) => {
                    console.log('🔗 Connection confirmed by server:', data);
                    this.session.id = data.session_id;
                    this.session.user_id = data.user_id;
                });

                this.socket.on('connection_status', (data) => {
                    console.log('📊 Connection status from server:', data);
                    if (data.authenticated) {
                        console.log('✅ WebSocket authenticated successfully');
                        this.session.id = data.session_id;
                        this.session.user_id = data.user_id;
                    } else {
                        console.log('⚠️ WebSocket not authenticated:', data.message);
                    }
                });

                this.socket.on('disconnect', (reason) => {
                    console.log('❌ WebSocket disconnected. Reason:', reason);
                    this.socketStatus = 'disconnected';
                    this.socketStatusText = 'Disconnected';
                    this.webSocketState = 'Disconnected';
                });

                this.socket.on('connect_error', (error) => {
                    console.error('❌ WebSocket connection error:', error);
                    this.socketStatus = 'error';
                    this.socketStatusText = 'Connection Error';
                    this.webSocketState = 'Error';
                });

                this.socket.on('reconnect', (attemptNumber) => {
                    console.log('🔄 WebSocket reconnected after', attemptNumber, 'attempts');
                    this.socketStatus = 'connected';
                    this.socketStatusText = 'Reconnected';
                    this.webSocketState = 'Connected';
                    // Request session jobs after reconnection
                    this.socket.emit('get_session_jobs');
                });

                this.socket.on('reconnect_attempt', (attemptNumber) => {
                    console.log('🔄 WebSocket reconnection attempt', attemptNumber);
                    this.socketStatus = 'reconnecting';
                    this.socketStatusText = 'Reconnecting...';
                    this.webSocketState = 'Reconnecting...';
                });

                this.socket.on('reconnect_error', (error) => {
                    console.error('❌ WebSocket reconnection error:', error);
                    this.socketStatus = 'error';
                    this.socketStatusText = 'Reconnection Failed';
                    this.webSocketState = 'Error';
                });

                this.socket.on('reconnect_failed', () => {
                    console.error('❌ WebSocket reconnection failed permanently');
                    this.socketStatus = 'failed';
                    this.socketStatusText = 'Connection Failed';
                    this.webSocketState = 'Failed';
                });

                this.socket.on('error', (error) => {
                    console.error('❌ WebSocket error:', error);
                    this.socketStatus = 'error';
                    this.socketStatusText = 'Error';
                    this.webSocketState = 'Error';
                });

                this.socket.on('job_progress', (data) => {
                    console.log('📊 Job Progress:', data);
                    this.handleJobProgress(data);
                });

                this.socket.on('job_status_change', (data) => {
                    console.log('🔄 Job Status Change:', data);
                    this.handleJobStatusChange(data);
                });

                this.socket.on('session_jobs', (data) => {
                    console.log('📋 Session Jobs Received:', data);
                    this.handleSessionJobs(data);
                });
            } catch (error) {
                console.error('WebSocket setup error:', error);
                this.socketStatus = 'error';
                this.socketStatusText = 'Setup Error';
            }
        },

        // =========================
        // PROGRESS TRACKING
        // =========================

        handleJobProgress(data) {
            if (!this.currentJob || this.currentJob.job_id !== data.job_id) return;
            
            // Update progress
            if (data.percentage !== undefined) {
                this.currentJob.progress.percentage = data.percentage;
            }
            
            if (data.message) {
                this.currentJob.progress.message = data.message;
            }
            
            if (data.stage) {
                this.currentJob.progress.stage = data.stage;
            }

            // Update statistics
            if (data.stats) {
                this.currentJob.progress.stats = data.stats;
            }

            // Update webhook statistics
            if (data.webhook_stats) {
                this.currentJob.progress.webhook_stats = data.webhook_stats;
            }

            // Handle n8n mapping data
            if (data.n8n_response) {
                this.n8nMappingData = data.n8n_response;
                console.log('🤖 n8n Mapping Data Received:', this.n8nMappingData);
            }
        },

        handleJobStatusChange(data) {
            if (!this.currentJob || this.currentJob.job_id !== data.job_id) return;
            
            this.currentJob.status = data.status;
            
            if (data.status === 'completed') {
                this.currentJob.progress.percentage = 100;
                this.currentJob.progress.message = 'Processing completed successfully!';
                this.addNotification('Job completed successfully!', 'success');
                
                // Add to completed jobs
                this.loadJobHistory();
            } else if (data.status === 'failed') {
                this.currentJob.error = data.error || 'Processing failed';
                this.addNotification('Job failed: ' + this.currentJob.error, 'error');
            }
        },

        // =========================
        // PHASE STATUS MANAGEMENT
        // =========================

        getPhaseStatus(phase) {
            if (!this.currentJob?.progress) return 'pending';
            
            const currentStage = this.currentJob.progress.stage;
            const percentage = this.currentJob.progress.percentage || 0;
            
            // Phase completion logic based on current stage and percentage
            switch (phase) {
                case 'n8n_mapping':
                    if (this.n8nMappingData) return 'completed';
                    if (currentStage === 'n8n_mapping') return 'processing';
                    return 'pending';
                    
                case 'phase1':
                    if (percentage >= 30 || currentStage === 'phase2' || currentStage === 'phase3') return 'completed';
                    if (currentStage === 'phase1') return 'processing';
                    return percentage >= 10 ? 'pending' : 'pending';
                    
                case 'phase2':
                    if (percentage >= 60 || currentStage === 'phase3') return 'completed';
                    if (currentStage === 'phase2') return 'processing';
                    return percentage >= 30 ? 'pending' : 'pending';
                    
                case 'phase3':
                    if (percentage >= 90 || currentStage === 'webhook_delivery' || this.currentJob.status === 'completed') return 'completed';
                    if (currentStage === 'phase3') return 'processing';
                    return percentage >= 60 ? 'pending' : 'pending';
                    
                case 'webhook_delivery':
                    if (this.currentJob.status === 'completed' && this.currentJob.processing_mode === 'webhook') return 'completed';
                    if (currentStage === 'webhook_delivery') return 'processing';
                    return this.currentJob.processing_mode === 'webhook' && percentage >= 90 ? 'pending' : 'pending';
                    
                default:
                    return 'pending';
            }
        },

        // =========================
        // COLUMN MAPPING FUNCTIONS
        // =========================

        getTotalMappedColumns() {
            if (!this.n8nMappingData?.mapped_files) return 0;
            return this.n8nMappingData.mapped_files.reduce((total, file) => {
                return total + Object.keys(file.mapped_headers || {}).length;
            }, 0);
        },

        getPrimaryMappings() {
            if (!this.n8nMappingData?.mapped_files) return 0;
            return this.n8nMappingData.mapped_files.reduce((total, file) => {
                return total + Object.values(file.mapped_headers || {}).filter(mapping => 
                    mapping?.primary || (typeof mapping === 'string')
                ).length;
            }, 0);
        },

        getSecondaryMappings() {
            if (!this.n8nMappingData?.mapped_files) return 0;
            return this.n8nMappingData.mapped_files.reduce((total, file) => {
                return total + Object.values(file.mapped_headers || {}).filter(mapping => 
                    mapping?.secondary
                ).length;
            }, 0);
        },

        getTertiaryMappings() {
            if (!this.n8nMappingData?.mapped_files) return 0;
            return this.n8nMappingData.mapped_files.reduce((total, file) => {
                return total + Object.values(file.mapped_headers || {}).filter(mapping => 
                    mapping?.tertiary
                ).length;
            }, 0);
        },

        getStandardFieldsCoverage() {
            const standardFields = [
                'First Name', 'Last Name', 'Work Email', 'Personal Email', 'Job Title',
                'Company Name', 'Company Domain', 'LinkedIn Profile', 'Phone Number'
            ];
            
            const mappedFields = new Set();
            if (this.n8nMappingData?.mapped_files) {
                this.n8nMappingData.mapped_files.forEach(file => {
                    Object.values(file.mapped_headers || {}).forEach(mapping => {
                        if (mapping?.primary) mappedFields.add(mapping.primary);
                        if (mapping?.secondary) mappedFields.add(mapping.secondary);
                        if (mapping?.tertiary) mappedFields.add(mapping.tertiary);
                        if (typeof mapping === 'string') mappedFields.add(mapping);
                    });
                });
            }
            
            return standardFields.map(field => ({
                name: field,
                mapped: mappedFields.has(field)
            }));
        },

        toggleFileDetails(index) {
            if (this.n8nMappingData?.mapped_files?.[index]) {
                if (this.n8nMappingData.mapped_files[index].showDetails === undefined) {
                    this.n8nMappingData.mapped_files[index].showDetails = true;
                } else {
                    this.n8nMappingData.mapped_files[index].showDetails = 
                        !this.n8nMappingData.mapped_files[index].showDetails;
                }
            }
        },

        // =========================
        // FILE UPLOAD FUNCTIONS
        // =========================

        handleDrop(event) {
            const files = Array.from(event.dataTransfer.files);
            this.processFiles(files);
        },

        handleFileSelect(event) {
            const files = Array.from(event.target.files);
            this.processFiles(files);
            
            // Clear the file input so the same files can be selected again
            event.target.value = '';
        },

        processFiles(files) {
            this.uploadErrors = [];
            const validFiles = [];

            // Validate files
            files.forEach(file => {
                if (!file.name.toLowerCase().endsWith('.csv')) {
                    this.uploadErrors.push(`${file.name}: Not a CSV file`);
                    return;
                }

                if (file.size > 20 * 1024 * 1024) { // 20MB
                    this.uploadErrors.push(`${file.name}: File too large (max 20MB)`);
                    return;
                }

                // Check if file already exists (by name and size)
                const isDuplicate = this.uploadedFiles.some(existingFile => 
                    existingFile.filename === file.name && existingFile.size === file.size
                );
                
                if (isDuplicate) {
                    this.uploadErrors.push(`${file.name}: File already uploaded`);
                    return;
                }

                if (this.uploadedFiles.length + validFiles.length >= 10) {
                    this.uploadErrors.push(`Maximum 10 files allowed`);
                    return;
                }

                validFiles.push(file);
            });

            if (validFiles.length > 0) {
                this.uploadFiles(validFiles);
            } else if (this.uploadErrors.length > 0) {
                // Show errors if no valid files but there are errors
                this.uploadErrors.forEach(error => {
                    this.addNotification(error, 'error');
                });
            }
        },

        uploadFiles(files) {
            if (!files || files.length === 0) return;
            
            this.uploadProgress.show = true;
            this.uploadProgress.percentage = 0;
            this.uploadProgress.message = 'Starting upload...';
            
            const formData = new FormData();
            
            // Add files to form data and count records
            let processedFiles = 0;
            const totalFiles = files.length;
            let totalRecords = 0;
            const fileRecordCounts = []; // Store individual file record counts
            
            const processNextFile = (index) => {
                if (index >= files.length) {
                    // All files processed, now upload
                    this.uploadProgress.message = 'Uploading files...';
                    this.doUpload(formData, totalRecords, fileRecordCounts);
                    return;
                }
                
                const file = files[index];
                formData.append('files', file);
                
                this.uploadProgress.message = `Counting records in ${file.name}...`;
                this.uploadProgress.percentage = Math.round((index / totalFiles) * 50); // First 50% for counting
                
                // Count records in this file
                this.countRecordsInFile(file).then(recordCount => {
                    totalRecords += recordCount;
                    fileRecordCounts.push({
                        filename: file.name,
                        size: file.size,
                        recordCount: recordCount
                    });
                    processedFiles++;
                    console.log(`File ${file.name}: ${recordCount} records (total so far: ${totalRecords})`);
                    
                    // Process next file
                    processNextFile(index + 1);
                }).catch(error => {
                    console.error(`Error counting records in ${file.name}:`, error);
                    // Continue with next file even if counting fails, but store 0 count
                    fileRecordCounts.push({
                        filename: file.name,
                        size: file.size,
                        recordCount: 0
                    });
                    processedFiles++;
                    processNextFile(index + 1);
                });
            };
            
            // Start processing files
            processNextFile(0);
        },

        countRecordsInFile(file) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                
                reader.onload = function(e) {
                    try {
                        const text = e.target.result;
                        
                        // Handle different line endings and count properly
                        const recordCount = this.countCSVRecords(text);
                        
                        resolve(recordCount);
                    } catch (error) {
                        reject(error);
                    }
                }.bind(this);
                
                reader.onerror = function(error) {
                    reject(error);
                };
                
                reader.readAsText(file);
            });
        },

        // =========================
        // CSV UTILITIES
        // =========================

        countCSVRecords(csvText) {
            if (!csvText || csvText.trim().length === 0) {
                return 0;
            }

            // Normalize line endings to \n
            const normalizedText = csvText.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
            
            let recordCount = 0;
            let inQuotes = false;
            let currentChar = '';
            let prevChar = '';
            
            // Parse character by character to handle quoted fields with newlines
            for (let i = 0; i < normalizedText.length; i++) {
                currentChar = normalizedText[i];
                
                // Handle quotes
                if (currentChar === '"') {
                    // Check if it's an escaped quote (double quote)
                    if (i + 1 < normalizedText.length && normalizedText[i + 1] === '"') {
                        // Skip the next quote as it's escaped
                        i++;
                        continue;
                    } else {
                        // Toggle quote state
                        inQuotes = !inQuotes;
                    }
                }
                
                // Count newlines only when not inside quotes
                if (currentChar === '\n' && !inQuotes) {
                    recordCount++;
                }
                
                prevChar = currentChar;
            }
            
            // If the file doesn't end with a newline, add 1 more record
            if (normalizedText.length > 0 && !normalizedText.endsWith('\n')) {
                recordCount++;
            }
            
            // Subtract 1 for header row, but ensure we don't go below 0
            const dataRecords = Math.max(0, recordCount - 1);
            
            console.log(`CSV parsing: ${recordCount} total lines, ${dataRecords} data records (excluding header)`);
            return dataRecords;
        },

        doUpload(formData, recordCount, fileRecordCounts) {
            this.uploadProgress.percentage = 50;
            this.uploadProgress.message = 'Uploading to server...';
            
            fetch('/api/upload', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                this.uploadProgress.show = false;
                
                if (data.success) {
                    // Append new files to existing ones instead of replacing
                    const newFiles = data.files || [];
                    
                    console.log('Server returned files:', newFiles);
                    console.log('Frontend record counts:', fileRecordCounts);
                    
                    // Add record counts to the file data
                    const newFilesWithRecords = newFiles.map(file => {
                        // Try to match by filename first, then by size as backup
                        let recordInfo = fileRecordCounts.find(rc => 
                            rc.filename === file.filename
                        );
                        
                        // If no exact filename match, try matching by original filename or size
                        if (!recordInfo) {
                            recordInfo = fileRecordCounts.find(rc => 
                                file.filename.includes(rc.filename.split('.')[0]) || 
                                rc.size === file.size
                            );
                        }
                        
                        const recordCount = recordInfo ? recordInfo.recordCount : 0;
                        console.log(`File ${file.filename}: matched record count ${recordCount}`);
                        
                        return {
                            ...file,
                            recordCount: recordCount
                        };
                    });
                    
                    this.uploadedFiles = [...this.uploadedFiles, ...newFilesWithRecords];
                    
                    // Add new record count to total
                    this.totalRecordCount += recordCount;
                    
                    this.uploadProgress.percentage = 100;
                    this.addNotification(`Successfully uploaded ${newFiles.length} new files. Total: ${this.uploadedFiles.length} files with ${this.totalRecordCount} total records`, 'success');
                } else {
                    this.addNotification(data.error || 'Upload failed', 'error');
                }
            })
            .catch(error => {
                this.uploadProgress.show = false;
                this.addNotification('Upload failed: ' + error.message, 'error');
            });
        },

        startNewJob() {
            // Reset all job-related state
            this.currentJob = null;
            this.n8nMappingData = null;
            this.showJobHistory = false;
            this.totalRecordCount = 0;
            
            // Clear files both frontend and backend
            this.clearFiles();
        },

        clearFiles() {
            // Clear frontend files
            this.uploadedFiles = [];
            this.totalRecordCount = 0;
            
            // Clear backend session files
            fetch('/api/session/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    this.addNotification('All files cleared from session', 'success');
                } else {
                    this.addNotification('Failed to clear server files: ' + (data.error || 'Unknown error'), 'warning');
                }
            })
            .catch(error => {
                console.error('Error clearing session:', error);
                this.addNotification('Error clearing server files', 'warning');
            });
        },

        removeFile(index) {
            // Get the file being removed to subtract its record count
            const fileToRemove = this.uploadedFiles[index];
            if (fileToRemove && fileToRemove.recordCount) {
                this.totalRecordCount -= fileToRemove.recordCount;
            }
            
            this.uploadedFiles.splice(index, 1);
        },

        resetSession() {
            this.uploadedFiles = [];
            this.currentJob = null;
            this.n8nMappingData = null;
            this.showJobHistory = false;
            this.totalRecordCount = 0;
            this.addNotification('Session reset', 'info');
        },

        // =========================
        // JOB CONFIGURATION FUNCTIONS
        // =========================

        canStartProcessing() {
            return this.uploadedFiles.length > 0 && 
                   this.isAuthenticated && 
                   (this.processingMode === 'download' || 
                    (this.processingMode === 'webhook' && this.webhookUrl)) &&
                   !this.processingStarting;
        },

        testWebhook() {
            if (!this.webhookUrl) return;
            
            this.webhookStatus = { tested: true, success: false, message: 'Testing...' };
            
            fetch('/api/webhook/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ webhook_url: this.webhookUrl })
            })
            .then(response => response.json())
            .then(data => {
                this.webhookStatus = {
                    tested: true,
                    success: data.success,
                    message: data.success ? 
                        `✓ Connected (${data.response_time_ms}ms)` : 
                        `✗ ${data.error}`
                };
            })
            .catch(error => {
                this.webhookStatus = {
                    tested: true,
                    success: false,
                    message: `✗ Test failed: ${error.message}`
                };
            });
        },

        testN8nConnection() {
            this.n8nStatus = { tested: true, success: false, message: 'Testing...' };
            
            fetch('/api/webhook/test-n8n', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(response => response.json())
            .then(data => {
                this.n8nStatus = {
                    tested: true,
                    success: data.success,
                    message: data.success ? 
                        '✓ n8n AI mapping system is accessible' : 
                        `✗ ${data.error}`
                };
            })
            .catch(error => {
                this.n8nStatus = {
                    tested: true,
                    success: false,
                    message: `✗ Connection failed: ${error.message}`
                };
            });
        },

        startProcessing() {
            if (!this.canStartProcessing()) return;
            
            this.processingStarting = true;
            
            const jobData = {
                user_id: this.currentUserId,
                session_id: this.sessionId,
                table_type: this.tableType,
                processing_mode: this.processingMode,
                webhook_url: this.processingMode === 'webhook' ? this.webhookUrl : null,
                webhook_rate_limit: this.webhookRateLimit,
                webhook_limit: this.webhookLimit
            };
            
            fetch('/api/jobs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(jobData)
            })
            .then(response => response.json())
            .then(data => {
                this.processingStarting = false;
                console.log('✅ Received response from /api/jobs:', JSON.stringify(data, null, 2));
                
                if (data.success) {
                    // Handle both synchronous (immediate completion) and asynchronous (queued) jobs
                    if (data.mode === 'synchronous' || data.status?.status === 'completed') {
                        console.log('🔄 Job completed synchronously. Updating UI with final state.');
                        // Job completed synchronously, use the final status from the response
                        this.currentJob = {
                            job_id: data.job_id,
                            status: data.status.status,
                            processing_mode: this.processingMode,
                            progress: {
                                percentage: 100,
                                message: data.status.message || 'Processing completed successfully!',
                                stage: 'completed',
                                result_path: data.status.result_path,
                                stats: data.status.stats || {}
                            }
                        };
                        
                        // Set n8n mapping data
                        if (data.status.n8n_response) {
                            this.n8nMappingData = data.status.n8n_response;
                            console.log('🤖 n8n Mapping Data successfully set from sync response:', this.n8nMappingData);
                        } else {
                            console.warn('⚠️ n8n mapping data was not found in the synchronous response.');
                        }

                        this.addNotification('Job completed successfully!', 'success');
                        
                        // Load job history but don't let it crash the UI
                        try {
                            this.loadJobHistory();
                        } catch (error) {
                            console.warn('⚠️ Failed to load job history, but job completed successfully:', error);
                        }
                    } else {
                        console.log('⏳ Job queued for asynchronous processing. Waiting for WebSocket updates.');
                        // Job was queued, wait for WebSocket updates
                        this.currentJob = {
                            job_id: data.job_id,
                            status: data.status?.status || 'processing',
                            processing_mode: this.processingMode,
                            progress: {
                                percentage: 0,
                                message: 'Starting processing...',
                                stage: 'setup'
                            }
                        };
                        
                        // Join job for real-time updates
                        if (this.socket) {
                            this.socket.emit('join_job', { job_id: data.job_id });
                            console.log('🔌 Emitted "join_job" for job:', data.job_id);
                        }
                        this.addNotification('Processing started successfully!', 'success');
                    }
                } else {
                    console.error('❌ Failed to start processing job:', data.error);
                    this.addNotification(data.error || 'Failed to start processing', 'error');
                }
            })
            .catch(error => {
                this.processingStarting = false;
                this.addNotification('Failed to start processing: ' + error.message, 'error');
            });
        },

        // =========================
        // JOB MANAGEMENT
        // =========================

        cancelJob() {
            if (!this.currentJob) return;
            
            fetch(`/api/jobs/${this.currentJob.job_id}/cancel`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    this.currentJob = null;
                    this.n8nMappingData = null;
                    this.addNotification('Job cancelled', 'info');
                } else {
                    this.addNotification('Failed to cancel job', 'error');
                }
            })
            .catch(error => {
                this.addNotification('Error cancelling job: ' + error.message, 'error');
            });
        },

        downloadJob(jobId) {
            if (!jobId) {
                this.addNotification('No job ID provided for download', 'error');
                return;
            }
            window.location.href = `/api/jobs/${jobId}/download`;
        },

        // =========================
        // JOB HISTORY
        // =========================

        handleSessionJobs(data) {
            console.log('🔍 Processing session jobs data:', data);
            if (data && data.jobs) {
                this.jobHistory = data.jobs;
                console.log(`📋 Loaded ${this.jobHistory.length} jobs into history`);
                
                // If we just completed a job and there's no current job shown, 
                // and we have a recent completed job, show it
                if (!this.currentJob && this.jobHistory.length > 0) {
                    const latestJob = this.jobHistory[0]; // Jobs are sorted newest first
                    if (latestJob.status === 'completed') {
                        console.log('🎯 Auto-selecting latest completed job:', latestJob.job_id);
                        this.selectHistoryJob(latestJob);
                    }
                }
            } else {
                console.warn('⚠️ No jobs found in session jobs response');
                this.jobHistory = [];
            }
        },

        loadJobHistory() {
            if (!this.socket) return;
            this.socket.emit('get_session_jobs');
        },

        selectHistoryJob(job) {
            // Allow viewing completed job details
            this.currentJob = {
                ...job,
                progress: {
                    percentage: 100,
                    message: 'Completed',
                    stage: 'completed'
                }
            };
            this.showJobHistory = false;
        },

        // =========================
        // UTILITY FUNCTIONS
        // =========================

        checkSystemHealth() {
            fetch('/api/health')
                .then(response => response.json())
                .then(data => {
                    this.healthStatus = {
                        status: data.status,
                        message: data.status === 'healthy' ? 'System Healthy' : 'System Issues'
                    };
                })
                .catch(error => {
                    this.healthStatus = {
                        status: 'error',
                        message: 'Health Check Failed'
                    };
                });
        },

        loadStoredSettings() {
            try {
                const settings = localStorage.getItem('csv_merger_settings');
                if (settings) {
                    const parsed = JSON.parse(settings);
                    this.tableType = parsed.tableType || 'people';
                    this.processingMode = parsed.processingMode || 'download';
                    this.webhookRateLimit = parsed.webhookRateLimit || 10;
                }
            } catch (error) {
                console.warn('Failed to load stored settings:', error);
            }
        },

        saveSettings() {
            try {
                const settings = {
                    tableType: this.tableType,
                    processingMode: this.processingMode,
                    webhookRateLimit: this.webhookRateLimit
                };
                localStorage.setItem('csv_merger_settings', JSON.stringify(settings));
            } catch (error) {
                console.warn('Failed to save settings:', error);
            }
        },

        // =========================
        // NOTIFICATIONS
        // =========================

        addNotification(message, type = 'info') {
            const notification = {
                id: ++this.notificationId,
                message,
                type,
                visible: true
            };
            
            this.notifications.push(notification);
            console.log(`📢 Notification [${type}]:`, message);
            
            // Auto-remove after 5 seconds
            setTimeout(() => {
                this.removeNotification(notification.id);
            }, 5000);
        },

        showNotification(message, type = 'info') {
            // Alias for addNotification to maintain compatibility
            this.addNotification(message, type);
        },

        removeNotification(id) {
            const index = this.notifications.findIndex(n => n.id === id);
            if (index > -1) {
                this.notifications[index].visible = false;
                setTimeout(() => {
                    this.notifications.splice(index, 1);
                }, 300);
            }
        },

        // =========================
        // HELPER FUNCTIONS
        // =========================

        formatDate(dateString) {
            if (!dateString) return '';
            return new Date(dateString).toLocaleString();
        },

        formatFileSize(bytes) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
        },

        getTotalFileSize() {
            return this.uploadedFiles.reduce((total, file) => total + (file.size || 0), 0);
        },

        getEstimatedRecords() {
            return this.totalRecordCount || 0;
        },

        getJobStatusColor(status) {
            const colors = {
                'completed': 'text-green-600',
                'processing': 'text-blue-600',
                'failed': 'text-red-600',
                'cancelled': 'text-gray-600'
            };
            return colors[status] || 'text-gray-600';
        },

        // =========================
        // FILE MANAGEMENT FUNCTIONS  
        // =========================
        
        async refreshRecordCounts() {
            if (this.uploadedFiles.length === 0) return;
            
            // Check if any files are missing record counts
            const filesNeedingCounts = this.uploadedFiles.filter(file => 
                file.recordCount === undefined || file.recordCount === 0
            );
            
            if (filesNeedingCounts.length === 0) {
                this.addNotification('All files already have record counts', 'info');
                return;
            }
            
            this.addNotification(`Files uploaded before record counting was enabled need to be re-uploaded to get accurate counts. Please clear and re-upload your files.`, 'warning');
        }
    };
}

// Make the function globally available
window.csvMergerApp = csvMergerApp;

// Initialize Alpine.js when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM Content Loaded - csvMergerApp available:', typeof csvMergerApp === 'function');
    
    // Wait for Alpine.js to load if not available yet
    let attempts = 0;
    const maxAttempts = 50; // 5 seconds max
    
    function checkAlpine() {
        attempts++;
        if (typeof Alpine !== 'undefined') {
            console.log('Alpine.js found, initializing...');
            // Alpine.js loads and starts automatically with defer
            return;
        } else if (attempts < maxAttempts) {
            console.log(`Waiting for Alpine.js... (${attempts}/${maxAttempts})`);
            setTimeout(checkAlpine, 100);
        } else {
            console.error('Alpine.js failed to load after 5 seconds');
        }
    }
    
    checkAlpine();
});

// Alpine.js error handler
window.addEventListener('alpine:init', () => {
    console.log('Alpine.js initialized');
});

// Debug info for production
console.log('CSV Merger App Script Loaded');
console.log('csvMergerApp function available:', typeof csvMergerApp === 'function');
console.log('Socket.IO available:', typeof io !== 'undefined');
console.log('jQuery available:', typeof $ !== 'undefined'); 