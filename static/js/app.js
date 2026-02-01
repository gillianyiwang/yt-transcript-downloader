// ========================================
// YouTube Transcript Downloader - JavaScript
// ========================================

// Global state
const state = {
    videoId: null,
    videoTitle: null,
    videoDescription: null,
    videoLength: null,
    videoUrl: null,
    segments: [],
    currentText: '',
    transcriptLanguages: {},
    currentLanguage: null,
};

// DOM elements
const urlInput = document.getElementById('url-input');
const fetchButton = document.getElementById('fetch-button');
const fetchStatus = document.getElementById('fetch-status');
const progressFill = document.getElementById('progress-fill');
const progressLabel = document.getElementById('progress-label');
const videoInfoRow = document.getElementById('video-info-row');
const thumbnailImage = document.getElementById('thumbnail-image');
const videoTitleLabel = document.getElementById('video-title-label');
const startInput = document.getElementById('start-input');
const endInput = document.getElementById('end-input');
const rangeError = document.getElementById('range-error');
const rangeHint = document.getElementById('range-hint');
const displayMode = document.getElementById('display-mode');
const includeTitleCheckbox = document.getElementById('include-title');
const includeDescriptionCheckbox = document.getElementById('include-description');
const transcriptLanguageSelect = document.getElementById('transcript-language');
const fileTitleInput = document.getElementById('file-title');
const applyButton = document.getElementById('apply-button');
const countsLabel = document.getElementById('counts-label');
const previewArea = document.getElementById('preview-area');
const copyButton = document.getElementById('copy-button');
const actionStatus = document.getElementById('action-status');

// ========================================
// Utility Functions
// ========================================

function setProgress(value) {
    const percent = Math.max(0, Math.min(100, value * 100));
    progressFill.style.width = `${percent}%`;
    progressLabel.textContent = `${Math.round(percent)}%`;
}

function resetProgress() {
    setProgress(0);
}

function parseTimecode(s) {
    if (!s || s.trim() === '') return null;
    const parts = s.trim().split(':').map(p => parseFloat(p));
    if (parts.some(isNaN)) return null;

    if (parts.length === 1) return parts[0];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return null;
}

function formatTimestamp(seconds) {
    const total = Math.round(seconds);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;

    if (h > 0) {
        return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function getVideoDuration() {
    if (state.videoLength) return state.videoLength;
    if (state.segments.length > 0) {
        const last = state.segments[state.segments.length - 1];
        return last.start + (last.duration || 0);
    }
    return null;
}

function refreshCounts() {
    const text = state.currentText || '';
    const words = text.split(/\s+/).filter(w => w.length > 0).length;
    const chars = text.length;
    countsLabel.textContent = `Words: ${words} | Characters: ${chars} | Est. size: ${formatSize(chars)}`;
}

function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    const mb = kb / 1024;
    return `${mb.toFixed(2)} MB`;
}

function resetToFullRange() {
    const duration = getVideoDuration();
    if (!duration || duration <= 0) return;
    startInput.value = '0';
    endInput.value = formatTimestamp(duration);
    rangeError.textContent = '';
}

// ========================================
// Time Adjustment Functions
// ========================================

function validateTimeRange() {
    const duration = getVideoDuration();
    if (!duration || duration <= 0) {
        rangeError.textContent = 'Transcript not loaded; please fetch transcript first.';
        return false;
    }

    const rawStart = (startInput.value || '').trim();
    const rawEnd = (endInput.value || '').trim();

    let startSec, endSec;

    // Parse and validate start time
    if (rawStart === '') {
        startSec = 0.0;
    } else {
        startSec = parseTimecode(rawStart);
        if (startSec === null) {
            rangeError.textContent = 'Invalid start time format.';
            return false;
        }
    }

    // Parse and validate end time
    if (rawEnd === '') {
        endSec = duration;
    } else {
        endSec = parseTimecode(rawEnd);
        if (endSec === null) {
            rangeError.textContent = 'Invalid end time format.';
            return false;
        }
    }

    // Clamp to valid range
    startSec = Math.max(0, Math.min(startSec, duration));
    endSec = Math.max(0, Math.min(endSec, duration));

    // Check if end > start
    if (endSec <= startSec) {
        rangeError.textContent = 'End time must be greater than start time.';
        return false;
    }

    // Update inputs with normalized values
    startInput.value = formatTimestamp(startSec);
    endInput.value = formatTimestamp(endSec);
    rangeError.textContent = '';
    return true;
}

function adjustTimeInput(inputElement, deltaSeconds) {
    const duration = getVideoDuration();
    if (!duration || duration <= 0) return;

    const raw = (inputElement.value || '').trim();
    let currentSec = parseTimecode(raw);
    if (currentSec === null) currentSec = 0;

    const newSec = Math.max(0, Math.min(currentSec + deltaSeconds, duration));
    inputElement.value = formatTimestamp(newSec);
    rangeError.textContent = '';
}

function adjustStart(delta) {
    adjustTimeInput(startInput, delta);
}

function adjustEnd(delta) {
    adjustTimeInput(endInput, delta);
}

// ========================================
// Fetch Transcript
// ========================================

async function fetchTranscript() {
    resetProgress();
    actionStatus.textContent = '';
    rangeError.textContent = '';
    fetchStatus.textContent = 'Parsing URL...';
    setProgress(0.1);

    const url = urlInput.value || '';
    if (!url) {
        fetchStatus.textContent = 'Please enter a YouTube URL';
        resetProgress();
        return;
    }

    try {
        fetchStatus.textContent = 'Fetching transcript...';
        setProgress(0.3);

        const response = await fetch('/api/fetch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to fetch transcript');
        }

        const data = await response.json();

        // Update state
        state.videoId = data.video_id;
        state.videoTitle = data.video_title;
        state.videoDescription = data.video_description;
        state.videoLength = data.video_length;
        state.videoUrl = data.video_url;
        state.segments = data.segments;
        state.transcriptLanguages = data.transcript_languages;
        state.currentLanguage = data.default_language;

        // Update UI
        if (state.videoTitle) {
            fileTitleInput.value = sanitizeFilename(state.videoTitle);
            videoTitleLabel.textContent = state.videoTitle + ' ⇱';
            videoTitleLabel.href = state.videoUrl;
        } else {
            fileTitleInput.value = 'transcript';
            videoTitleLabel.textContent = 'Title unavailable';
            videoTitleLabel.href = '#';
        }

        if (data.thumbnail_url) {
            thumbnailImage.src = data.thumbnail_url;
            thumbnailImage.onclick = () => window.open(state.videoUrl, '_blank');
        }

        videoInfoRow.style.display = 'flex';

        // Populate language selector
        transcriptLanguageSelect.innerHTML = '';
        for (const [code, label] of Object.entries(data.transcript_languages)) {
            const option = document.createElement('option');
            option.value = code;
            option.textContent = label;
            transcriptLanguageSelect.appendChild(option);
        }
        transcriptLanguageSelect.value = data.default_language;

        // Update time range hint and defaults
        const duration = getVideoDuration();
        if (duration && duration > 0) {
            const endTs = formatTimestamp(duration);
            rangeHint.textContent = `Default range is 0 to ${endTs}.`;
            startInput.value = '0';
            endInput.value = endTs;
        } else {
            rangeHint.textContent = 'Clear custom start/end time to use the full video.';
            startInput.value = '';
            endInput.value = '';
        }

        setProgress(1.0);
        fetchStatus.textContent = `Transcript fetched in ${data.default_language}.`;

        // Initialize preview
        updatePreview();

    } catch (error) {
        console.error('Fetch error:', error);
        fetchStatus.textContent = error.message;
        videoInfoRow.style.display = 'none';
        resetProgress();
    }
}

// ========================================
// Apply Options
// ========================================

async function applyOptions() {
    const desiredCode = transcriptLanguageSelect.value;

    // If language changed, reload transcript
    if (desiredCode && state.videoId && desiredCode !== state.currentLanguage) {
        fetchStatus.textContent = `Reloading transcript in ${desiredCode}...`;

        try {
            const response = await fetch(`/api/load_transcript?video_id=${state.videoId}&language_code=${desiredCode}`, {
                method: 'POST',
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to load transcript');
            }

            const data = await response.json();
            state.segments = data.segments;
            state.currentLanguage = desiredCode;
            fetchStatus.textContent = `Transcript loaded in ${desiredCode}.`;

        } catch (error) {
            console.error('Load transcript error:', error);
            fetchStatus.textContent = error.message;
            return;
        }
    }

    // Now apply time range + formatting
    updatePreview();
}

// ========================================
// Update Preview
// ========================================

async function updatePreview() {
    if (!state.segments || state.segments.length === 0) {
        state.currentText = '';
        previewArea.value = '';
        refreshCounts();
        return;
    }

    // Validate time range before making API call
    if (!validateTimeRange()) {
        return; // Error message already set by validateTimeRange()
    }

    try {
        const response = await fetch('/api/apply_options', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                video_id: state.videoId,
                language_code: state.currentLanguage,
                start_time: startInput.value || '0',
                end_time: endInput.value || formatTimestamp(getVideoDuration() || 0),
                display_mode: displayMode.value,
                include_title: includeTitleCheckbox.checked,
                include_description: includeDescriptionCheckbox.checked,
                video_title: state.videoTitle,
                video_description: state.videoDescription,
                video_length: state.videoLength,
                segments: state.segments,
            }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to apply options');
        }

        const data = await response.json();
        state.currentText = data.text;
        previewArea.value = data.text;
        countsLabel.textContent = `Words: ${data.word_count} | Characters: ${data.char_count} | Est. size: ${data.size_str}`;

    } catch (error) {
        console.error('Apply options error:', error);
        rangeError.textContent = error.message;
    }
}

// ========================================
// Copy to Clipboard
// ========================================

function copyToClipboard() {
    const text = previewArea.value || state.currentText || '';
    if (!text) {
        actionStatus.textContent = 'Nothing to copy.';
        return;
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            actionStatus.textContent = 'Copied to clipboard.';
        }).catch(() => {
            fallbackCopy(text);
        });
    } else {
        fallbackCopy(text);
    }
}

function fallbackCopy(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
        document.execCommand('copy');
        actionStatus.textContent = 'Copied to clipboard.';
    } catch (err) {
        actionStatus.textContent = 'Failed to copy.';
    }
    document.body.removeChild(ta);
}

// ========================================
// Export File
// ========================================

async function exportFile(format) {
    const text = previewArea.value || state.currentText || '';
    if (!text) {
        actionStatus.textContent = 'Nothing to export. Fetch transcript first.';
        return;
    }

    const rawName = (fileTitleInput.value || '').trim();
    const filename = rawName ? sanitizeFilename(rawName) :
                     (state.videoTitle ? sanitizeFilename(state.videoTitle) : 'transcript');

    try {
        const response = await fetch('/api/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, filename, format }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Export failed');
        }

        // Download file
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = response.headers.get('Content-Disposition')?.split('filename=')[1] || `${filename}.${format}`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        actionStatus.textContent = `Downloaded ${filename}.${format}`;

    } catch (error) {
        console.error('Export error:', error);
        actionStatus.textContent = error.message;
    }
}

// ========================================
// Helper Functions
// ========================================

function sanitizeFilename(name) {
    return name.replace(/[\\/:*?"<>|]/g, '').replace(/\s+/g, '_').replace(/^_+|_+$/g, '') || 'transcript';
}

// ========================================
// Event Listeners
// ========================================

fetchButton.addEventListener('click', fetchTranscript);
applyButton.addEventListener('click', applyOptions);
copyButton.addEventListener('click', copyToClipboard);

// Time input blur handlers
startInput.addEventListener('blur', () => {
    const duration = getVideoDuration();
    if (!duration || duration <= 0) return;

    const sVal = (startInput.value || '').trim();
    const eVal = (endInput.value || '').trim();

    if (sVal === '' && eVal === '') {
        resetToFullRange();
    } else if (sVal === '') {
        startInput.value = '0';
        rangeError.textContent = '';
    }
});

endInput.addEventListener('blur', () => {
    const duration = getVideoDuration();
    if (!duration || duration <= 0) return;

    const eVal = (endInput.value || '').trim();
    if (eVal === '') {
        resetToFullRange();
    }
});

// Allow Enter key to trigger fetch
urlInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        fetchTranscript();
    }
});

// Update counts when user edits preview
previewArea.addEventListener('input', () => {
    state.currentText = previewArea.value;
    refreshCounts();
});
