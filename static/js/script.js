let currentTaskId = null;
let dotsInterval = null;

document.getElementById('csvFile').addEventListener('change', function(e) {
    const file = e.target.files[0];
    const fileName = document.getElementById('fileName');
    
    resetUI();
    
    if (!file) return;
    
    fileName.textContent = file.name;
    fileName.classList.add('show');
    
    Papa.parse(file, {
        preview: 1,
        complete: function(results) {
            updateColumnSelector(results.data[0]);
            document.getElementById('mappingSection').classList.remove('hidden');
        },
        error: function(error) {
            showError(`Error reading CSV: ${error.message}`);
        }
    });
});

document.getElementById('hasHeaders').addEventListener('change', function(e) {
    updateColumnSelector();
});

function updateColumnSelector(headers = []) {
    const hasHeaders = document.getElementById('hasHeaders').checked;
    const select = document.getElementById('columnSelect');
    const helpText = document.getElementById('columnHelp');
    
    select.innerHTML = '';
    
    if (hasHeaders && headers.length > 0) {
        headers.forEach(header => {
            const option = document.createElement('option');
            option.value = header;
            option.textContent = header;
            select.appendChild(option);
        });
        helpText.textContent = "Select the column containing email addresses";
    } else {
        const columnCount = headers.length || 10;
        for (let i = 0; i < columnCount; i++) {
            const option = document.createElement('option');
            option.value = i;
            option.textContent = `Column ${i + 1}`;
            select.appendChild(option);
        }
        helpText.textContent = "Select the column index containing email addresses";
    }
}

function startValidation() {
    const file = document.getElementById('csvFile').files[0];
    const emailColumn = document.getElementById('columnSelect').value;
    const hasHeaders = document.getElementById('hasHeaders').checked;
    
    if (!file) {
        showError('Please select a CSV file first');
        return;
    }

    toggleLoading(true);
    showProgress();
    
    const formData = new FormData();
    formData.append('file', file);
    formData.append('email_column', emailColumn);
    formData.append('has_headers', hasHeaders.toString());

    fetch('/upload', {
        method: 'POST',
        body: formData
    })
    .then(handleResponse)
    .then(data => {
        currentTaskId = data.task_id;
        monitorProgress(data.task_id);
    })
    .catch(error => {
        toggleLoading(false);
        handleError(error);
    });
}

function handleResponse(response) {
    if (!response.ok) {
        return response.json().then(err => { throw new Error(err.error) });
    }
    return response.json();
}

function monitorProgress(taskId) {
    const progressBar = document.getElementById('progressBar');
    const statusText = document.querySelector('.status-text');
    dotsInterval = animateStatusDots();

    const interval = setInterval(() => {
        fetch(`/status/${taskId}`)
            .then(handleResponse)
            .then(data => {
                updateProgressUI(data, progressBar);
                
                if (data.status === 'completed') {
                    clearInterval(interval);
                    clearInterval(dotsInterval);
                    toggleLoading(false);
                    showDownloadButton(taskId);
                }
                
                if (data.status === 'failed') {
                    clearInterval(interval);
                    clearInterval(dotsInterval);
                    toggleLoading(false);
                    throw new Error(data.error || 'Processing failed');
                }
            })
            .catch(error => {
                clearInterval(interval);
                clearInterval(dotsInterval);
                toggleLoading(false);
                handleError(error);
            });
    }, 2000);
}

function updateProgressUI(data, progressBar) {
    progressBar.style.width = `${data.progress}%`;
}

function animateStatusDots() {
    const dots = document.querySelector('.status-dots');
    let count = 0;
    return setInterval(() => {
        dots.textContent = '.'.repeat(count % 4);
        count++;
    }, 500);
}

function toggleLoading(isLoading) {
    const btn = document.getElementById('validateButton');
    const spinner = btn.querySelector('.loading-spinner');
    const btnText = btn.querySelector('.button-text');
    
    btn.disabled = isLoading;
    spinner.classList.toggle('hidden', !isLoading);
    btnText.textContent = isLoading ? 'Validating...' : 'Start Validation';
}

function showProgress() {
    document.getElementById('progressSection').classList.remove('hidden');
    document.getElementById('downloadSection').classList.add('hidden');
    document.getElementById('errorMessage').classList.add('hidden');
}

function showDownloadButton(taskId) {
    const downloadLink = document.getElementById('downloadLink');
    downloadLink.href = `/download/${taskId}`;
    document.getElementById('downloadSection').classList.remove('hidden');
}

function showError(message) {
    const errorDiv = document.getElementById('errorMessage');
    const errorText = errorDiv.querySelector('.error-text');
    
    errorText.textContent = message;
    errorDiv.classList.remove('hidden');
    
    setTimeout(() => {
        errorDiv.classList.add('hidden');
    }, 5000);
}

function resetUI() {
    document.getElementById('fileName').textContent = '';
    document.getElementById('mappingSection').classList.add('hidden');
    document.getElementById('progressSection').classList.add('hidden');
    document.getElementById('downloadSection').classList.add('hidden');
    document.getElementById('errorMessage').classList.add('hidden');
}

function handleError(error) {
    showError(error.message || 'An unknown error occurred');
    console.error('Error:', error);
}