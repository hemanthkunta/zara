/**
 * ZARA Unified Command Center — Client Application
 */

(() => {
  // State
  let ws = null;
  let reconnectTimer = null;
  let currentFilter = "all";
  const eventsLog = [];

  // DOM Elements
  const connectionBadge = document.getElementById("connection-badge");
  const autonomousBadge = document.getElementById("autonomous-badge");
  const voiceBadge = document.getElementById("voice-badge");
  const activeProjectName = document.getElementById("active-project-name");
  const activeTaskDesc = document.getElementById("active-task-desc");
  const metricCpu = document.getElementById("metric-cpu");
  const metricRam = document.getElementById("metric-ram");
  const metricConf = document.getElementById("metric-conf");

  // World Elements
  const worldConfidenceTag = document.getElementById("world-confidence-tag");
  const worldActiveApp = document.getElementById("world-active-app");
  const worldActiveWindow = document.getElementById("world-active-window");
  const worldGraphStats = document.getElementById("world-graph-stats");
  const worldLastObs = document.getElementById("world-last-obs");
  const freshnessGrid = document.getElementById("freshness-grid");
  const btnViewDiff = document.getElementById("btn-view-diff");
  const diffContainer = document.getElementById("diff-container");
  const diffContent = document.getElementById("diff-content");

  // Screen Elements
  const screenPreview = document.getElementById("screen-preview");
  const screenTimeTag = document.getElementById("screen-time-tag");
  const btnCaptureScreen = document.getElementById("btn-capture-screen");

  // Plan & DAG Elements
  const planStatusBadge = document.getElementById("plan-status-badge");
  const planGoalText = document.getElementById("plan-goal-text");
  const planProgressFill = document.getElementById("plan-progress-fill");
  const planProgressText = document.getElementById("plan-progress-text");
  const dagTaskList = document.getElementById("dag-task-list");
  const approvalBanner = document.getElementById("approval-banner");
  const btnApprovePlan = document.getElementById("btn-approve-plan");
  const btnDismissApproval = document.getElementById("btn-dismiss-approval");

  // Terminal & Events
  const terminalFeed = document.getElementById("terminal-feed");
  const eventsTimeline = document.getElementById("events-timeline");
  const filterChips = document.querySelectorAll(".chip-filter");

  // Project Explorer
  const projectStatusBadge = document.getElementById("project-status-badge");
  const projName = document.getElementById("proj-name");
  const projId = document.getElementById("proj-id");
  const projRoot = document.getElementById("proj-root");
  const projArtifacts = document.getElementById("proj-artifacts");
  const projCheckpoints = document.getElementById("proj-checkpoints");
  const btnPauseProj = document.getElementById("btn-pause-proj");
  const btnResumeProj = document.getElementById("btn-resume-proj");
  const btnCancelProj = document.getElementById("btn-cancel-proj");

  // Command Form
  const commandForm = document.getElementById("command-form");
  const commandInput = document.getElementById("command-input");
  const btnSubmitCmd = document.getElementById("btn-submit-cmd");
  const btnRefreshWorld = document.getElementById("btn-refresh-world");
  const btnVoiceInterrupt = document.getElementById("btn-voice-interrupt");

  // Format Helpers
  const formatTime = (ts) => {
    try {
      const d = ts ? new Date(ts) : new Date();
      return d.toTimeString().split(" ")[0];
    } catch {
      return "--:--:--";
    }
  };

  const escapeHtml = (str) => {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  };

  const logTerminal = (msg, level = "system") => {
    const line = document.createElement("div");
    line.className = `terminal-line ${level}`;
    line.textContent = `[${formatTime()}] ${msg}`;
    terminalFeed.appendChild(line);
    terminalFeed.scrollTop = terminalFeed.scrollHeight;
  };

  const addEventRow = (eventData) => {
    eventsLog.push(eventData);
    if (eventsLog.length > 200) eventsLog.shift();
    renderEvents();
  };

  const renderEvents = () => {
    eventsTimeline.innerHTML = "";
    const filtered = eventsLog.filter(e => {
      if (currentFilter === "all") return true;
      const type = (e.type || e.event_type || "").toLowerCase();
      return type.includes(currentFilter);
    });

    if (filtered.length === 0) {
      eventsTimeline.innerHTML = `<div class="event-row system"><span class="event-time">--:--:--</span><span class="event-msg">No matching events.</span></div>`;
      return;
    }

    filtered.forEach(e => {
      const row = document.createElement("div");
      let cat = "system";
      const type = (e.type || e.event_type || "").toLowerCase();
      if (type.includes("world")) cat = "world";
      else if (type.includes("task") || type.includes("plan")) cat = "task";
      else if (type.includes("tool") || type.includes("term")) cat = "tool";

      row.className = `event-row ${cat}`;
      const timeStr = formatTime(e.timestamp);
      const msg = e.message || e.event_type || JSON.stringify(e.data || e);
      row.innerHTML = `<span class="event-time">${timeStr}</span><span class="event-msg">${escapeHtml(msg)}</span>`;
      eventsTimeline.appendChild(row);
    });
    eventsTimeline.scrollTop = eventsTimeline.scrollHeight;
  };

  // Update World State in UI
  const updateWorldUI = (data) => {
    if (!data) return;
    const curr = data.world_state || data.current_state || data;
    if (curr.active_application) {
      worldActiveApp.textContent = curr.active_application;
    }
    if (curr.active_window) {
      worldActiveWindow.textContent = curr.active_window;
      worldActiveWindow.title = curr.active_window;
    }
    if (curr.timestamp) {
      worldLastObs.textContent = formatTime(curr.timestamp);
    }
    if (curr.confidence !== undefined) {
      const pct = Math.round((Number(curr.confidence) || 0) * 100);
      worldConfidenceTag.textContent = `Conf: ${pct}%`;
      metricConf.textContent = `${pct}%`;
    }

    if (data.entities_count !== undefined && data.relationships_count !== undefined) {
      worldGraphStats.textContent = `${data.entities_count} entities / ${data.relationships_count} relations`;
    }

    // Modality freshness
    const freshness = data.freshness || data.modality_freshness || {};
    const chips = freshnessGrid.querySelectorAll(".chip");
    chips.forEach(chip => {
      const mod = chip.getAttribute("data-modality");
      const status = (freshness[mod] || "unknown").toLowerCase();
      chip.className = `chip chip-${status}`;
    });
  };

  // Update Tasks & Plan in UI
  const updateTasksUI = (data) => {
    if (!data) return;
    if (data.goal) {
      planGoalText.textContent = data.goal;
    }
    if (data.status) {
      planStatusBadge.textContent = data.status.toUpperCase();
      if (data.status === "pending_approval") {
        approvalBanner.classList.remove("hidden");
        planStatusBadge.className = "tag tag-warning";
      } else {
        approvalBanner.classList.add("hidden");
        planStatusBadge.className = data.status === "completed" ? "tag tag-success" : "tag tag-secondary";
      }
    }

    // Progress
    const total = data.total_tasks || (data.tasks ? data.tasks.length : 0);
    const completed = data.completed_tasks || 0;
    const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
    planProgressFill.style.width = `${pct}%`;
    planProgressText.textContent = `${pct}% Complete (${completed}/${total})`;

    // Task List
    if (data.tasks && Array.isArray(data.tasks)) {
      dagTaskList.innerHTML = "";
      if (data.tasks.length === 0) {
        dagTaskList.innerHTML = `<li class="empty-placeholder">No active tasks in DAG queue.</li>`;
      } else {
        data.tasks.forEach(t => {
          const item = document.createElement("li");
          const status = (t.status || "pending").toLowerCase();
          item.className = `dag-item ${status}`;
          item.innerHTML = `
            <div class="dag-title">
              <span class="task-id">#${escapeHtml(t.task_id || t.id || "")}</span>
              <span class="task-desc">${escapeHtml(t.description || t.title || "Task")}</span>
            </div>
            <span class="tag tag-dim">${status.toUpperCase()}</span>
          `;
          dagTaskList.appendChild(item);
        });
      }
    }
  };

  // Update Project Info
  const updateProjectUI = (proj) => {
    if (!proj) return;
    projName.textContent = proj.name || "None";
    activeProjectName.textContent = proj.name || "No Active Project";
    projId.textContent = proj.project_id ? proj.project_id.slice(0, 8) + "..." : "--";
    projRoot.textContent = proj.root_path || "--";
    projRoot.title = proj.root_path || "";
    projArtifacts.textContent = proj.artifacts_count || 0;
    projCheckpoints.textContent = proj.checkpoints_count || 0;

    const status = (proj.status || "IDLE").toUpperCase();
    projectStatusBadge.textContent = status;
    if (status === "ACTIVE") {
      projectStatusBadge.className = "tag tag-success";
    } else if (status === "PAUSED") {
      projectStatusBadge.className = "tag tag-warning";
    } else {
      projectStatusBadge.className = "tag tag-dim";
    }
  };

  // Update System Health
  const updateStatusUI = (status) => {
    if (!status) return;
    if (status.cpu_percent !== undefined) metricCpu.textContent = `${Math.round(status.cpu_percent)}%`;
    if (status.memory_percent !== undefined) metricRam.textContent = `${Math.round(status.memory_percent)}%`;

    if (status.autonomous_mode !== undefined) {
      if (status.autonomous_mode) {
        autonomousBadge.className = "badge badge-active";
        autonomousBadge.textContent = "AUTONOMOUS: ON";
      } else {
        autonomousBadge.className = "badge badge-dim";
        autonomousBadge.textContent = "AUTONOMOUS: OFF";
      }
    }

    if (status.voice_speaking !== undefined) {
      if (status.voice_speaking) {
        voiceBadge.className = "badge badge-active";
        voiceBadge.textContent = "VOICE: SPEAKING";
      } else {
        voiceBadge.className = "badge badge-dim";
        voiceBadge.textContent = "VOICE: IDLE";
      }
    }

    if (status.active_project) {
      activeProjectName.textContent = status.active_project;
    }
    if (status.active_task) {
      activeTaskDesc.textContent = status.active_task;
    }
  };

  // WebSocket Connection
  const connectWebSocket = () => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      connectionBadge.className = "badge badge-pulse online";
      connectionBadge.textContent = "ONLINE";
      logTerminal("Connected to ZARA real-time event stream.", "success");
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        handleWSMessage(msg);
      } catch (err) {
        console.error("WS Parse error:", err);
      }
    };

    ws.onerror = (err) => {
      console.warn("WebSocket error observed.");
    };

    ws.onclose = () => {
      connectionBadge.className = "badge badge-pulse offline";
      connectionBadge.textContent = "OFFLINE";
      logTerminal("Disconnected from ZARA real-time feed. Reconnecting in 3s...", "warning");
      if (!reconnectTimer) {
        reconnectTimer = setTimeout(connectWebSocket, 3000);
      }
    };
  };

  const handleWSMessage = (msg) => {
    if (!msg || !msg.type) return;

    if (msg.type === "init") {
      logTerminal("Synchronizing initial session state...", "info");
      if (msg.world) updateWorldUI(msg.world);
      if (msg.project) updateProjectUI(msg.project);
      if (msg.tasks) updateTasksUI(msg.tasks);
      if (msg.events && Array.isArray(msg.events)) {
        msg.events.forEach(e => eventsLog.push(e));
        renderEvents();
      }
    } else if (msg.type === "world_update") {
      updateWorldUI(msg.data);
      addEventRow({ type: "world_update", message: "World model state refreshed", timestamp: new Date() });
    } else if (msg.type === "event") {
      addEventRow(msg.data || msg);
      if (msg.data && msg.data.terminal_output) {
        logTerminal(msg.data.terminal_output, "info");
      }
    } else if (msg.type === "task_completed") {
      logTerminal(`Task finished: ${msg.data ? msg.data.task_id : "unknown"}`, "success");
      fetchTasks();
    } else if (msg.type === "status") {
      updateStatusUI(msg.data);
    }
  };

  // REST API Fetchers
  const fetchStatus = async () => {
    try {
      const res = await fetch("/api/status");
      if (res.ok) {
        const data = await res.json();
        updateStatusUI(data);
      }
    } catch (e) {
      console.error("fetchStatus failed:", e);
    }
  };

  const fetchWorld = async () => {
    try {
      const res = await fetch("/api/world");
      if (res.ok) {
        const data = await res.json();
        updateWorldUI(data);
      }
    } catch (e) {
      console.error("fetchWorld failed:", e);
    }
  };

  const fetchTasks = async () => {
    try {
      const res = await fetch("/api/tasks");
      if (res.ok) {
        const data = await res.json();
        updateTasksUI(data);
      }
    } catch (e) {
      console.error("fetchTasks failed:", e);
    }
  };

  const fetchProject = async () => {
    try {
      const res = await fetch("/api/projects");
      if (res.ok) {
        const data = await res.json();
        if (data.projects && data.projects.length > 0) {
          updateProjectUI(data.projects[0]);
        }
      }
    } catch (e) {
      console.error("fetchProject failed:", e);
    }
  };

  // UI Event Handlers
  commandForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const cmd = commandInput.value.trim();
    if (!cmd) return;

    logTerminal(`Transmitting: "${cmd}"`, "info");
    btnSubmitCmd.disabled = true;
    commandInput.disabled = true;

    try {
      const res = await fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: cmd })
      });
      const data = await res.json();
      if (res.ok) {
        logTerminal(`Response: ${data.response || data.status || "Acknowledged"}`, "success");
        commandInput.value = "";
        fetchTasks();
        fetchWorld();
      } else {
        logTerminal(`Error: ${data.detail || "Command failed"}`, "error");
      }
    } catch (err) {
      logTerminal(`Network Error: ${err.message}`, "error");
    } finally {
      btnSubmitCmd.disabled = false;
      commandInput.disabled = false;
      commandInput.focus();
    }
  });

  btnRefreshWorld.addEventListener("click", async () => {
    logTerminal("Refreshing world state modalities...", "system");
    try {
      const res = await fetch("/api/world/refresh", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        updateWorldUI(data.world || data);
        logTerminal("World state refreshed.", "success");
      }
    } catch (err) {
      logTerminal(`Refresh failed: ${err.message}`, "error");
    }
  });

  btnCaptureScreen.addEventListener("click", async () => {
    logTerminal("Capturing live screen snapshot...", "system");
    try {
      const res = await fetch("/api/screen/refresh", { method: "POST" });
      if (res.ok) {
        screenPreview.src = `/api/screenshot/latest?t=${Date.now()}`;
        screenTimeTag.textContent = `Last: ${formatTime()}`;
        logTerminal("Screen updated.", "success");
      }
    } catch (err) {
      logTerminal(`Screen capture failed: ${err.message}`, "error");
    }
  });

  btnVoiceInterrupt.addEventListener("click", async () => {
    logTerminal("Interrupting active voice playback...", "warning");
    try {
      await fetch("/api/voice/interrupt", { method: "POST" });
      logTerminal("Voice playback halted.", "system");
    } catch (err) {
      logTerminal(`Interrupt failed: ${err.message}`, "error");
    }
  });

  btnViewDiff.addEventListener("click", async () => {
    if (!diffContainer.classList.contains("hidden")) {
      diffContainer.classList.add("hidden");
      btnViewDiff.textContent = "Show World Diff";
      return;
    }

    try {
      const res = await fetch("/api/world/diff");
      if (res.ok) {
        const diff = await res.json();
        diffContent.textContent = JSON.stringify(diff, null, 2);
        diffContainer.classList.remove("hidden");
        btnViewDiff.textContent = "Hide World Diff";
      }
    } catch (err) {
      logTerminal(`Diff error: ${err.message}`, "error");
    }
  });

  btnApprovePlan.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/plan/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true })
      });
      if (res.ok) {
        logTerminal("Plan approved by operator.", "success");
        approvalBanner.classList.add("hidden");
        fetchTasks();
      }
    } catch (err) {
      logTerminal(`Approval failed: ${err.message}`, "error");
    }
  });

  btnDismissApproval.addEventListener("click", () => {
    approvalBanner.classList.add("hidden");
  });

  // Project controls
  btnPauseProj.addEventListener("click", async () => {
    await fetch("/api/project/pause", { method: "POST" });
    fetchProject();
  });
  btnResumeProj.addEventListener("click", async () => {
    await fetch("/api/project/resume", { method: "POST" });
    fetchProject();
  });
  btnCancelProj.addEventListener("click", async () => {
    if (confirm("Halt active project?")) {
      await fetch("/api/project/cancel", { method: "POST" });
      fetchProject();
    }
  });

  // Event filter chips
  filterChips.forEach(chip => {
    chip.addEventListener("click", () => {
      filterChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      currentFilter = chip.getAttribute("data-filter");
      renderEvents();
    });
  });

  // Initial Boot
  connectWebSocket();
  fetchStatus();
  fetchWorld();
  fetchTasks();
  fetchProject();

  // Periodic status poll (every 5 seconds)
  setInterval(() => {
    fetchStatus();
  }, 5000);
})();
