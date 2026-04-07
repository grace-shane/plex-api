/*
 * plex-api · endpoint tester
 * Minimal, no framework. Vanilla DOM.
 */
(() => {
    "use strict";

    // ── DOM ─────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const methodEl   = $("#method");
    const pathEl     = $("#path-input");
    const paramsEl   = $("#params-input");
    const urlHostEl  = $("#url-host");
    const sendBtn    = $("#btn-send");
    const envChipEl  = $("#env-chip");
    const writesChipEl = $("#writes-chip");

    const statusStripEl = $("#status-strip");
    const respPre       = $("#resp-pre");
    const tabsEl        = $$(".tab");
    const copyBtn       = $("#btn-copy");
    const clearBtn      = $("#btn-clear");
    const clearHistBtn  = $("#btn-clear-history");
    const historyListEl = $("#history-list");

    const btnPickFiles  = $("#btn-pick-files");
    const btnPickDir    = $("#btn-pick-dir");
    const fileInput     = $("#fusion-file-input");
    const dirInput      = $("#fusion-dir-input");

    // ── State ───────────────────────────────────────
    const state = {
        activeTab: "body",
        lastResponse: null,     // { body, headers, raw, http_status, elapsed_ms, size_bytes, method, url }
        history: [],
        maxHistory: 20,
    };

    // ── Boot ────────────────────────────────────────
    loadConfig();
    wireEvents();
    renderHistory();

    async function loadConfig() {
        try {
            const r = await fetch("/api/config");
            const cfg = await r.json();
            urlHostEl.textContent = `${cfg.base_url}/`;

            // Environment chip
            envChipEl.textContent = cfg.environment === "production" ? "PROD" : "TEST";
            envChipEl.classList.remove("test", "prod");
            envChipEl.classList.add(cfg.is_production ? "prod" : "test");
            envChipEl.title =
                `Tenant ${cfg.tenant_id || "(default)"} · ` +
                `key:${cfg.has_key ? "✓" : "✗"} ` +
                `secret:${cfg.has_secret ? "✓" : "✗"}`;

            // Writes chip — only meaningful in production
            if (cfg.is_production) {
                writesChipEl.classList.remove("hidden");
                if (cfg.writes_allowed) {
                    writesChipEl.textContent = "WRITES ON";
                    writesChipEl.classList.remove("blocked");
                    writesChipEl.classList.add("allowed");
                    writesChipEl.title =
                        "PLEX_ALLOW_WRITES is set. POST/PUT/PATCH/DELETE to " +
                        "production are ENABLED. Every mutating call hits real " +
                        "Grace Engineering production data.";
                } else {
                    writesChipEl.textContent = "READ ONLY";
                    writesChipEl.classList.remove("allowed");
                    writesChipEl.classList.add("blocked");
                    writesChipEl.title =
                        "Production write guard active. POST/PUT/PATCH/DELETE " +
                        "to production are blocked at the proxy. To enable, set " +
                        "PLEX_ALLOW_WRITES=1 in the environment and restart.";
                }
            } else {
                writesChipEl.classList.add("hidden");
            }
        } catch (e) {
            envChipEl.textContent = "offline";
        }
    }

    function wireEvents() {
        // Send button
        sendBtn.addEventListener("click", send);

        // Ctrl/Cmd+Enter to send
        document.addEventListener("keydown", (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                e.preventDefault();
                send();
            }
        });

        // Presets
        $$(".preset").forEach((btn) => {
            btn.addEventListener("click", () => {
                const internal = btn.getAttribute("data-internal");
                if (internal) {
                    runInternal(internal, btn.querySelector(".p")?.textContent || internal);
                    return;
                }
                const m = btn.getAttribute("data-method") || "GET";
                const p = btn.getAttribute("data-path") || "";
                methodEl.value = m;
                pathEl.value = p;
                pathEl.focus();
            });
        });

        // Tabs
        tabsEl.forEach((tab) => {
            tab.addEventListener("click", () => {
                tabsEl.forEach((t) => t.classList.remove("active"));
                tab.classList.add("active");
                state.activeTab = tab.getAttribute("data-tab");
                renderResponseTab();
            });
        });

        copyBtn.addEventListener("click", copyResponse);
        clearBtn.addEventListener("click", clearResponse);
        clearHistBtn.addEventListener("click", () => {
            state.history = [];
            renderHistory();
        });

        // Fusion local uploads
        if (btnPickFiles && fileInput) {
            btnPickFiles.addEventListener("click", () => fileInput.click());
            fileInput.addEventListener("change", handleFileSelect);
        }
        if (btnPickDir && dirInput) {
            btnPickDir.addEventListener("click", () => dirInput.click());
            dirInput.addEventListener("change", handleFileSelect);
        }
    }

    // ── Core: send via proxy ────────────────────────
    async function send() {
        const path = pathEl.value.trim().replace(/^\/+/, "");
        const method = methodEl.value;
        if (!path) {
            setStatusStrip({ error: "Missing path" });
            pathEl.focus();
            return;
        }

        const qs = new URLSearchParams();
        qs.set("path", path);

        if (paramsEl.value.trim()) {
            const extra = parseParams(paramsEl.value.trim());
            for (const [k, v] of extra) qs.append(k, v);
        }

        const url = `/api/plex/raw?${qs.toString()}`;

        setLoading(true, `${method} ${path}`);
        const started = performance.now();
        try {
            const r = await fetch(url, { method });
            const data = await r.json();
            const elapsed = Math.round(performance.now() - started);

            const resp = {
                method,
                path,
                http_status: data.http_status ?? 0,
                http_reason: data.http_reason || "",
                elapsed_ms: data.elapsed_ms ?? elapsed,
                size_bytes: data.size_bytes ?? 0,
                url: data.url || "",
                headers: data.headers || {},
                body: data.body ?? data,
                raw: data,
            };
            state.lastResponse = resp;
            setStatusStripFromResponse(resp);
            renderResponseTab();
            pushHistory(resp);
        } catch (err) {
            state.lastResponse = {
                error: err.message,
                raw: { error: err.message },
                headers: {},
                body: null,
            };
            setStatusStrip({ error: err.message });
            respPre.textContent = `// fetch failed\n${err.message}`;
        } finally {
            setLoading(false);
        }
    }

    // ── Internal (non-proxy) endpoints ──────────────
    async function runInternal(endpoint, label) {
        setLoading(true, `RUN ${label}`);
        const started = performance.now();
        try {
            const r = await fetch(endpoint);
            const data = await r.json();
            const elapsed = Math.round(performance.now() - started);
            const text = JSON.stringify(data, null, 2);

            const resp = {
                method: "RUN",
                path: endpoint,
                http_status: r.status,
                http_reason: r.statusText,
                elapsed_ms: elapsed,
                size_bytes: new Blob([text]).size,
                url: endpoint,
                headers: Object.fromEntries(r.headers.entries()),
                body: data,
                raw: data,
            };
            state.lastResponse = resp;
            setStatusStripFromResponse(resp);
            renderResponseTab();
            pushHistory(resp);
        } catch (err) {
            setStatusStrip({ error: err.message });
            respPre.textContent = `// fetch failed\n${err.message}`;
        } finally {
            setLoading(false);
        }
    }

    // ── Fusion file upload ──────────────────────────
    async function handleFileSelect(e) {
        const files = e.target.files;
        if (!files || files.length === 0) return;

        const fd = new FormData();
        let added = 0;
        for (let i = 0; i < files.length; i++) {
            if (files[i].name.toLowerCase().endsWith(".json")) {
                fd.append(`file_${i}`, files[i]);
                added++;
            }
        }
        if (added === 0) {
            setStatusStrip({ error: "No .json files in selection" });
            return;
        }

        setLoading(true, `UPLOAD ${added} file${added === 1 ? "" : "s"}`);
        const started = performance.now();
        try {
            const r = await fetch("/api/fusion/tools", { method: "POST", body: fd });
            const data = await r.json();
            const elapsed = Math.round(performance.now() - started);
            const text = JSON.stringify(data, null, 2);

            const resp = {
                method: "POST",
                path: "/api/fusion/tools",
                http_status: r.status,
                http_reason: r.statusText,
                elapsed_ms: elapsed,
                size_bytes: new Blob([text]).size,
                url: "/api/fusion/tools",
                headers: Object.fromEntries(r.headers.entries()),
                body: data,
                raw: data,
            };
            state.lastResponse = resp;
            setStatusStripFromResponse(resp);
            renderResponseTab();
            pushHistory(resp);
        } catch (err) {
            setStatusStrip({ error: err.message });
            respPre.textContent = `// upload failed\n${err.message}`;
        } finally {
            setLoading(false);
            e.target.value = "";
        }
    }

    // ── Status strip ────────────────────────────────
    function setStatusStrip({ error } = {}) {
        if (error) {
            statusStripEl.innerHTML = `<span class="ss-status err">ERROR</span><span class="ss-item"><span class="v">${escapeHtml(error)}</span></span>`;
            return;
        }
        statusStripEl.innerHTML = `<span class="ss-idle">Ready · Ctrl+Enter to send</span>`;
    }

    function setStatusStripFromResponse(r) {
        const status = r.http_status;
        let cls = "info";
        if (status >= 200 && status < 300) cls = "ok";
        else if (status >= 300 && status < 400) cls = "warn";
        else if (status >= 400) cls = "err";
        else if (status === 0) cls = "err";

        const label = status ? `${status} ${r.http_reason || ""}`.trim() : "NO RESP";

        statusStripEl.innerHTML = `
            <span class="ss-status ${cls}">${escapeHtml(label)}</span>
            <span class="ss-item"><span class="k">time</span><span class="v">${r.elapsed_ms}ms</span></span>
            <span class="ss-item"><span class="k">size</span><span class="v">${formatBytes(r.size_bytes)}</span></span>
            <span class="ss-item"><span class="k">${r.method}</span><span class="v">${escapeHtml(r.path)}</span></span>
        `;
    }

    function setLoading(isLoading, label) {
        sendBtn.disabled = isLoading;
        if (isLoading) {
            statusStripEl.innerHTML = `<span class="ss-loading">… ${escapeHtml(label || "sending")}</span>`;
            respPre.classList.add("empty");
            respPre.textContent = "// waiting for response";
        }
    }

    // ── Response rendering ──────────────────────────
    function renderResponseTab() {
        const r = state.lastResponse;
        if (!r) {
            respPre.classList.add("empty");
            respPre.textContent = "// Response will appear here";
            return;
        }
        respPre.classList.remove("empty");

        if (state.activeTab === "headers") {
            const lines = Object.entries(r.headers || {})
                .map(([k, v]) => `${k}: ${v}`)
                .join("\n");
            respPre.textContent = lines || "// no headers";
            return;
        }

        if (state.activeTab === "raw") {
            respPre.textContent = JSON.stringify(r.raw, null, 2);
            return;
        }

        // body tab — try to render just the body nicely
        const body = r.body;
        if (body == null) {
            respPre.textContent = "// empty body";
            return;
        }
        if (typeof body === "string") {
            respPre.textContent = body;
            return;
        }
        try {
            respPre.innerHTML = syntaxHighlight(JSON.stringify(body, null, 2));
        } catch {
            respPre.textContent = String(body);
        }
    }

    function syntaxHighlight(json) {
        const esc = escapeHtml(json);
        return esc.replace(
            /(&quot;(\\.|[^&])*?&quot;)(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,
            (match, strMatch, _c, colon) => {
                if (strMatch !== undefined) {
                    return colon
                        ? `<span class="json-key">${strMatch}</span>${colon}`
                        : `<span class="json-str">${strMatch}</span>`;
                }
                if (match === "true" || match === "false") return `<span class="json-bool">${match}</span>`;
                if (match === "null") return `<span class="json-null">${match}</span>`;
                return `<span class="json-num">${match}</span>`;
            }
        );
    }

    // ── Copy / clear ────────────────────────────────
    async function copyResponse() {
        const txt = respPre.textContent || "";
        try {
            await navigator.clipboard.writeText(txt);
            flashBtn(copyBtn, "Copied");
        } catch {
            flashBtn(copyBtn, "Fail");
        }
    }

    function clearResponse() {
        state.lastResponse = null;
        respPre.classList.add("empty");
        respPre.textContent = "// Response will appear here";
        setStatusStrip();
    }

    function flashBtn(btn, text) {
        const prev = btn.textContent;
        btn.textContent = text;
        setTimeout(() => (btn.textContent = prev), 900);
    }

    // ── History ─────────────────────────────────────
    function pushHistory(r) {
        const item = {
            method: r.method,
            path: r.path,
            http_status: r.http_status,
            elapsed_ms: r.elapsed_ms,
            ts: Date.now(),
            snapshot: r,
        };
        state.history.unshift(item);
        state.history = state.history.slice(0, state.maxHistory);
        renderHistory();
    }

    function renderHistory() {
        historyListEl.innerHTML = "";
        if (state.history.length === 0) {
            const li = document.createElement("li");
            li.className = "history-empty";
            li.textContent = "No requests yet";
            historyListEl.appendChild(li);
            return;
        }
        state.history.forEach((item, idx) => {
            const li = document.createElement("li");
            const btn = document.createElement("button");
            let cls = "history-item";
            if (item.http_status >= 200 && item.http_status < 300) cls += " ok";
            else if (item.http_status >= 300 && item.http_status < 400) cls += " warn";
            else cls += " err";
            btn.className = cls;
            btn.innerHTML = `
                <span class="h-status">${item.http_status || "—"}</span>
                <span class="h-path">${escapeHtml(item.path)}</span>
                <span class="h-time">${item.elapsed_ms}ms</span>
            `;
            btn.addEventListener("click", () => {
                state.lastResponse = item.snapshot;
                setStatusStripFromResponse(item.snapshot);
                renderResponseTab();
            });
            li.appendChild(btn);
            historyListEl.appendChild(li);
        });
    }

    // ── Helpers ─────────────────────────────────────
    function parseParams(s) {
        // Accept "k=v&k2=v2" or one-per-line
        const out = [];
        const chunks = s.split(/[&\n]/);
        for (const chunk of chunks) {
            const t = chunk.trim();
            if (!t) continue;
            const i = t.indexOf("=");
            if (i === -1) out.push([t, ""]);
            else out.push([t.slice(0, i).trim(), t.slice(i + 1).trim()]);
        }
        return out;
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function formatBytes(n) {
        if (!n) return "0 B";
        const units = ["B", "KB", "MB", "GB"];
        let i = 0;
        while (n >= 1024 && i < units.length - 1) {
            n /= 1024;
            i++;
        }
        return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
    }
})();
