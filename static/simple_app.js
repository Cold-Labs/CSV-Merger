/**
 * CSV Merger - Simplified Frontend
 * No WebSockets, no modules, just simple API calls and polling
 */

let currentJobId = null;
let statusPollingInterval = null;
let selectedFiles = []; // Store accumulated selected files

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    console.log('CSV Merger - Simple Frontend Loading...');
    setupEventListeners();
    initializeDragAndDrop();
    
    // Initialize empty file list
    updateFileList(selectedFiles);
});

function setupEventListeners() {
    // File input change
    const fileInput = document.getElementById('csvFiles');
    if (fileInput) {
        fileInput.addEventListener('change', handleFileSelection);
    }
    
    // Note: Start processing button uses onclick in HTML
    
    // Download result button
    const downloadResultBtn = document.getElementById('downloadResultBtn');
    if (downloadResultBtn) {
        downloadResultBtn.addEventListener('click', downloadResult);
    }
    
    // Webhook URL input - enable/disable test button
    const webhookUrlInput = document.getElementById('webhookUrl');
    if (webhookUrlInput) {
        webhookUrlInput.addEventListener('input', function() {
            const testWebhookBtn = document.getElementById('testWebhookBtn');
            if (testWebhookBtn) {
                const hasUrl = this.value.trim().length > 0;
                testWebhookBtn.disabled = !hasUrl;
            }
        });
    }
}

async function handleFileSelection() {
    const fileInput = document.getElementById('csvFiles');
    const files = Array.from(fileInput.files);
    
    if (files.length === 0) {
        return;
    }
    
    // Add new files to existing selection (avoid duplicates)
    for (let file of files) {
        const exists = selectedFiles.some(existingFile => 
            existingFile.name === file.name && existingFile.size === file.size
        );
        if (!exists) {
            // Clear any serverFilename from previous uploads since this is a new file
            delete file.serverFilename;
            selectedFiles.push(file);
        }
    }
    
    console.log(`Added ${files.length} files. Total: ${selectedFiles.length} files`);
    
    // Reset the file input so same files can be selected again if needed
    fileInput.value = '';
    
    // Upload all selected files (including previously selected ones)
    await uploadFiles(selectedFiles);
}

async function uploadFiles(files) {
    try {
        showLoading('Uploading files...');
        
        const formData = new FormData();
        for (let file of files) {
            formData.append('files', file);
        }
        
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentJobId = data.job_id;
            
            // Update selectedFiles with server-assigned filenames for accurate counting
            selectedFiles.forEach((file, index) => {
                if (data.files[index]) {
                    file.serverFilename = data.files[index].filename;
                }
            });
            
            // Update the displayed file list with all selected files
            updateFileList(selectedFiles);
            showMessage(`Uploaded ${selectedFiles.length} files successfully`, 'success');
            enableButtons();
            
            // Automatically count records after upload
            try {
                await countRecords();
            } catch (countError) {
                console.error('Count error (non-fatal):', countError);
                showMessage('Record counting failed, but files uploaded successfully', 'warning');
            }
        } else {
            showMessage(`Upload failed: ${data.error}`, 'error');
        }
        
    } catch (error) {
        console.error('Upload error:', error);
        showMessage(`Upload failed: ${error.message}`, 'error');
    } finally {
        hideLoading();
    }
}

function updateFileList(files) {
    const container = document.getElementById('fileList');
    if (!container) return;
    
    if (files.length === 0) {
        container.innerHTML = `
            <p class="text-gray-500">No files selected</p>
        `;
        disableButtons();
        
        // Hide uploaded files section when no files
        const uploadedSection = document.getElementById('uploadedFilesSection');
        if (uploadedSection) {
            uploadedSection.classList.add('hidden');
        }
        return;
    }
    
    const html = `
        ${files.map((file, index) => `
            <div class="flex items-center justify-between p-3 bg-white rounded border mb-2">
                <div class="flex items-center flex-1">
                    <svg class="w-5 h-5 text-green-500 mr-3 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"></path>
                    </svg>
                    <div class="flex-1">
                        <div class="font-medium text-gray-900">${file.name}</div>
                        <div class="text-sm text-gray-500">
                            <span>${formatFileSize(file.size)}</span>
                            <span id="count-${file.serverFilename || file.name}" class="inline">
                                • Counting records...
                            </span>
                        </div>
                    </div>
                </div>
                <button 
                    onclick="removeFile(${index})" 
                    class="text-red-500 hover:text-red-700 focus:outline-none ml-3"
                    title="Remove file"
                >
                    <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
                    </svg>
                </button>
            </div>
        `).join('')}
    `;
    
    container.innerHTML = html;
    
    // Update file summary stats
    updateFileSummary();
}

async function countRecords() {
    if (!currentJobId) {
        showMessage('No files uploaded', 'error');
        return;
    }
    
    try {
        showLoading('Counting records...');
        
        const response = await fetch('/api/count-records', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                job_id: currentJobId
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Update individual file counts
            data.file_counts.forEach(fileCount => {
                const element = document.getElementById(`count-${fileCount.filename}`);
                if (element) {
                    if (fileCount.error) {
                        element.textContent = `• Error: ${fileCount.error}`;
                        element.className = 'inline text-red-600';
                    } else {
                        element.textContent = `• ${fileCount.records.toLocaleString()} records`;
                        element.className = 'inline text-gray-500';
                    }
                }
            });
            
            // Update summary stats
            updateFileSummary();
            showMessage(`Total: ${data.total_records.toLocaleString()} records`, 'success');
        } else {
            showMessage(`Count failed: ${data.error}`, 'error');
        }
        
    } catch (error) {
        console.error('Count error:', error);
        showMessage(`Count failed: ${error.message}`, 'error');
    } finally {
        hideLoading();
    }
}

async function processFiles(mode) {
    if (!currentJobId) {
        showMessage('No files uploaded', 'error');
        return;
    }
    
    const webhookUrl = mode === 'webhook' ? document.getElementById('webhookUrl').value : null;
    const tableType = getSelectedDataType();
    
    if (mode === 'webhook' && !webhookUrl) {
        showMessage('Webhook URL is required for webhook mode', 'error');
        return;
    }
    
    try {
        // Show progress section immediately, no popup
        showProgress(true);
        // Hide form sections to prevent interference during processing
        hideFormSections();
        
        const response = await fetch('/api/process', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                job_id: currentJobId,
                processing_mode: mode,
                webhook_url: webhookUrl,
                table_type: tableType,
                rate_limit: parseInt(document.getElementById('rateLimit').value) || 20,
                record_limit: parseInt(document.getElementById('recordLimit').value) || null
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            if (mode === 'download' && data.download_ready) {
                // Download mode - immediate completion
                updateProgress(100, 'Processing completed successfully!');
                showDownloadButton();
                showMessage('Processing completed! Click download to get your file.', 'success');
                showFormSections(); // Show form sections back since download is ready
            } else {
                // Webhook mode - ALWAYS start polling, show download button if ready
                if (data.download_ready) {
                    showDownloadButton();
                    updateProgress(80, 'Download ready, starting webhook delivery...');
                } else {
                    updateProgress(0, 'Processing started...');
                }
                startStatusPolling();
            }
        } else {
            showMessage(`Processing failed: ${data.error}`, 'error');
            showProgress(false);
            showFormSections(); // Show form sections back on failure
        }
        
    } catch (error) {
        console.error('Process error:', error);
        showMessage(`Processing failed: ${error.message}`, 'error');
        showProgress(false);
        showFormSections(); // Show form sections back on error
    } finally {
        // No loading popup to hide - progress section handles everything
    }
}

function startStatusPolling() {
    if (statusPollingInterval) {
        clearInterval(statusPollingInterval);
    }
    
    statusPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/status/${currentJobId}`);
            const data = await response.json();
            
            if (data.success) {
                const status = data.status;
                updateProgress(status.progress || 0, status.message || 'Processing...', status);
                
                // Show download button as soon as download is ready
                if (status.download_ready) {
                    showDownloadButton();
                }
                
                // Show/hide stop button based on cancellation capability
                if (status.can_cancel) {
                    showStopButton();
                } else {
                    hideStopButton();
                }
                
                if (status.status === 'completed') {
                    clearInterval(statusPollingInterval);
                    hideStopButton();
                    if (status.download_ready) {
                        showMessage('Processing completed! Download ready.', 'success');
                        showDownloadButton();
                    } else {
                        showMessage('Webhook processing completed!', 'success');
                    }
                    showProgress(false);
                    showFormSections(); // Show form sections back on completion
                } else if (status.status === 'failed') {
                    clearInterval(statusPollingInterval);
                    hideStopButton();
                    showMessage(`Processing failed: ${status.message}`, 'error');
                    showProgress(false);
                    showFormSections(); // Show form sections back on failure
                } else if (status.status === 'cancelled') {
                    clearInterval(statusPollingInterval);
                    hideStopButton();
                    showMessage(`Job cancelled: ${status.message}`, 'warning');
                    showProgress(false);
                    showFormSections(); // Show form sections back on cancellation
                }
            }
        } catch (error) {
            console.error('Status polling error:', error);
        }
    }, 2000); // Poll every 2 seconds
}

function updateProgress(percentage, message, status = null) {
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');
    const progressPercent = document.getElementById('progressPercent');
    
    if (progressBar) {
        progressBar.style.width = `${percentage}%`;
    }
    
    if (progressPercent) {
        progressPercent.textContent = `${Math.round(percentage)}%`;
    }
    
    // Enhanced message display with estimated time
    if (progressText) {
        let displayMessage = message;
        
        // Add webhook progress details if available
        if (status && status.webhooks_sent && status.webhooks_total) {
            const webhookProgress = ` (${status.webhooks_sent}/${status.webhooks_total})`;
            displayMessage += webhookProgress;
        }
        
        // Add estimated time if available
        if (status && status.estimated_seconds_remaining && status.estimated_seconds_remaining > 0) {
            const timeStr = formatEstimatedTime(status.estimated_seconds_remaining);
            displayMessage += ` - ${timeStr}`;
        }
        
        progressText.textContent = displayMessage;
    }
}

function formatEstimatedTime(seconds) {
    if (seconds > 3600) {
        const hours = Math.floor(seconds / 3600);
        const mins = Math.floor((seconds % 3600) / 60);
        return `${hours}h ${mins}m remaining`;
    } else if (seconds > 60) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}m ${secs}s remaining`;
    } else {
        return `${Math.floor(seconds)}s remaining`;
    }
}

function showProgress(show) {
    const container = document.getElementById('progressContainer');
    if (container) {
        container.style.display = show ? 'block' : 'none';
    }
}

function hideFormSections() {
    // Hide upload, config, and actions sections during processing
    const sections = ['uploadSection', 'configSection', 'actionsSection'];
    sections.forEach(sectionId => {
        const section = document.getElementById(sectionId);
        if (section) {
            section.style.display = 'none';
        }
    });
}

function showFormSections() {
    // Show upload, config, and actions sections when processing is done
    const sections = ['uploadSection', 'configSection', 'actionsSection'];
    sections.forEach(sectionId => {
        const section = document.getElementById(sectionId);
        if (section) {
            section.style.display = 'block';
        }
    });
}

function showDownloadButton() {
    const button = document.getElementById('downloadResultBtn');
    if (button) {
        button.style.display = 'block';
    }
}

function showStopButton() {
    const button = document.getElementById('stopJobBtn');
    if (button) {
        button.style.display = 'block';
    }
}

function hideStopButton() {
    const button = document.getElementById('stopJobBtn');
    if (button) {
        button.style.display = 'none';
    }
}

async function stopJob() {
    if (!currentJobId) {
        showMessage('No active job to stop', 'error');
        return;
    }
    
    try {
        showLoading('Stopping job...');
        
        const response = await fetch(`/api/cancel/${currentJobId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            showMessage('Job stop requested', 'info');
            hideStopButton();
        } else {
            showMessage(`Stop failed: ${data.error}`, 'error');
        }
        
    } catch (error) {
        console.error('Stop error:', error);
        showMessage(`Stop failed: ${error.message}`, 'error');
    } finally {
        hideLoading();
    }
}

async function downloadResult() {
    if (!currentJobId) {
        showMessage('No processed file available', 'error');
        return;
    }
    
    try {
        const response = await fetch(`/api/download/${currentJobId}`);
        
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `processed_${currentJobId}.csv`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            showMessage('File downloaded successfully!', 'success');
        } else {
            const data = await response.json();
            showMessage(`Download failed: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Download error:', error);
        showMessage(`Download failed: ${error.message}`, 'error');
    }
}

function enableButtons() {
    const startBtn = document.getElementById('startProcessingBtn');
    const testWebhookBtn = document.getElementById('testWebhookBtn');
    
    if (startBtn) startBtn.disabled = false;
    
    // Enable test button if webhook URL is provided
    if (testWebhookBtn) {
        const webhookUrl = document.getElementById('webhookUrl').value.trim();
        testWebhookBtn.disabled = !webhookUrl;
    }
}

function disableButtons() {
    const startBtn = document.getElementById('startProcessingBtn');
    const testWebhookBtn = document.getElementById('testWebhookBtn');
    
    if (startBtn) startBtn.disabled = true;
    if (testWebhookBtn) testWebhookBtn.disabled = true;
}

function showLoading(message) {
    const loading = document.getElementById('loadingIndicator');
    const loadingText = document.getElementById('loadingText');
    
    if (loading) {
        loading.style.display = 'flex';
    }
    
    if (loadingText) {
        loadingText.textContent = message;
    }
}

function hideLoading() {
    const loading = document.getElementById('loadingIndicator');
    if (loading) {
        loading.style.display = 'none';
    }
}

function showMessage(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    
    const colors = {
        success: 'bg-green-500 text-white',
        error: 'bg-red-500 text-white', 
        info: 'bg-blue-500 text-white',
        warning: 'bg-yellow-500 text-white'
    };
    
    const icons = {
        success: '✓',
        error: '✗',
        info: 'i',
        warning: '!'
    };
    
    // Create toast element
    const toast = document.createElement('div');
    toast.className = `${colors[type]} px-4 py-3 rounded-lg shadow-lg flex items-center space-x-3 transform translate-x-full transition-transform duration-300 ease-in-out`;
    
    toast.innerHTML = `
        <div class="flex-shrink-0 w-5 h-5 rounded-full bg-white bg-opacity-20 flex items-center justify-center text-sm font-bold">
            ${icons[type]}
        </div>
        <div class="flex-1 text-sm font-medium">${message}</div>
        <button class="flex-shrink-0 text-white hover:text-gray-200 focus:outline-none" onclick="this.parentElement.remove()">
            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
            </svg>
        </button>
    `;
    
    container.appendChild(toast);
    
    // Slide in animation
    setTimeout(() => {
        toast.classList.remove('translate-x-full');
    }, 10);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.classList.add('translate-x-full');
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 300);
        }
    }, 5000);
    
    console.log(`${type.toUpperCase()}: ${message}`);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// File management functions
async function removeFile(index) {
    if (index >= 0 && index < selectedFiles.length) {
        const removedFile = selectedFiles.splice(index, 1)[0];
        console.log(`Removed file: ${removedFile.name}`);
        
        // Update the file list display
        updateFileList(selectedFiles);
        
        // Show toast notification
        showMessage(`Removed ${removedFile.name}`, 'info');
        
        // If no files left, disable buttons and reset job
        if (selectedFiles.length === 0) {
            currentJobId = null;
            disableButtons();
            
            // Ensure the uploaded files section is hidden
            const uploadedSection = document.getElementById('uploadedFilesSection');
            if (uploadedSection) {
                uploadedSection.classList.add('hidden');
            }
        } else {
            // Clear any old server filenames since we're re-uploading
            selectedFiles.forEach(file => {
                delete file.serverFilename;
            });
            
            // Re-upload and recount remaining files
            try {
                await uploadFiles(selectedFiles);
            } catch (error) {
                console.error('Error re-uploading files after removal:', error);
            }
        }
    }
}

function clearAllFiles() {
    if (selectedFiles.length === 0) return;
    
    const fileCount = selectedFiles.length;
    selectedFiles = [];
    currentJobId = null;
    
    // Update the file list display
    updateFileList(selectedFiles);
    
    // Reset the file input
    const fileInput = document.getElementById('csvFiles');
    if (fileInput) {
        fileInput.value = '';
    }
    
    // Ensure the uploaded files section is hidden
    const uploadedSection = document.getElementById('uploadedFilesSection');
    if (uploadedSection) {
        uploadedSection.classList.add('hidden');
    }
    
    // Disable buttons
    disableButtons();
    
    // Show toast notification
    showMessage(`Cleared ${fileCount} files`, 'info');
    
    console.log('Cleared all selected files');
}

// Test webhook functionality
async function testWebhook() {
    const webhookUrl = document.getElementById('webhookUrl').value.trim();
    const testWebhookBtn = document.getElementById('testWebhookBtn');
    
    if (!webhookUrl) {
        showMessage('Please enter a webhook URL first', 'error');
        return;
    }
    
    // Disable button during test
    const originalText = testWebhookBtn.textContent;
    testWebhookBtn.disabled = true;
    testWebhookBtn.textContent = 'Testing...';
    
    try {
        const response = await fetch('/api/test-webhook', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                webhook_url: webhookUrl
            })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showMessage(`Webhook test successful! Response: ${result.status}`, 'success');
        } else {
            showMessage(`Webhook test failed: ${result.error}`, 'error');
        }
        
    } catch (error) {
        console.error('Webhook test error:', error);
        showMessage(`Webhook test failed: ${error.message}`, 'error');
    } finally {
        // Re-enable button
        testWebhookBtn.disabled = false;
        testWebhookBtn.textContent = originalText;
        
        // Re-check if button should be enabled based on URL
        const webhookUrlValue = document.getElementById('webhookUrl').value.trim();
        testWebhookBtn.disabled = !webhookUrlValue;
    }
}

// New functions for updated UI

function toggleWebhookConfig() {
    const webhookConfig = document.getElementById('webhookConfig');
    const webhookRadio = document.getElementById('outputMethodWebhook');
    
    if (webhookRadio.checked) {
        webhookConfig.classList.remove('hidden');
    } else {
        webhookConfig.classList.add('hidden');
    }
}

function getSelectedDataType() {
    const dataTypeRadios = document.querySelectorAll('input[name="dataType"]');
    for (const radio of dataTypeRadios) {
        if (radio.checked) {
            return radio.value;
        }
    }
    return 'people'; // default
}

function getSelectedOutputMethod() {
    const outputMethodRadios = document.querySelectorAll('input[name="outputMethod"]');
    for (const radio of outputMethodRadios) {
        if (radio.checked) {
            return radio.value;
        }
    }
    return 'download'; // default
}

function startProcessing() {
    const dataType = getSelectedDataType();
    const outputMethod = getSelectedOutputMethod();
    
    if (outputMethod === 'download') {
        processFiles('download');
    } else {
        processFiles('webhook');
    }
}

function updateFileSummary() {
    const uploadedSection = document.getElementById('uploadedFilesSection');
    const fileCountEl = document.getElementById('fileCount');
    const summaryFilesEl = document.getElementById('summaryFiles');
    const summarySizeEl = document.getElementById('summarySize');
    const summaryRecordsEl = document.getElementById('summaryRecords');
    
    if (selectedFiles.length > 0) {
        uploadedSection.classList.remove('hidden');
        
        // Update file count
        const fileText = selectedFiles.length === 1 ? 'file' : 'files';
        fileCountEl.textContent = `${selectedFiles.length} ${fileText}`;
        
        // Calculate total size
        let totalSize = 0;
        let totalRecords = 0;
        
        selectedFiles.forEach(file => {
            totalSize += file.size || 0;
            
            // Get record count from the file's count element if available
            const countEl = document.getElementById(`count-${file.serverFilename || file.name}`);
            if (countEl && countEl.textContent) {
                const countText = countEl.textContent;
                const match = countText.match(/(\d+(?:,\d+)*)/);
                if (match) {
                    totalRecords += parseInt(match[1].replace(/,/g, ''));
                }
            }
        });
        
        // Format file size
        const formatSize = (bytes) => {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        };
        
        // Update summary
        summaryFilesEl.textContent = selectedFiles.length;
        summarySizeEl.textContent = formatSize(totalSize);
        summaryRecordsEl.textContent = totalRecords.toLocaleString();
    } else {
        uploadedSection.classList.add('hidden');
    }
    
    // Enable/disable start processing button
    const startBtn = document.getElementById('startProcessingBtn');
    if (startBtn) {
        startBtn.disabled = selectedFiles.length === 0;
    }
}

// Initialize drag and drop functionality
function initializeDragAndDrop() {
    const dropZone = document.getElementById('dropZone'); // The drag and drop area
    const fileInput = document.getElementById('csvFiles');
    
    if (!dropZone || !fileInput) return;
    
    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });
    
    // Highlight drop area when item is dragged over it
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, highlight, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, unhighlight, false);
    });
    
    // Handle dropped files
    dropZone.addEventListener('drop', handleDrop, false);
    
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    function highlight(e) {
        dropZone.classList.add('border-blue-500', 'bg-blue-50');
        dropZone.classList.remove('border-gray-300');
    }
    
    function unhighlight(e) {
        dropZone.classList.remove('border-blue-500', 'bg-blue-50');
        dropZone.classList.add('border-gray-300');
    }
    
    async function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        
        // Convert FileList to Array and filter for CSV files
        const csvFiles = Array.from(files).filter(file => {
            const isCSV = file.name.toLowerCase().endsWith('.csv') || file.type === 'text/csv';
            if (!isCSV) {
                showMessage(`Skipped ${file.name}: Only CSV files are allowed`, 'warning');
            }
            return isCSV;
        });
        
        if (csvFiles.length === 0) {
            showMessage('No valid CSV files found in the dropped items', 'error');
            return;
        }
        
        // Add dropped files to existing selection
        csvFiles.forEach(file => {
            // Check if file is already selected
            const exists = selectedFiles.some(existing => 
                existing.name === file.name && existing.size === file.size
            );
            
            if (!exists) {
                selectedFiles.push(file);
            }
        });
        
        // Update the file input to reflect the selection (for form compatibility)
        const dataTransfer = new DataTransfer();
        selectedFiles.forEach(file => {
            dataTransfer.items.add(file);
        });
        fileInput.files = dataTransfer.files;
        
        // Process the files
        try {
            await uploadFiles(selectedFiles);
            showMessage(`Successfully added ${csvFiles.length} CSV file(s)`, 'success');
        } catch (error) {
            console.error('Error processing dropped files:', error);
            showMessage(`Error processing dropped files: ${error.message}`, 'error');
        }
    }
}

