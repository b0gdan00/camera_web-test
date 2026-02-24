// ══════════════════════════════════════════════════
//  Auth / Viewers
// ══════════════════════════════════════════════════
var viewerName = sessionStorage.getItem('viewerName') || '';
var loginOverlay    = document.getElementById('loginOverlay');
var nameInput       = document.getElementById('nameInput');
var viewersInline   = document.getElementById('viewersInline');
var viewersToggle   = document.getElementById('viewersToggle');
var viewersCount    = document.getElementById('viewersCount');
var viewersDropdown = document.getElementById('viewersDropdown');
var viewersDropdownList = document.getElementById('viewersDropdownList');
var leaveBtn        = document.getElementById('leaveBtn');

nameInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') joinStream();
});

function showLeaveBtn(show) {
    leaveBtn.style.display = show ? 'inline-flex' : 'none';
}

function joinStream() {
    var name = nameInput.value.trim();
    if (!name) { nameInput.focus(); return; }
    viewerName = name;
    sessionStorage.setItem('viewerName', name);

    fetch('/api/join', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name}),
    }).then(function(r) { return r.json(); })
      .then(function(data) { renderViewers(data.viewers); })
      .catch(function() {});

    loginOverlay.classList.add('hidden');
    document.getElementById('stream').src = '/video_feed';
    showLeaveBtn(true);
}

function leaveStream() {
    if (!viewerName) return;
    fetch('/api/leave', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: viewerName}),
    }).then(function(r) { return r.json(); })
      .then(function(data) { renderViewers(data.viewers); })
      .catch(function() {});

    viewerName = '';
    sessionStorage.removeItem('viewerName');
    document.getElementById('stream').src = '';
    loginOverlay.classList.remove('hidden');
    nameInput.value = '';
    showLeaveBtn(false);
}

function renderViewers(list) {
    var chips = '';
    for (var i = 0; i < list.length; i++) {
        chips += '<span class="viewer-chip"><span class="viewer-dot"></span>' + list[i] + '</span>';
    }
    viewersInline.innerHTML = chips;
    viewersDropdownList.innerHTML = chips;
    viewersCount.textContent = list.length;
}

function toggleViewersDropdown() {
    viewersDropdown.classList.toggle('open');
}

// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
    if (!viewersToggle.contains(e.target) && !viewersDropdown.contains(e.target)) {
        viewersDropdown.classList.remove('open');
    }
});

// Heartbeat every 10s
setInterval(function() {
    if (!viewerName) return;
    fetch('/api/heartbeat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: viewerName}),
    }).then(function(r) { return r.json(); })
      .then(function(data) { renderViewers(data.viewers); })
      .catch(function() {});
}, 10000);

// Poll viewers every 15s
setInterval(function() {
    if (!viewerName) return;
    fetch('/api/viewers').then(function(r) { return r.json(); })
      .then(function(data) { renderViewers(data.viewers); })
      .catch(function() {});
}, 15000);

// Auto-login if name already saved
if (viewerName) {
    loginOverlay.classList.add('hidden');
    document.getElementById('stream').src = '/video_feed';
    showLeaveBtn(true);
    fetch('/api/join', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: viewerName}),
    }).then(function(r) { return r.json(); })
      .then(function(data) { renderViewers(data.viewers); })
      .catch(function() {});
}

// ══════════════════════════════════════════════════
//  Clock
// ══════════════════════════════════════════════════
function updateClock() {
    document.getElementById('clock').textContent =
        new Date().toLocaleTimeString('uk-UA', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}
updateClock();
setInterval(updateClock, 1000);

// ══════════════════════════════════════════════════
//  Stream status
// ══════════════════════════════════════════════════
var streamImg  = document.getElementById('stream');
var badge      = document.getElementById('statusBadge');
var statusText = document.getElementById('statusText');
var errorOvl   = document.getElementById('errorOverlay');

function setOnline(on) {
    badge.classList.toggle('offline', !on);
    statusText.textContent = on ? 'Connected' : 'Disconnected';
    errorOvl.classList.toggle('visible', !on);
}

streamImg.addEventListener('error', function() { setOnline(false); });
streamImg.addEventListener('load',  function() { setOnline(true); });
setInterval(function() {
    fetch('/snapshot', {method:'HEAD'})
        .then(function(r) { setOnline(r.ok); })
        .catch(function() { setOnline(false); });
}, 5000);

// ══════════════════════════════════════════════════
//  Camera settings API
// ══════════════════════════════════════════════════
function updateSetting(key, value) {
    var body = {}; body[key] = value;
    fetch('/api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    }).then(function(r) { return r.json(); })
      .then(syncUI)
      .catch(function(e) { console.error('Settings error:', e); });
}

function syncUI(s) {
    document.getElementById('qualitySlider').value = s.jpeg_quality;
    document.getElementById('qualityVal').textContent = s.jpeg_quality;
    document.getElementById('fpsSlider').value = s.fps;
    document.getElementById('fpsVal').textContent = s.fps;
    if (s.rotation !== undefined) {
        document.querySelectorAll('.rot-btn').forEach(function(btn) {
            btn.classList.toggle('active', parseInt(btn.dataset.rot) === s.rotation);
        });
    }
}

fetch('/api/settings').then(function(r) { return r.json(); }).then(syncUI).catch(function() {});

// ══════════════════════════════════════════════════
//  Rotation (collapsible)
// ══════════════════════════════════════════════════
var rotationOpen = false;

function toggleRotationPanel() {
    rotationOpen = !rotationOpen;
    document.getElementById('rotationPanel').classList.toggle('open', rotationOpen);
    document.getElementById('rotCollapseIcon').classList.toggle('rotated', rotationOpen);
}

function setRotation(deg) {
    updateSetting('rotation', deg);
    document.querySelectorAll('.rot-btn').forEach(function(btn) {
        btn.classList.toggle('active', parseInt(btn.dataset.rot) === deg);
    });
}

// ══════════════════════════════════════════════════
//  Detection API
// ══════════════════════════════════════════════════
var detToggle    = document.getElementById('detToggle');
var allObjToggle = document.getElementById('allObjToggle');
var detBadge     = document.getElementById('detCountBadge');
var detEnabled   = false;

function updateDetection(key, value) {
    var body = {}; body[key] = value;
    fetch('/api/detection', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    }).then(function(r) { return r.json(); })
      .then(syncDetectionUI)
      .catch(function(e) { console.error('Detection error:', e); });
}

function toggleDetection() {
    detEnabled = !detEnabled;
    updateDetection('enabled', detEnabled);
    detToggle.classList.toggle('on', detEnabled);
}

function toggleAllObjects() {
    var on = !allObjToggle.classList.contains('on');
    updateDetection('draw_all_objects', on);
    allObjToggle.classList.toggle('on', on);
}

function syncDetectionUI(s) {
    detEnabled = s.enabled;
    detToggle.classList.toggle('on', s.enabled);
    allObjToggle.classList.toggle('on', s.draw_all_objects);

    document.getElementById('confSlider').value = Math.round(s.confidence * 100);
    document.getElementById('confVal').textContent = Math.round(s.confidence * 100) + '%';
    document.getElementById('intervalSlider').value = s.detect_interval;
    document.getElementById('intervalVal').textContent = s.detect_interval;

    var count = s.detections ? s.detections.length : 0;
    detBadge.textContent = count + (count === 1 ? ' object' : ' objects');
    detBadge.classList.toggle('empty', count === 0);
}

fetch('/api/detection').then(function(r) { return r.json(); }).then(syncDetectionUI).catch(function() {});
setInterval(function() {
    if (detEnabled) {
        fetch('/api/detection').then(function(r) { return r.json(); }).then(syncDetectionUI).catch(function() {});
    }
}, 3000);

// ══════════════════════════════════════════════════
//  Actions
// ══════════════════════════════════════════════════
function takeSnapshot() {
    var a = document.createElement('a');
    a.href = '/snapshot'; a.download = 'snapshot_' + Date.now() + '.jpg'; a.click();
}

function toggleFullscreen() {
    var el = document.getElementById('videoWrapper');
    if (!document.fullscreenElement) el.requestFullscreen().catch(function() {});
    else document.exitFullscreen();
}

// ══════════════════════════════════════════════════
//  System Stats
// ══════════════════════════════════════════════════
var statsPanel = document.getElementById('statsPanel');
var statsOpen  = false;
var statsTimer = null;

function toggleStatsPanel() {
    statsOpen = !statsOpen;
    statsPanel.classList.toggle('open', statsOpen);
    if (statsOpen) {
        if (logOpen) { logOpen = false; logPanel.classList.remove('open'); }
        fetchStats();
        statsTimer = setInterval(fetchStats, 5000);
    } else {
        if (statsTimer) { clearInterval(statsTimer); statsTimer = null; }
    }
}

function barColor(pct) {
    if (pct >= 85) return 'red';
    if (pct >= 60) return 'yellow';
    return 'green';
}

function setBar(barEl, pct) {
    barEl.style.width = pct + '%';
    barEl.className = 'stat-bar-fill ' + barColor(pct);
}

function fetchStats() {
    fetch('/api/stats')
        .then(function(r) { return r.json(); })
        .then(function(s) {
            if (s.cpu_percent !== null) {
                document.getElementById('statCpu').textContent = s.cpu_percent + '%';
                setBar(document.getElementById('statCpuBar'), s.cpu_percent);
            } else {
                document.getElementById('statCpu').textContent = 'N/A';
            }

            if (s.ram_percent !== null) {
                document.getElementById('statRam').textContent = s.ram_percent + '%';
                document.getElementById('statRamSub').textContent = s.ram_used_mb + ' / ' + s.ram_total_mb + ' MB';
                setBar(document.getElementById('statRamBar'), s.ram_percent);
            } else {
                document.getElementById('statRam').textContent = 'N/A';
            }

            if (s.disk_percent !== null) {
                document.getElementById('statDisk').textContent = s.disk_percent + '%';
                document.getElementById('statDiskSub').textContent = s.disk_used_gb + ' / ' + s.disk_total_gb + ' GB';
                setBar(document.getElementById('statDiskBar'), s.disk_percent);
            } else {
                document.getElementById('statDisk').textContent = 'N/A';
            }

            if (s.cpu_temp !== null) {
                var tempColor = s.cpu_temp >= 70 ? 'var(--red)' : s.cpu_temp >= 55 ? '#f0b040' : 'var(--green)';
                document.getElementById('statTemp').innerHTML = s.cpu_temp + '°C';
                document.getElementById('statTemp').style.color = tempColor;
            } else {
                document.getElementById('statTemp').textContent = 'N/A';
            }

            document.getElementById('statUptime').textContent = s.uptime || 'N/A';
        })
        .catch(function() {});
}

// ══════════════════════════════════════════════════
//  Server Logs
// ══════════════════════════════════════════════════
var logPanel      = document.getElementById('logPanel');
var logBody       = document.getElementById('logBody');
var logCountEl    = document.getElementById('logCount');
var autoScrollBtn = document.getElementById('autoScrollBtn');
var logAutoScroll = true;
var logOpen       = false;
var knownLogCount = 0;
var logLines      = [];

function toggleLogPanel() {
    logOpen = !logOpen;
    logPanel.classList.toggle('open', logOpen);
    if (logOpen) {
        if (statsOpen) { statsOpen = false; statsPanel.classList.remove('open'); if (statsTimer) { clearInterval(statsTimer); statsTimer = null; } }
        fetchLogs();
    }
}

function toggleAutoScroll() {
    logAutoScroll = !logAutoScroll;
    autoScrollBtn.classList.toggle('active', logAutoScroll);
    if (logAutoScroll) scrollLogToBottom();
}

function clearLogs() {
    logLines = [];
    knownLogCount = 0;
    renderLogs([]);
}

function scrollLogToBottom() {
    logBody.scrollTop = logBody.scrollHeight;
}

function getLogLevel(line) {
    if (line.indexOf('[ERROR]') !== -1 || line.indexOf('[CRITICAL]') !== -1) return 'error';
    if (line.indexOf('[WARNING]') !== -1) return 'warning';
    if (line.indexOf('[INFO]') !== -1) return 'info';
    return '';
}

function renderLogs(lines, newCount) {
    if (lines.length === 0) {
        logBody.innerHTML = '<div class="log-empty">No logs yet...</div>';
        logCountEl.textContent = '0';
        return;
    }
    logCountEl.textContent = lines.length;

    var fragment = document.createDocumentFragment();

    if (!newCount || newCount >= lines.length) {
        logBody.innerHTML = '';
        for (var i = 0; i < lines.length; i++) {
            var div = document.createElement('div');
            div.className = 'log-line';
            var lvl = getLogLevel(lines[i]);
            if (lvl) div.classList.add('lvl-' + lvl);
            div.textContent = lines[i];
            fragment.appendChild(div);
        }
    } else {
        var startIdx = Math.max(0, lines.length - newCount);
        for (var j = startIdx; j < lines.length; j++) {
            var div2 = document.createElement('div');
            div2.className = 'log-line new-line';
            var lvl2 = getLogLevel(lines[j]);
            if (lvl2) div2.classList.add('lvl-' + lvl2);
            div2.textContent = lines[j];
            fragment.appendChild(div2);
        }
    }
    logBody.appendChild(fragment);

    while (logBody.children.length > 500) {
        logBody.removeChild(logBody.firstChild);
    }

    if (logAutoScroll) scrollLogToBottom();
}

function fetchLogs() {
    fetch('/api/logs?n=200')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var newLines = data.lines;
            var newCount = newLines.length - logLines.length;

            if (newLines.length !== logLines.length ||
                (newLines.length > 0 && newLines[newLines.length-1] !== logLines[logLines.length-1])) {
                var actualNew = newCount > 0 ? newCount : newLines.length;
                logLines = newLines;
                if (actualNew === newLines.length) {
                    renderLogs(logLines);
                } else {
                    renderLogs(logLines, actualNew);
                }
            }
            knownLogCount = data.total;
        })
        .catch(function() {});
}

setInterval(function() {
    if (logOpen) fetchLogs();
}, 2000);

fetchLogs();
