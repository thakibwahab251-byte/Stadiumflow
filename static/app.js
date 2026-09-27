/**
 * static/app.js - StadiumFlow Frontend Controller
 * 
 * Drives interactive stadium SVG mapping, dynamic Bézier rerouting lines,
 * Gemini Multimodal Vision queue scanning, and real-time crowd pulse updates.
 */

// Global Application State
const state = {
    zones: [],
    selectedZoneId: "food_north",
    autoTickTimer: null,
    reroutesCompleted: 142,
    activeImageFile: null,
    activeScenario: null
};

// SVG Canvas Dimensions
const SVG_WIDTH = 800;
const SVG_HEIGHT = 500;

// Type Icons Mapping
const TYPE_ICONS = {
    gate: "🚪",
    food_court: "🍔",
    concession: "🍔",
    restroom: "🚻",
    help_desk: "ℹ️",
    medical_room: "🩺",
    merch: "🛍️",
    service: "🩺"
};

// Initialize on DOM Ready
document.addEventListener("DOMContentLoaded", () => {
    initEventListeners();
    fetchVenueData();
});

/**
 * Attaches UI event listeners for buttons, uploads, and scenarios.
 */
function initEventListeners() {
    // Top Bar Simulation Controls
    document.getElementById("btnSimulateTick").addEventListener("click", stepSimulation);
    document.getElementById("btnToggleAutoTick").addEventListener("click", toggleAutoSimulation);
    document.getElementById("btnResetState").addEventListener("click", resetVenueState);

    // Match Phase Selector
    const phaseSelect = document.getElementById("selectMatchPhase");
    if (phaseSelect) {
        phaseSelect.addEventListener("change", async (e) => {
            const phase = e.target.value;
            try {
                const res = await fetch("/api/phase", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ phase })
                });
                const data = await res.json();
                if (data.success) {
                    state.zones = data.zones;
                    updateDashboardMetrics(data.summary);
                    renderStadiumMapNodes();
                    selectZone(state.selectedZoneId);
                    showToast(`Match phase set to: ${phase.replace('_', ' ').toUpperCase()} (wait times updated)`, "info");
                }
            } catch (err) {
                console.error("Failed to update phase:", err);
            }
        });
    }

    // Smart Wayfinder (best_option) Button
    const btnBestOption = document.getElementById("btnFindBestOption");
    if (btnBestOption) {
        btnBestOption.addEventListener("click", async () => {
            const need = document.getElementById("wayfinderNeed").value;
            const userZone = document.getElementById("wayfinderZone").value;
            try {
                const res = await fetch("/api/best-option", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ need, user_zone: userZone })
                });
                const data = await res.json();
                if (data.success && data.best_option) {
                    const opt = data.best_option;
                    document.getElementById("wfTitle").textContent = `${opt.name} (${opt.zone} Zone)`;
                    document.getElementById("wfTotalTime").textContent = `${opt.total_time} min total`;
                    document.getElementById("wfBreakdown").textContent = `🚶 ${opt.walking_time} min walk + ⏳ ${opt.waiting_time} min wait`;
                    document.getElementById("wfDesc").textContent = opt.recommendation;
                    document.getElementById("wayfinderResult").style.display = "flex";
                    selectZone(opt.id);
                    showToast(`Optimal facility found: ${opt.name} (${opt.total_time}m total)`, "success");
                }
            } catch (err) {
                console.error("Wayfinder error:", err);
            }
        });
    }

    // Selected Zone Action Buttons
    document.getElementById("btnTriggerReroute").addEventListener("click", () => {
        calculateAndDisplayReroute(state.selectedZoneId);
    });

    document.getElementById("btnBroadcastAdvisory").addEventListener("click", () => {
        broadcastZoneAdvisory(state.selectedZoneId);
    });

    document.getElementById("btnLoadZoneIntoScanner").addEventListener("click", () => {
        const zoneSelect = document.getElementById("selectTargetZone");
        zoneSelect.value = state.selectedZoneId;
        zoneSelect.scrollIntoView({ behavior: "smooth", block: "center" });
        showToast(`Target zone set to: ${getZoneById(state.selectedZoneId)?.name}`, "info");
    });

    document.getElementById("btnApplyReroute").addEventListener("click", () => {
        state.reroutesCompleted += 28;
        document.getElementById("valReroutesCount").textContent = state.reroutesCompleted;
        showToast("Dynamic FastPath diversion broadcasted to fans & digital signs!", "success");
    });

    // Preset Demo Scenario Buttons
    document.querySelectorAll(".btn-scenario").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const scenario = btn.dataset.scenario;
            const zoneId = btn.dataset.zone;
            loadDemoScenario(scenario, zoneId);
        });
    });

    // File Upload & Dropzone
    const dropzone = document.getElementById("uploadDropzone");
    const fileInput = document.getElementById("fileInput");

    dropzone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", handleFileSelect);

    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("drag-over");
    });

    dropzone.addEventListener("dragleave", () => {
        dropzone.classList.remove("drag-over");
    });

    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("drag-over");
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleImageFile(e.dataTransfer.files[0]);
        }
    });

    document.getElementById("btnClearImage").addEventListener("click", (e) => {
        e.stopPropagation();
        clearUploadedImage();
    });

    // Vision Analysis Execution
    document.getElementById("btnRunVisionAnalysis").addEventListener("click", runGeminiVisionAnalysis);

    document.getElementById("btnAutoRerouteFromVision").addEventListener("click", () => {
        const targetZone = document.getElementById("selectTargetZone").value;
        selectZone(targetZone);
        calculateAndDisplayReroute(targetZone);
        state.reroutesCompleted += 34;
        document.getElementById("valReroutesCount").textContent = state.reroutesCompleted;
        showToast("Traffic diversion applied across concourse displays!", "success");
    });
}

/**
 * Fetches all zones and venue summary from the backend API.
 */
async function fetchVenueData() {
    try {
        const res = await fetch("/api/venue");
        const data = await res.json();
        if (data.success) {
            updateDashboardMetrics(data.summary);
        }

        const zonesRes = await fetch("/api/zones");
        const zonesData = await zonesRes.json();
        if (zonesData.success) {
            state.zones = zonesData.zones;
            renderStadiumMapNodes();
            selectZone(state.selectedZoneId);
        }
    } catch (err) {
        console.error("Failed to load venue data:", err);
        showToast("Error connecting to StadiumFlow API", "warning");
    }
}

/**
 * Updates top-level key performance metrics.
 */
function updateDashboardMetrics(summary) {
    if (!summary) return;

    document.getElementById("venueMatchInfo").textContent = `${summary.venue_name} • ${summary.event_phase}`;
    document.getElementById("venueAttendance").textContent = `👥 ${summary.attendance}`;

    document.getElementById("valCongestion").textContent = `${summary.congestion_index}%`;
    document.getElementById("barCongestion").style.width = `${summary.congestion_index}%`;

    document.getElementById("valAvgWait").innerHTML = `${summary.avg_wait_minutes}<span class="unit">min</span>`;
    document.getElementById("valChokepoints").textContent = summary.active_chokepoints;

    // Update announcement feed
    if (summary.latest_announcements) {
        renderAnnouncements(summary.latest_announcements);
    }
}

/**
 * Renders interactive SVG nodes for each stadium facility.
 */
function renderStadiumMapNodes() {
    const group = document.getElementById("svgZoneNodes");
    group.innerHTML = "";

    state.zones.forEach(zone => {
        const cx = (zone.map_coords.x / 100) * SVG_WIDTH;
        const cy = (zone.map_coords.y / 100) * SVG_HEIGHT;
        const color = getStatusColor(zone.status);
        const icon = TYPE_ICONS[zone.type] || "📍";
        const isSelected = zone.id === state.selectedZoneId;

        // Group container
        const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
        g.setAttribute("class", "zone-node-group");
        g.setAttribute("id", `node_${zone.id}`);
        g.setAttribute("transform", `translate(${cx}, ${cy})`);
        g.style.cursor = "pointer";

        // Pulsing ring if congested/critical or selected
        if (zone.status === "critical" || zone.status === "congested" || isSelected) {
            const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            ring.setAttribute("r", isSelected ? "24" : "20");
            ring.setAttribute("class", "zone-node-ring");
            ring.setAttribute("stroke", color);
            g.appendChild(ring);
        }

        // Base circle
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("r", isSelected ? "18" : "15");
        circle.setAttribute("class", "zone-node-bg");
        circle.setAttribute("fill", "#0f172a");
        circle.setAttribute("stroke", color);
        circle.setAttribute("stroke-width", isSelected ? "3.5" : "2");
        g.appendChild(circle);

        // Icon inside circle
        const textIcon = document.createElementNS("http://www.w3.org/2000/svg", "text");
        textIcon.setAttribute("text-anchor", "middle");
        textIcon.setAttribute("y", "4");
        textIcon.setAttribute("font-size", isSelected ? "13" : "11");
        textIcon.textContent = icon;
        g.appendChild(textIcon);

        // Wait time badge below node
        const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
        label.setAttribute("text-anchor", "middle");
        label.setAttribute("y", isSelected ? "28" : "24");
        label.setAttribute("class", "zone-node-label");
        label.setAttribute("fill", color);
        label.textContent = `${zone.wait_time_minutes}m`;
        g.appendChild(label);

        // Click event
        g.addEventListener("click", () => {
            selectZone(zone.id);
        });

        group.appendChild(g);
    });
}

/**
 * Returns hexadecimal color for zone congestion statuses.
 */
function getStatusColor(status) {
    switch (status) {
        case "critical": return "#ef4444";
        case "congested": return "#f97316";
        case "moderate": return "#f59e0b";
        default: return "#10b981";
    }
}

/**
 * Handles selection of a zone, updating the focus card and drawing fast-path lines.
 */
function selectZone(zoneId) {
    state.selectedZoneId = zoneId;
    const zone = getZoneById(zoneId);
    if (!zone) return;

    // Update Zone Focus Card DOM
    document.getElementById("zoneBadgeType").textContent = zone.type.toUpperCase();
    document.getElementById("zoneName").textContent = zone.name;
    document.getElementById("zoneSection").textContent = `${zone.section} • Capacity ${zone.capacity}`;

    const waitElem = document.getElementById("zoneWaitTime");
    waitElem.textContent = `${zone.wait_time_minutes} min`;
    waitElem.className = `stat-number text-${zone.status === "normal" ? "emerald" : (zone.status === "moderate" ? "amber" : "crimson")}`;

    document.getElementById("zoneHeadcount").textContent = zone.current_count;
    document.getElementById("zoneDescription").textContent = zone.description;

    // Highlight node in SVG
    renderStadiumMapNodes();

    // Check if congested, show alternative banner
    if (zone.status === "critical" || zone.status === "congested" || zone.wait_time_minutes >= 8) {
        calculateAndDisplayReroute(zoneId);
    } else {
        document.getElementById("alternativeBanner").style.display = "none";
        clearRerouteLine();
    }
}

/**
 * Finds the fastest alternative facility and renders dynamic Bézier SVG connector line.
 */
async function calculateAndDisplayReroute(zoneId) {
    try {
        const res = await fetch("/api/reroute", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ zone_id: zoneId })
        });
        const data = await res.json();

        if (data.success && data.reroute) {
            const alt = data.reroute;
            const fromZone = alt.from_zone;
            const toZone = alt.recommended_zone;
            const timeSaved = alt.time_saved_minutes;

            // Render FastPath Banner
            const banner = document.getElementById("alternativeBanner");
            banner.style.display = "flex";
            document.getElementById("altBannerText").innerHTML =
                `Divert to <strong>${toZone.name}</strong> (${toZone.wait_time_minutes}m wait) — <strong>Saves ~${timeSaved} mins!</strong>`;

            // Draw animated curved connector on the SVG
            drawRerouteLine(fromZone.map_coords, toZone.map_coords);
            showToast(`FastPath computed: Divert to ${toZone.name} to save ~${timeSaved}m`, "info");
        } else {
            document.getElementById("alternativeBanner").style.display = "none";
            clearRerouteLine();
        }
    } catch (err) {
        console.error("Reroute error:", err);
    }
}

/**
 * Draws an animated Bézier curve between two stadium coordinates on the SVG.
 */
function drawRerouteLine(fromCoords, toCoords) {
    const x1 = (fromCoords.x / 100) * SVG_WIDTH;
    const y1 = (fromCoords.y / 100) * SVG_HEIGHT;
    const x2 = (toCoords.x / 100) * SVG_WIDTH;
    const y2 = (toCoords.y / 100) * SVG_HEIGHT;

    // Control point pulled toward center pitch for stadium concourse routing
    const cx = (x1 + x2) / 2 + (400 - (x1 + x2) / 2) * 0.45;
    const cy = (y1 + y2) / 2 + (250 - (y1 + y2) / 2) * 0.45;

    const pathData = `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`;
    const pathElem = document.getElementById("svgReroutePath");
    pathElem.setAttribute("d", pathData);
}

/**
 * Clears the reroute line from the SVG.
 */
function clearRerouteLine() {
    document.getElementById("svgReroutePath").setAttribute("d", "");
}

/**
 * Triggers a live AI broadcast advisory for the congested zone.
 */
async function broadcastZoneAdvisory(zoneId) {
    try {
        const res = await fetch("/api/broadcast", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ zone_id: zoneId })
        });
        const data = await res.json();
        if (data.success) {
            renderAnnouncements(data.feed);
            showToast("Gemini Crowd Advisory broadcasted to concourse screens!", "success");
        }
    } catch (err) {
        console.error("Broadcast error:", err);
    }
}

/**
 * Handles preset scenario loading for instant demoing.
 */
function loadDemoScenario(scenarioKey, zoneId) {
    state.activeScenario = scenarioKey;
    state.activeImageFile = null;

    // Update target zone dropdown
    document.getElementById("selectTargetZone").value = zoneId;
    selectZone(zoneId);

    // Create synthetic preview canvas representation
    const previewWrapper = document.getElementById("previewWrapper");
    const dropzoneEmpty = document.getElementById("dropzoneEmpty");
    const imgPreview = document.getElementById("imagePreview");

    // Dynamic mock visual frame for the preview
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 360;
    const ctx = canvas.getContext("2d");

    // Background concourse
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Grid lines
    ctx.strokeStyle = "rgba(56, 189, 248, 0.15)";
    ctx.lineWidth = 1;
    for (let x = 0; x < canvas.width; x += 40) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, canvas.height);
        ctx.stroke();
    }

    // CCTV Timestamp HUD
    ctx.fillStyle = "#38bdf8";
    ctx.font = "bold 14px monospace";
    ctx.fillText(`CCTV CAM-${zoneId.toUpperCase()} • LIVE CONCOURSE FEED`, 24, 30);
    ctx.fillStyle = "#94a3b8";
    ctx.font = "12px monospace";
    ctx.fillText(`STREAM REC: ${new Date().toLocaleTimeString()} | 1080p 60fps`, 24, 52);

    // Draw silhouettes
    const isHeavy = scenarioKey.includes("congested");
    const count = isHeavy ? 36 : 8;

    for (let i = 0; i < count; i++) {
        const px = 60 + (i % 9) * 60 + (Math.sin(i) * 10);
        const py = 120 + Math.floor(i / 9) * 55;

        // Head
        ctx.fillStyle = isHeavy ? "#fca5a5" : "#86efac";
        ctx.beginPath();
        ctx.arc(px + 12, py, 10, 0, Math.PI * 2);
        ctx.fill();

        // Body
        ctx.fillStyle = isHeavy ? "rgba(239, 68, 68, 0.6)" : "rgba(16, 185, 129, 0.6)";
        ctx.fillRect(px, py + 12, 24, 32);
    }

    imgPreview.src = canvas.toDataURL("image/jpeg");
    previewWrapper.style.display = "flex";
    dropzoneEmpty.style.display = "none";

    showToast(`Loaded scenario: ${scenarioKey.replace('_', ' ')}`, "info");
}

/**
 * Handles user file selection for queue photo uploads.
 */
function handleFileSelect(e) {
    if (e.target.files && e.target.files[0]) {
        handleImageFile(e.target.files[0]);
    }
}

function handleImageFile(file) {
    if (!file.type.startsWith("image/")) {
        showToast("Please upload an image file (JPG, PNG, WebP)", "warning");
        return;
    }

    state.activeImageFile = file;
    state.activeScenario = null;

    const reader = new FileReader();
    reader.onload = (e) => {
        const imgPreview = document.getElementById("imagePreview");
        imgPreview.src = e.target.result;
        document.getElementById("previewWrapper").style.display = "flex";
        document.getElementById("dropzoneEmpty").style.display = "none";
    };
    reader.readAsDataURL(file);
    showToast("Photo loaded. Click 'Analyze Queue with Gemini AI'", "info");
}

function clearUploadedImage() {
    state.activeImageFile = null;
    state.activeScenario = null;
    document.getElementById("fileInput").value = "";
    document.getElementById("imagePreview").src = "";
    document.getElementById("previewWrapper").style.display = "none";
    document.getElementById("dropzoneEmpty").style.display = "block";
    document.getElementById("analysisResultsCard").style.display = "none";
}

/**
 * Calls Gemini Multimodal Vision to analyze queue headcount and bottlenecks.
 */
async function runGeminiVisionAnalysis() {
    const targetZoneId = document.getElementById("selectTargetZone").value;
    const laser = document.getElementById("scannerLaser");
    const resultsCard = document.getElementById("analysisResultsCard");
    const btnAnalyze = document.getElementById("btnRunVisionAnalysis");

    // Validate input
    if (!state.activeImageFile && !state.activeScenario) {
        showToast("Please upload a photo or pick a Quick Scenario first!", "warning");
        return;
    }

    // UI Loading state
    laser.style.display = "block";
    btnAnalyze.disabled = true;
    btnAnalyze.innerHTML = `<span>⏳ Gemini Vision Analyzing...</span>`;

    try {
        const formData = new FormData();
        formData.append("zone_id", targetZoneId);

        if (state.activeImageFile) {
            formData.append("image", state.activeImageFile);
        } else if (state.activeScenario) {
            formData.append("scenario", state.activeScenario);
        }

        const res = await fetch("/api/analyze-queue", {
            method: "POST",
            body: formData
        });

        const data = await res.json();

        if (data.success) {
            // Update zones and metrics
            state.zones = state.zones.map(z => z.id === targetZoneId ? data.zone : z);
            updateDashboardMetrics(data.summary);
            renderStadiumMapNodes();
            selectZone(targetZoneId);

            // Populate Analysis Results Card
            const analysis = data.analysis;
            document.getElementById("resConfidence").textContent = `${analysis.confidence_score || 94}% Confidence`;

            const densityBadge = document.getElementById("resDensityBadge");
            densityBadge.textContent = `${analysis.density_level?.toUpperCase()} DENSITY`;
            densityBadge.style.background = analysis.density_level === "Critical" ? "rgba(239, 68, 68, 0.25)" : "rgba(16, 185, 129, 0.25)";
            densityBadge.style.color = analysis.density_level === "Critical" ? "#fca5a5" : "#86efac";

            document.getElementById("resHeadcount").textContent = `${analysis.headcount} people`;
            document.getElementById("resWaitMinutes").textContent = `${analysis.estimated_wait_minutes} min`;
            document.getElementById("resFlowRate").textContent = analysis.queue_flow_rate || "Normal";

            document.getElementById("resBottleneck").textContent = analysis.bottleneck_reason;
            document.getElementById("resMarshalAction").textContent = analysis.marshal_action;
            document.getElementById("resFanAdvice").textContent = analysis.fan_advice;

            resultsCard.style.display = "flex";
            resultsCard.scrollIntoView({ behavior: "smooth", block: "nearest" });

            showToast(`Gemini Vision: ~${analysis.headcount} people detected (${analysis.estimated_wait_minutes}m wait)`, "success");
        } else {
            showToast(data.error || "Analysis failed", "warning");
        }
    } catch (err) {
        console.error("Gemini Vision analysis error:", err);
        showToast("Analysis connection error", "warning");
    } finally {
        laser.style.display = "none";
        btnAnalyze.disabled = false;
        btnAnalyze.innerHTML = `✨ Analyze Queue with Gemini AI`;
    }
}

/**
 * Renders the live announcements feed.
 */
function renderAnnouncements(announcements) {
    const list = document.getElementById("announcementsList");
    if (!list || !announcements) return;

    list.innerHTML = announcements.map(ann => `
        <div class="announcement-item ann-${ann.urgency}">
            <div class="ann-meta">
                <span class="ann-time">${ann.timestamp}</span>
                <span class="ann-urgency">${ann.urgency.toUpperCase()}</span>
            </div>
            <div class="ann-title">${ann.title}</div>
            <div class="ann-body">${ann.message}</div>
        </div>
    `).join("");
}

/**
 * Advances the simulation by 1 step.
 */
async function stepSimulation() {
    try {
        const res = await fetch("/api/simulate-tick", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            state.zones = data.zones;
            updateDashboardMetrics(data.summary);
            renderStadiumMapNodes();
            selectZone(state.selectedZoneId);
            showToast("Simulation stepped (+1 flow tick)", "info");
        }
    } catch (err) {
        console.error("Step simulation error:", err);
    }
}

/**
 * Toggles automated live simulation polling.
 */
function toggleAutoSimulation() {
    const label = document.getElementById("autoTickState");
    const btn = document.getElementById("btnToggleAutoTick");

    if (state.autoTickTimer) {
        clearInterval(state.autoTickTimer);
        state.autoTickTimer = null;
        label.textContent = "OFF";
        btn.classList.remove("btn-primary");
        btn.classList.add("btn-outline");
        showToast("Auto crowd pulse stopped", "info");
    } else {
        state.autoTickTimer = setInterval(stepSimulation, 4500);
        label.textContent = "ON";
        btn.classList.remove("btn-outline");
        btn.classList.add("btn-primary");
        showToast("Auto crowd pulse active (every 4.5s)", "success");
    }
}

/**
 * Resets venue queues to original baseline.
 */
async function resetVenueState() {
    try {
        const res = await fetch("/api/reset", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            state.zones = data.zones;
            updateDashboardMetrics(data.summary);
            renderStadiumMapNodes();
            selectZone(state.zones[0]?.id || "food_north");
            clearUploadedImage();
            showToast("Stadium queues reset to baseline", "info");
        }
    } catch (err) {
        console.error("Reset error:", err);
    }
}

/**
 * Helper to retrieve a zone by its ID.
 */
function getZoneById(id) {
    return state.zones.find(z => z.id === id);
}

/**
 * Displays floating notification toasts.
 */
function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;

    const icon = type === "success" ? "✅" : (type === "warning" ? "⚠️" : "ℹ️");
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

/**
 * Fan Q&A Assistant — Ask button + quick questions
 */
function initFanQaAssistant() {
    const askBtn = document.getElementById("btnAskQuestion");
    const questionInput = document.getElementById("fanQuestionInput");
    const answerArea = document.getElementById("fanAnswerArea");

    if (!askBtn) return;

    async function askQuestion(questionText) {
        const question = (questionText ?? questionInput.value ?? "").trim();
        if (!question) {
            answerArea.textContent = "Please type a question first.";
            return;
        }

        const need = document.getElementById("wayfinderNeed")?.value || "food";
        const userZone = document.getElementById("wayfinderZone")?.value || "North";

        answerArea.textContent = "Thinking…";
        askBtn.disabled = true;

        try {
            const res = await fetch("/api/ask", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question, need, user_zone: userZone })
            });
            const data = await res.json();
            if (data.success) {
                answerArea.textContent = data.answer;
            } else {
                answerArea.textContent = "Sorry, I couldn't get an answer right now.";
            }
        } catch (err) {
            console.error("Ask question error:", err);
            answerArea.textContent = "Connection error — please try again.";
        } finally {
            askBtn.disabled = false;
        }
    }

    askBtn.addEventListener("click", () => askQuestion());

    questionInput?.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            askQuestion();
        }
    });

    document.querySelectorAll(".btn-quick-question").forEach(btn => {
        btn.addEventListener("click", () => {
            const q = btn.dataset.question;
            questionInput.value = q;
            askQuestion(q);
        });
    });
}

/**
 * Live Wait-Time List — auto-refreshes every 15 seconds
 */
function renderLiveWaitList(zones) {
    const list = document.getElementById("liveWaitList");
    if (!list || !zones) return;

    list.innerHTML = zones.map(zone => {
        const wait = zone.wait_time_minutes;
        let colorClass = "text-emerald";
        if (wait >= 10) colorClass = "text-crimson";
        else if (wait >= 5) colorClass = "text-amber";

        return `
            <li class="announcement-item">
                <div class="ann-title">${zone.name}</div>
                <div class="ann-body ${colorClass}">${wait} min wait</div>
            </li>
        `;
    }).join("");
}

async function refreshLiveWaitList() {
    try {
        const res = await fetch("/api/zones");
        const data = await res.json();
        if (data.success) {
            renderLiveWaitList(data.zones);
        }
    } catch (err) {
        console.error("Live wait list refresh error:", err);
    }
}

function initLiveWaitList() {
    refreshLiveWaitList();
    setInterval(refreshLiveWaitList, 15000);
}

// Hook new features into startup
document.addEventListener("DOMContentLoaded", () => {
    initFanQaAssistant();
    initLiveWaitList();
});