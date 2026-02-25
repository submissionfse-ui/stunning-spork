/* ============================================
   Policy Summarizer — Frontend Logic (SSE Streaming)
   ============================================ */

// --- File Upload / Drag & Drop ---
const uploadArea = document.getElementById('uploadArea');
const fileInput = document.getElementById('fileInput');
const policyInput = document.getElementById('policyInput');

uploadArea.addEventListener('click', () => fileInput.click());
uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('drag-over');
});
uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('drag-over');
});
uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) readFile(file);
});
fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) readFile(fileInput.files[0]);
});

function readFile(file) {
    if (!file.name.endsWith('.json')) {
        showError('Please upload a .json file');
        return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
        policyInput.value = e.target.result;
        hideError();
    };
    reader.readAsText(file);
}

// --- Bucket state tracking ---
let bucketCards = {};

// --- Analyze Policy (SSE) ---
async function analyzePolicy() {
    const policyText = policyInput.value.trim();
    const bound = parseInt(document.getElementById('boundInput').value) || 100;
    const explain = document.getElementById('explainToggle').checked;

    // Validate JSON
    let policy;
    try {
        policy = JSON.parse(policyText);
    } catch (e) {
        showError('Invalid JSON: ' + e.message);
        return;
    }

    if (!policy.Statement && !policy.statement) {
        showError('Policy must contain a "Statement" field');
        return;
    }

    // UI: loading state
    hideError();
    setLoading(true);
    bucketCards = {};

    const container = document.getElementById('resultsContainer');
    container.innerHTML = '';
    container.hidden = false;
    document.getElementById('resultsPlaceholder').hidden = true;
    document.getElementById('resultsSummary').hidden = true;

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ policy, bound, explain })
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: 'Server error' }));
            throw new Error(err.detail || `HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Parse SSE events from buffer
            const lines = buffer.split('\n');
            buffer = '';
            let currentEvent = null;

            for (const line of lines) {
                if (line.startsWith('event: ')) {
                    currentEvent = line.substring(7).trim();
                } else if (line.startsWith('data: ') && currentEvent) {
                    const data = JSON.parse(line.substring(6));
                    handleEvent(currentEvent, data);
                    currentEvent = null;
                } else if (line === '') {
                    currentEvent = null;
                } else {
                    // Incomplete line, put back in buffer
                    buffer += line + '\n';
                }
            }
        }

    } catch (e) {
        showError('Analysis failed: ' + e.message);
    } finally {
        setLoading(false);
    }
}

// --- Handle SSE Events ---
function handleEvent(type, data) {
    switch (type) {
        case 'start':
            updateLoadingText(`Analyzing ${data.total_buckets} bucket(s)...`);
            break;

        case 'stage':
            updateLoadingText(data.message);
            updateBucketStage(data.bucket_index, data.stage, data.message);
            break;

        case 'bucket':
            createBucketCard(data);
            break;

        case 'simplified':
            addSimplifiedRegex(data);
            break;

        case 'jaccard':
            addJaccardScore(data);
            break;

        case 'verified':
            addVerifiedPath(data);
            break;

        case 'done':
            setLoading(false);
            showSummary();
            break;
    }
}

// --- Create Bucket Card (Stage 1) ---
function createBucketCard(data) {
    const container = document.getElementById('resultsContainer');
    const idx = data.bucket_index;
    const total = data.total;

    const card = document.createElement('div');
    card.className = 'bucket-card expanded';
    card.id = `bucket-${idx}`;

    const actionsStr = (data.actions || []).join(', ');
    const rawRegex = data.raw_regex || '∅';
    const regexPreview = rawRegex.length > 80 ? rawRegex.substring(0, 80) + '...' : rawRegex;
    const hasLongRegex = rawRegex.length > 80;

    let bodyHTML = '';

    // Actions
    bodyHTML += `
        <div class="bucket-section">
            <div class="section-label">Actions</div>
            <div class="actions-list">
                ${(data.actions || []).map(a => `<span class="action-tag">${escapeHTML(a)}</span>`).join('')}
            </div>
        </div>
    `;

    // Raw Regex
    const regexId = `regex-${idx}`;
    bodyHTML += `
        <div class="bucket-section">
            <div class="section-label">Raw Regex <span class="time-badge">${data.abc_time}s</span></div>
            <div class="section-value">${escapeHTML(regexPreview)}</div>
            ${hasLongRegex ? `
                <button class="regex-toggle" onclick="toggleRegex('${regexId}', this)">Show full regex</button>
                <div class="regex-full section-value" id="${regexId}">${escapeHTML(rawRegex)}</div>
            ` : ''}
        </div>
    `;

    // Simplified placeholder
    bodyHTML += `<div id="simplified-${idx}" class="bucket-section" hidden></div>`;

    // Jaccard similarity placeholder
    bodyHTML += `<div id="jaccard-${idx}" class="bucket-section" hidden></div>`;

    // Permission sets placeholder
    bodyHTML += `<div id="paths-${idx}" class="bucket-section" hidden>
        <div class="section-label">Permission Sets</div>
        <div class="section-hint">Each permission set is formally verified. ✅ = allowed by the policy, ❌ = not allowed.</div>
        <ul class="path-list" id="pathlist-${idx}"></ul>
    </div>`;

    // Stage indicator
    bodyHTML += `<div id="stage-${idx}" class="stage-indicator" hidden></div>`;

    card.innerHTML = `
        <div class="bucket-header" onclick="toggleBucket(this)">
            <span class="bucket-toggle">▶</span>
            <span class="bucket-title">[${idx + 1}/${total}] ${escapeHTML(data.sid)}: ${escapeHTML(actionsStr)}</span>
        </div>
        <div class="bucket-body">${bodyHTML}</div>
    `;

    container.appendChild(card);
    bucketCards[idx] = card;

    // Scroll to new card
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// --- Add Simplified Regex (Stage 2) ---
function addSimplifiedRegex(data) {
    const el = document.getElementById(`simplified-${data.bucket_index}`);
    if (!el) return;

    el.innerHTML = `
        <div class="section-label">Simplified Regex</div>
        <div class="section-value simplified">${escapeHTML(data.simplified_regex || 'N/A')}</div>
    `;
    el.hidden = false;

    // Add badge to header
    const card = bucketCards[data.bucket_index];
    if (card && data.simplified_regex) {
        const header = card.querySelector('.bucket-header');
        const badge = document.createElement('span');
        badge.className = 'bucket-badge';
        badge.textContent = data.simplified_regex.substring(0, 30);
        header.appendChild(badge);
    }
}

// --- Add Verified Permission Set (Stage 3, one at a time) ---
function addVerifiedPath(data) {
    const pathsSection = document.getElementById(`paths-${data.bucket_index}`);
    const pathList = document.getElementById(`pathlist-${data.bucket_index}`);
    if (!pathsSection || !pathList) return;

    pathsSection.hidden = false;

    const li = document.createElement('li');
    li.className = 'path-item path-item-enter';
    li.innerHTML = `
        <span class="path-icon">${data.verified ? '✅' : '❌'}</span>
        <code class="path-text perm-pattern">${escapeHTML(data.path)}</code>
    `;
    pathList.appendChild(li);

    // Trigger animation
    requestAnimationFrame(() => li.classList.add('path-item-visible'));
}

// --- Add Jaccard Similarity Score (Stage 2b) ---
function addJaccardScore(data) {
    const el = document.getElementById(`jaccard-${data.bucket_index}`);
    if (!el) return;

    const score = data.jaccard_similarity;
    if (score === null || score === undefined) {
        el.innerHTML = `
            <div class="section-label">Jaccard Similarity</div>
            <div class="section-value jaccard-na">N/A</div>
        `;
    } else {
        const pct = (score * 100).toFixed(1);
        // Determine color class based on score
        let colorClass = 'jaccard-low';
        if (score >= 0.95) colorClass = 'jaccard-high';
        else if (score >= 0.7) colorClass = 'jaccard-mid';

        el.innerHTML = `
            <div class="section-label">Jaccard Similarity</div>
            <div class="jaccard-score-container">
                <div class="jaccard-bar-bg">
                    <div class="jaccard-bar-fill ${colorClass}" style="width: ${pct}%"></div>
                </div>
                <span class="jaccard-value ${colorClass}">${pct}%</span>
            </div>
        `;
    }
    el.hidden = false;
}

// --- Update stage indicator inside a bucket ---
function updateBucketStage(bucketIndex, stage, message) {
    const el = document.getElementById(`stage-${bucketIndex}`);
    if (!el) return;

    const icons = { abc: '⚙️', llm: '🤖', verify: '🔍', jaccard: '📊' };
    el.innerHTML = `<span>${icons[stage] || '⏳'} ${escapeHTML(message)}</span>`;
    el.hidden = false;

    // Hide when done
    if (stage === 'done') el.hidden = true;
}

// --- Show Summary ---
function showSummary() {
    // Remove all stage indicators entirely
    document.querySelectorAll('.stage-indicator').forEach(el => {
        el.innerHTML = '';
        el.hidden = true;
        el.style.display = 'none';
    });

    // Clear loading text
    updateLoadingText('');

    const cards = document.querySelectorAll('.bucket-card');
    const totalBuckets = cards.length;
    const totalVerified = document.querySelectorAll('.path-icon').length;

    const summary = document.getElementById('resultsSummary');
    summary.innerHTML = `
        <span class="summary-stat">Buckets analyzed: <span>${totalBuckets}</span></span>
        <span class="summary-stat">Permission sets verified: <span>${totalVerified}</span></span>
    `;
    summary.hidden = false;
}

// --- Toggle Helpers ---
function toggleBucket(headerEl) {
    headerEl.parentElement.classList.toggle('expanded');
}

function toggleRegex(id, btnEl) {
    const el = document.getElementById(id);
    el.classList.toggle('visible');
    btnEl.textContent = el.classList.contains('visible') ? 'Hide full regex' : 'Show full regex';
}

// --- UI Helpers ---
function setLoading(loading) {
    const btn = document.getElementById('analyzeBtn');
    const btnText = btn.querySelector('.btn-text');
    const btnSpinner = btn.querySelector('.btn-spinner');
    const loadingEl = document.getElementById('resultsLoading');

    btn.disabled = loading;
    btnText.textContent = loading ? 'Analyzing...' : 'Analyze Policy';
    btnSpinner.hidden = !loading;
    loadingEl.hidden = !loading;

    if (loading) {
        document.getElementById('resultsSummary').hidden = true;
        document.getElementById('resultsPlaceholder').hidden = true;
    }
}

function updateLoadingText(msg) {
    const el = document.getElementById('loadingText');
    if (el) el.textContent = msg;
}

function showError(msg) {
    const el = document.getElementById('errorMsg');
    el.textContent = msg;
    el.hidden = false;
}

function hideError() {
    document.getElementById('errorMsg').hidden = true;
}

function escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
