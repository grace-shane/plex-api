document.addEventListener('DOMContentLoaded', () => {
    
    const actionBtns = document.querySelectorAll('.action-btn');
    const loadingOverlay = document.getElementById('loading-overlay');
    const jsonOutput = document.getElementById('json-output');
    const formattedOutput = document.getElementById('formatted-output');
    const btnClear = document.getElementById('btn-clear');
    const viewTitle = document.getElementById('view-title');
    
    const btnPickFiles = document.getElementById('btn-pick-files');
    const btnPickDir = document.getElementById('btn-pick-dir');
    const fusionFileInput = document.getElementById('fusion-file-input');
    const fusionDirInput = document.getElementById('fusion-dir-input');
    
    // Clear console output
    btnClear.addEventListener('click', () => {
        jsonOutput.textContent = "Console cleared. Select an action...";
        jsonOutput.style.display = 'block';
        if (formattedOutput) formattedOutput.classList.add('hidden');
        viewTitle.textContent = "Ready";
        removeActiveStates();
    });
    
    // Handle action buttons
    actionBtns.forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const endpoint = btn.getAttribute('data-endpoint');
            const name = btn.getAttribute('data-name');
            
            // UI updates
            removeActiveStates();
            btn.classList.add('active');
            viewTitle.textContent = `Executing: ${name}`;
            
            await fetchData(endpoint);
        });
    });
    
    function removeActiveStates() {
        actionBtns.forEach(b => b.classList.remove('active'));
    }
    
    async function fetchData(url) {
        // Show loader
        loadingOverlay.classList.remove('hidden');
        jsonOutput.textContent = "Fetching data...";
        jsonOutput.style.display = 'block';
        if (formattedOutput) formattedOutput.classList.add('hidden');
        
        try {
            const response = await fetch(url);
            const data = await response.json();
            
            if (url.includes('/api/fusion/tools') && data.status === 'success') {
                renderFusionTools(data);
            } else {
                // Format JSON output beautifully
                jsonOutput.textContent = JSON.stringify(data, null, 4);
            }
            
        } catch (err) {
            console.error(err);
            jsonOutput.textContent = `CRITICAL ERROR: Unable to reach backend.\n\n${err.message}`;
        } finally {
            // Hide loader
            loadingOverlay.classList.add('hidden');
        }
    }

    function renderFusionTools(data) {
        jsonOutput.style.display = 'none';
        formattedOutput.classList.remove('hidden');
        formattedOutput.innerHTML = '';
        
        const header = document.createElement('div');
        header.className = 'formatted-header';
        header.innerHTML = `<h2>Successfully Loaded ${data.library_count} Libraries</h2>`;
        formattedOutput.appendChild(header);
        
        const grid = document.createElement('div');
        grid.className = 'library-grid';
        
        data.data.forEach(lib => {
            const card = document.createElement('div');
            card.className = 'library-card glass-panel';
            
            let toolsHtml = '';
            if (lib.tools_sample && lib.tools_sample.length > 0) {
                lib.tools_sample.forEach(tool => {
                    const desc = tool.description || tool.Description || 'Untitled Tool';
                    const type = tool.type || tool.Type || 'Unknown Type';
                    const num = (tool.postProcess && tool.postProcess.number !== undefined) ? tool.postProcess.number : (tool.id || '-');
                    
                    toolsHtml += `
                        <div class="tool-item">
                            <span class="tool-num">#${num}</span>
                            <span class="tool-desc">${desc}</span>
                            <span class="badge small-badge">${type}</span>
                        </div>
                    `;
                });
            } else {
                toolsHtml = `<div class="tool-item"><span class="tool-desc muted">No tools found</span></div>`;
            }
            
            card.innerHTML = `
                <div class="library-header">
                    <h4>${lib.library_name}</h4>
                    <span class="badge accent-badge">${lib.tool_count} Tools</span>
                </div>
                <div class="library-body">
                    <h5>Sample Tools</h5>
                    <div class="tools-list">
                        ${toolsHtml}
                    </div>
                </div>
                <div class="library-footer">
                    <button class="ghost-btn btn-sm view-raw-btn" data-lib="${lib.library_name}">View JSON</button>
                </div>
            `;
            
            // Add view raw JSON functionality
            const viewRawBtn = card.querySelector('.view-raw-btn');
            viewRawBtn.addEventListener('click', () => {
                const modalOverlay = document.createElement('div');
                modalOverlay.className = 'modal-overlay';
                modalOverlay.innerHTML = `
                    <div class="modal-content glass-panel">
                        <div class="modal-header">
                            <h4>${lib.library_name} JSON Sample</h4>
                            <button class="close-modal ghost-btn">Close</button>
                        </div>
                        <pre class="modal-body">${JSON.stringify(lib.tools_sample, null, 4)}</pre>
                    </div>
                `;
                document.body.appendChild(modalOverlay);
                
                modalOverlay.querySelector('.close-modal').addEventListener('click', () => {
                    document.body.removeChild(modalOverlay);
                });
            });
            
            grid.appendChild(card);
        });
        
        formattedOutput.appendChild(grid);
    }

    if (btnPickFiles && fusionFileInput) {
        btnPickFiles.addEventListener('click', () => fusionFileInput.click());
    }

    if (btnPickDir && fusionDirInput) {
        btnPickDir.addEventListener('click', () => fusionDirInput.click());
    }
    
    const handleFileSelect = async (e) => {
        const files = e.target.files;
        if (!files || files.length === 0) return;
        
        removeActiveStates();
        viewTitle.textContent = `Executing: Custom Selection`;
        loadingOverlay.classList.remove('hidden');
        jsonOutput.textContent = "Uploading and processing files...";
        jsonOutput.style.display = 'block';
        if (formattedOutput) formattedOutput.classList.add('hidden');
        
        try {
            const formData = new FormData();
            let added = 0;
            for (let i = 0; i < files.length; i++) {
                if (files[i].name.endsWith('.json')) {
                    formData.append('file_' + i, files[i]);
                    added++;
                }
            }
            
            if (added === 0) {
                throw new Error("No valid .json files were found in the selection.");
            }
            
            const response = await fetch('/api/fusion/tools', {
                method: 'POST',
                body: formData
            });
            const data = await response.json();
            
            if (data.status === 'success') {
                renderFusionTools(data);
            } else {
                jsonOutput.textContent = JSON.stringify(data, null, 4);
            }
        } catch (err) {
            console.error(err);
            jsonOutput.textContent = `CRITICAL ERROR: ${err.message}`;
        } finally {
            loadingOverlay.classList.add('hidden');
            e.target.value = ''; // Reset for re-selection
        }
    };

    if (fusionFileInput) fusionFileInput.addEventListener('change', handleFileSelect);
    if (fusionDirInput) fusionDirInput.addEventListener('change', handleFileSelect);

});
