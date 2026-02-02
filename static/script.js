
document.addEventListener('DOMContentLoaded', () => {

    // --- Elements ---
    const kmlDropZone = document.getElementById('kmlDropZone');
    const kmlInput = document.getElementById('kmlInput');
    const polygonOutput = document.getElementById('polygonOutput');
    const copyPolygonBtn = document.getElementById('copyPolygonBtn');

    const metaDropZone = document.getElementById('metaDropZone');
    const metaInput = document.getElementById('metaInput');

    const downloadReliefBtn = document.getElementById('downloadReliefBtn');
    const progressList = document.getElementById('progressList');

    let progressInterval = null;

    // --- Helpers ---
    function setupDragDrop(zone, input, callback) {
        zone.addEventListener('click', () => input.click());

        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('dragover');
        });

        zone.addEventListener('dragleave', () => {
            zone.classList.remove('dragover');
        });

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                callback(e.dataTransfer.files[0]);
            }
        });

        input.addEventListener('change', () => {
            if (input.files.length) {
                callback(input.files[0]);
            }
        });
    }

    // --- KML Logic ---
    setupDragDrop(kmlDropZone, kmlInput, async (file) => {
        const formData = new FormData();
        formData.append('file', file);

        try {
            const resp = await fetch('/analyze-kml', { method: 'POST', body: formData });
            const data = await resp.json();

            if (resp.ok) {
                polygonOutput.value = data.polygon;
            } else {
                alert('Error: ' + data.error);
            }
        } catch (e) {
            alert('Upload failed: ' + e);
        }
    });

    copyPolygonBtn.addEventListener('click', () => {
        polygonOutput.select();
        document.execCommand('copy');
        copyPolygonBtn.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
        setTimeout(() => copyPolygonBtn.innerHTML = '<i class="fa-regular fa-copy"></i> Copy to Clipboard', 2000);
    });

    // --- Metalink Logic ---
    setupDragDrop(metaDropZone, metaInput, async (file) => {
        const formData = new FormData();
        formData.append('file', file);

        try {
            startPolling();
            const resp = await fetch('/start-download-metalink', { method: 'POST', body: formData });
            if (!resp.ok) {
                const data = await resp.json();
                alert('Error: ' + data.error);
            }
        } catch (e) {
            alert('Start download failed: ' + e);
        }
    });

    // --- Relief Logic ---
    downloadReliefBtn.addEventListener('click', async () => {
        const poly = polygonOutput.value.trim();
        if (!poly) {
            alert('Please extract a polygon first!');
            return;
        }

        const formData = new FormData();
        formData.append('polygon', poly);

        try {
            startPolling();
            const resp = await fetch('/start-download-relief', { method: 'POST', body: formData });
            if (!resp.ok) {
                const data = await resp.json();
                alert('Error: ' + data.error);
            }
        } catch (e) {
            alert('Start download failed: ' + e);
        }
    });

    // --- Progress Polling ---
    function startPolling() {
        if (progressInterval) return;
        progressList.innerHTML = ''; // Clear old list
        progressInterval = setInterval(updateProgress, 1000);
        updateProgress(); // Immediate call
    }

    async function updateProgress() {
        try {
            const resp = await fetch('/progress');
            const data = await resp.json();

            // Check if anything is active
            const fileNames = Object.keys(data);
            if (fileNames.length === 0) return;

            // Render
            let html = '';
            let allComplete = true;

            fileNames.forEach(fname => {
                const info = data[fname];
                if (info.status !== 'Completed' && info.status !== 'Skipped (Exists)') {
                    allComplete = false;
                }

                html += `
                    <div class="progress-item">
                        <div class="file-name" title="${fname}">${fname}</div>
                        <div class="progress-bar-bg">
                            <div class="progress-bar-fill" style="width: ${info.percent}%"></div>
                        </div>
                        <div class="status-text">${info.percent}%</div>
                    </div>
                `;
            });

            progressList.innerHTML = html;

        } catch (e) {
            console.error('Polling error', e);
        }
    }
});
