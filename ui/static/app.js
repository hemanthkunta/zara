/**
 * ZARA Unified Command Center — Client Application
 * Production Frontend Lifecycle, Centralized Polling Scheduler, and Resilient WebSocket Manager
 */

(() => {
  "use strict";

  // =========================================================================
  // 1. Application Lifecycle Management
  // =========================================================================

  const AppLifecycleState = {
    BOOT: "BOOT",
    INITIALIZING: "INITIALIZING",
    RUNNING: "RUNNING",
    PAUSED: "PAUSED",
    SHUTDOWN: "SHUTDOWN",
  };

  const WSConnectionState = {
    DISCONNECTED: "DISCONNECTED",
    CONNECTING: "CONNECTING",
    CONNECTED: "CONNECTED",
    RECONNECT_WAIT: "RECONNECT_WAIT",
    CLOSED: "CLOSED",
  };

  // State
  let currentLifecycle = AppLifecycleState.BOOT;
  let isInitialized = false;
  let listenersAttached = false;
  let currentFilter = "all";
  const eventsLog = [];
  const MAX_EVENTS_LOG = 100;
  const MAX_TERMINAL_LINES = 100;

  // Cached state hashes for conditional DOM rendering
  const stateCache = {
    status: null,
    world: null,
    tasks: null,
    project: null,
    memory: null,
    workers: null,
    models: null,
    modelsCatalog: null,
    learning: null,
  };

  // DOM Elements Cache
  const getEl = (id) => (typeof document !== "undefined" ? document.getElementById(id) : null);
  const getAll = (sel) => (typeof document !== "undefined" ? document.querySelectorAll(sel) : []);

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

  // =========================================================================
  // 2. Bounded DOM Logging & Rendering
  // =========================================================================

  const logTerminal = (msg, level = "system") => {
    const terminalFeed = getEl("terminal-feed");
    if (!terminalFeed) return;

    const line = document.createElement("div");
    line.className = `terminal-line ${level}`;
    line.textContent = `[${formatTime()}] ${msg}`;
    terminalFeed.appendChild(line);

    // Bounded terminal output: evict oldest lines when exceeding limit
    while (terminalFeed.childNodes.length > MAX_TERMINAL_LINES) {
      terminalFeed.removeChild(terminalFeed.firstChild);
    }
    terminalFeed.scrollTop = terminalFeed.scrollHeight;
  };

  const addEventRow = (eventData) => {
    if (!eventData) return;
    eventsLog.push(eventData);
    if (eventsLog.length > MAX_EVENTS_LOG) {
      eventsLog.shift();
    }

    const eventsTimeline = getEl("events-timeline");
    if (!eventsTimeline) return;

    const type = (eventData.type || eventData.event_type || "").toLowerCase();
    if (currentFilter !== "all" && !type.includes(currentFilter)) {
      return;
    }

    // Remove empty placeholder if present
    const emptyRow = eventsTimeline.querySelector(".event-placeholder");
    if (emptyRow) {
      emptyRow.remove();
    }

    // Create incremental row
    const row = document.createElement("div");
    let cat = "system";
    if (type.includes("world")) cat = "world";
    else if (type.includes("task") || type.includes("plan")) cat = "task";
    else if (type.includes("tool") || type.includes("term")) cat = "tool";

    row.className = `event-row ${cat}`;
    const timeStr = formatTime(eventData.timestamp);
    const msg = eventData.message || eventData.event_type || JSON.stringify(eventData.data || eventData);
    row.innerHTML = `<span class="event-time">${timeStr}</span><span class="event-msg">${escapeHtml(msg)}</span>`;
    eventsTimeline.appendChild(row);

    // Bound events timeline DOM children
    while (eventsTimeline.childNodes.length > MAX_EVENTS_LOG) {
      eventsTimeline.removeChild(eventsTimeline.firstChild);
    }
    eventsTimeline.scrollTop = eventsTimeline.scrollHeight;
  };

  const renderEvents = () => {
    const eventsTimeline = getEl("events-timeline");
    if (!eventsTimeline) return;

    eventsTimeline.innerHTML = "";
    const filtered = eventsLog.filter((e) => {
      if (currentFilter === "all") return true;
      const type = (e.type || e.event_type || "").toLowerCase();
      return type.includes(currentFilter);
    });

    if (filtered.length === 0) {
      eventsTimeline.innerHTML = `<div class="event-row system event-placeholder"><span class="event-time">--:--:--</span><span class="event-msg">No matching events.</span></div>`;
      return;
    }

    const frag = document.createDocumentFragment();
    filtered.slice(-MAX_EVENTS_LOG).forEach((e) => {
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
      frag.appendChild(row);
    });
    eventsTimeline.appendChild(frag);
    eventsTimeline.scrollTop = eventsTimeline.scrollHeight;
  };

  // =========================================================================
  // 3. UI Section Renderers (with State Comparison Guards)
  // =========================================================================

  const updateStatusUI = (status) => {
    if (!status) return;
    const serialized = JSON.stringify(status);
    if (stateCache.status === serialized) return;
    stateCache.status = serialized;

    const metricCpu = getEl("metric-cpu");
    const metricRam = getEl("metric-ram");
    const autonomousBadge = getEl("autonomous-badge");
    const voiceBadge = getEl("voice-badge");
    const activeProjectName = getEl("active-project-name");
    const activeTaskDesc = getEl("active-task-desc");

    if (status.cpu_percent !== undefined && metricCpu) metricCpu.textContent = `${Math.round(status.cpu_percent)}%`;
    if (status.memory_percent !== undefined && metricRam) metricRam.textContent = `${Math.round(status.memory_percent)}%`;

    if (status.autonomous_mode !== undefined && autonomousBadge) {
      if (status.autonomous_mode) {
        autonomousBadge.className = "badge badge-active";
        autonomousBadge.textContent = "AUTONOMOUS: ON";
      } else {
        autonomousBadge.className = "badge badge-dim";
        autonomousBadge.textContent = "AUTONOMOUS: OFF";
      }
    }

    if (status.voice_speaking !== undefined && voiceBadge) {
      if (status.voice_speaking) {
        voiceBadge.className = "badge badge-active";
        voiceBadge.textContent = "VOICE: SPEAKING";
      } else {
        voiceBadge.className = "badge badge-dim";
        voiceBadge.textContent = "VOICE: IDLE";
      }
    }

    if (status.active_project && activeProjectName) {
      const pName = typeof status.active_project === "object" ? status.active_project.name : status.active_project;
      activeProjectName.textContent = pName || "No Active Project";
    }
    if (status.active_task && activeTaskDesc) {
      activeTaskDesc.textContent = status.active_task;
    }
  };

  const updateWorldUI = (data) => {
    if (!data) return;
    const serialized = JSON.stringify(data);
    if (stateCache.world === serialized) return;
    stateCache.world = serialized;

    const worldConfidenceTag = getEl("world-confidence-tag");
    const worldActiveApp = getEl("world-active-app");
    const worldActiveWindow = getEl("world-active-window");
    const worldGraphStats = getEl("world-graph-stats");
    const worldLastObs = getEl("world-last-obs");
    const metricConf = getEl("metric-conf");
    const freshnessGrid = getEl("freshness-grid");

    const curr = data.world_state || data.current_state || data;
    if (curr.active_application && worldActiveApp) {
      worldActiveApp.textContent = curr.active_application;
    }
    if (curr.active_window && worldActiveWindow) {
      worldActiveWindow.textContent = curr.active_window;
      worldActiveWindow.title = curr.active_window;
    }
    if (curr.timestamp && worldLastObs) {
      worldLastObs.textContent = formatTime(curr.timestamp);
    }
    if (curr.confidence !== undefined) {
      const pct = Math.round((Number(curr.confidence) || 0) * 100);
      if (worldConfidenceTag) worldConfidenceTag.textContent = `Conf: ${pct}%`;
      if (metricConf) metricConf.textContent = `${pct}%`;
    }

    if (data.entities_count !== undefined && data.relationships_count !== undefined && worldGraphStats) {
      worldGraphStats.textContent = `${data.entities_count} entities / ${data.relationships_count} relations`;
    }

    // Modality freshness
    const freshness = data.freshness || data.modality_freshness || {};
    if (freshnessGrid) {
      const chips = freshnessGrid.querySelectorAll(".chip");
      chips.forEach((chip) => {
        const mod = chip.getAttribute("data-modality");
        const status = (freshness[mod] || "unknown").toLowerCase();
        chip.className = `chip chip-${status}`;
      });
    }
  };

  const updateTasksUI = (data) => {
    if (!data) return;
    const serialized = JSON.stringify(data);
    if (stateCache.tasks === serialized) return;
    stateCache.tasks = serialized;

    const planGoalText = getEl("plan-goal-text");
    const planStatusBadge = getEl("plan-status-badge");
    const approvalBanner = getEl("approval-banner");
    const planProgressFill = getEl("plan-progress-fill");
    const planProgressText = getEl("plan-progress-text");
    const dagTaskList = getEl("dag-task-list");

    if (data.goal && planGoalText) {
      planGoalText.textContent = data.goal;
    }
    if (data.status && planStatusBadge) {
      planStatusBadge.textContent = data.status.toUpperCase();
      if (data.status === "pending_approval" || data.pending_approval) {
        if (approvalBanner) approvalBanner.classList.remove("hidden");
        planStatusBadge.className = "tag tag-warning";
      } else {
        if (approvalBanner) approvalBanner.classList.add("hidden");
        planStatusBadge.className = data.status === "completed" ? "tag tag-success" : "tag tag-secondary";
      }
    }

    // Progress
    const total = data.total_tasks || (data.tasks ? data.tasks.length : 0);
    const completed = data.completed_tasks || 0;
    const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
    if (planProgressFill) planProgressFill.style.width = `${pct}%`;
    if (planProgressText) planProgressText.textContent = `${pct}% Complete (${completed}/${total})`;

    // Task List
    if (data.tasks && Array.isArray(data.tasks) && dagTaskList) {
      dagTaskList.innerHTML = "";
      if (data.tasks.length === 0) {
        dagTaskList.innerHTML = `<li class="empty-placeholder">No active tasks in DAG queue.</li>`;
      } else {
        const frag = document.createDocumentFragment();
        data.tasks.slice(0, 20).forEach((t) => {
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
          frag.appendChild(item);
        });
        dagTaskList.appendChild(frag);
      }
    }
  };

  const updateProjectUI = (proj) => {
    if (!proj) return;
    const serialized = JSON.stringify(proj);
    if (stateCache.project === serialized) return;
    stateCache.project = serialized;

    const projName = getEl("proj-name");
    const activeProjectName = getEl("active-project-name");
    const projId = getEl("proj-id");
    const projRoot = getEl("proj-root");
    const projArtifacts = getEl("proj-artifacts");
    const projCheckpoints = getEl("proj-checkpoints");
    const projectStatusBadge = getEl("project-status-badge");

    if (projName) projName.textContent = proj.name || "None";
    if (activeProjectName) activeProjectName.textContent = proj.name || "No Active Project";
    if (projId) projId.textContent = proj.project_id ? proj.project_id.slice(0, 8) + "..." : "--";
    if (projRoot) {
      projRoot.textContent = proj.root_path || "--";
      projRoot.title = proj.root_path || "";
    }
    if (projArtifacts) projArtifacts.textContent = proj.artifacts_count || 0;
    if (projCheckpoints) projCheckpoints.textContent = proj.checkpoints_count || 0;

    if (projectStatusBadge) {
      const status = (proj.status || "IDLE").toUpperCase();
      projectStatusBadge.textContent = status;
      if (status === "ACTIVE") {
        projectStatusBadge.className = "tag tag-success";
      } else if (status === "PAUSED") {
        projectStatusBadge.className = "tag tag-warning";
      } else {
        projectStatusBadge.className = "tag tag-dim";
      }
    }
  };

  const updateMemoryUI = (data) => {
    if (!data) return;
    const serialized = JSON.stringify(data);
    if (stateCache.memory === serialized) return;
    stateCache.memory = serialized;

    const memStatActive = getEl("mem-stat-active");
    const memStatConflicts = getEl("mem-stat-conflicts");
    const memoryCountBadge = getEl("memory-count-badge");
    const memoryItemsList = getEl("memory-items-list");

    if (data.stats) {
      if (memStatActive) memStatActive.textContent = data.stats.active_memories || 0;
      if (memStatConflicts) memStatConflicts.textContent = data.stats.conflict_count || 0;
      if (memoryCountBadge) memoryCountBadge.textContent = `${data.stats.total_memories || 0} Items`;
    } else if (data.results) {
      if (memoryCountBadge) memoryCountBadge.textContent = `${data.count || 0} Results`;
    }

    if (!memoryItemsList) return;
    const items = data.results || (data.recent_lessons ? data.recent_lessons.map((l) => ({ content: typeof l === "string" ? l : (l.lesson || l.header), type: "LESSON" })) : (data.entries || []));
    if (!items || items.length === 0) {
      memoryItemsList.innerHTML = '<div class="memory-empty-state" style="color: #718096; padding: 4px 0;">No memories found.</div>';
      return;
    }

    memoryItemsList.innerHTML = items
      .slice(0, 5)
      .map((m) => {
        const typeStr = escapeHtml(m.type || "INFO");
        const contentStr = escapeHtml(m.content || m.lesson || JSON.stringify(m));
        return `<div style="padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.05);">
          <span class="tag tag-dim" style="font-size: 9px; margin-right: 4px;">${typeStr}</span>
          <span>${contentStr}</span>
        </div>`;
      })
      .join("");
  };

  const updateWorkersUI = (data) => {
    if (!data) return;
    const serialized = JSON.stringify(data);
    if (stateCache.workers === serialized) return;
    stateCache.workers = serialized;

    const workers = data.workers || [];
    const metrics = data.metrics || {};

    const countBadge = getEl("workers-count-badge");
    if (countBadge) {
      countBadge.textContent = `${metrics.active_workers || 0} Active`;
      countBadge.className = metrics.active_workers > 0 ? "tag tag-success" : "tag tag-dim";
    }

    const locksSummary = getEl("active-locks-count");
    if (locksSummary) {
      locksSummary.textContent = metrics.active_locks || 0;
    }

    const workersList = getEl("workers-list");
    if (workersList) {
      if (workers.length === 0) {
        workersList.innerHTML = '<div class="empty-placeholder" style="font-size: 12px; color: #888;">No active workers.</div>';
      } else {
        workersList.innerHTML = workers
          .slice(0, 6)
          .map((w) => {
            const statusClass = w.status === "running" ? "tag-success" : (w.status === "completed" ? "tag-info" : (w.status === "failed" ? "tag-danger" : "tag-dim"));
            return `<div style="display: flex; justify-content: space-between; align-items: center; padding: 4px 6px; background: rgba(255,255,255,0.03); border-radius: 4px;">
              <div>
                <span style="font-weight: 600; font-size: 11px;">${escapeHtml((w.worker_type || "general").toUpperCase())}</span>
                <span style="font-size: 10px; color: #888; margin-left: 4px;">${escapeHtml(w.worker_id)}</span>
              </div>
              <span class="tag ${statusClass}" style="font-size: 9px;">${escapeHtml((w.status || "created").toUpperCase())}</span>
            </div>`;
          })
          .join("");
      }
    }
  };

  const updateModelsUI = (statusData, catalogData) => {
    if (statusData) {
      const serStatus = JSON.stringify(statusData);
      if (stateCache.models !== serStatus) {
        stateCache.models = serStatus;
        const provElem = getEl("model-active-provider");
        const nameElem = getEl("model-active-name");
        const latElem = getEl("model-avg-latency");
        const failElem = getEl("model-failovers-count");
        const badgeElem = getEl("model-router-badge");

        if (provElem) provElem.textContent = statusData.active_provider || "mock";
        if (nameElem) nameElem.textContent = statusData.active_model || "default";
        if (latElem) latElem.textContent = statusData.metrics ? `${Math.round(statusData.metrics.average_latency || 0)}ms` : "0ms";
        if (failElem) failElem.textContent = statusData.metrics ? (statusData.metrics.failovers_total || 0) : 0;
        if (badgeElem) {
          badgeElem.textContent = statusData.status || "HEALTHY";
          badgeElem.className = statusData.status === "HEALTHY" ? "tag tag-success" : "tag tag-warning";
        }
      }
    }

    if (catalogData) {
      const serCat = JSON.stringify(catalogData);
      if (stateCache.modelsCatalog !== serCat) {
        stateCache.modelsCatalog = serCat;
        const listContainer = getEl("models-list-container");
        if (listContainer && catalogData.models) {
          listContainer.innerHTML = catalogData.models
            .slice(0, 5)
            .map((m) => {
              const availTag = m.availability === "available" ? "tag-success" : (m.availability === "configured" ? "tag-info" : "tag-dim");
              return `<div style="display: flex; justify-content: space-between; align-items: center; padding: 2px 0;">
                <span style="font-size: 10px; font-weight: 500;">${escapeHtml(m.display_name || m.model_id)}</span>
                <span class="tag ${availTag}" style="font-size: 8px;">${escapeHtml((m.availability || "configured").toUpperCase())}</span>
              </div>`;
            })
            .join("");
        }
      }
    }
  };

  const updateLearningUI = (data) => {
    if (!data) return;
    const serialized = JSON.stringify(data);
    if (stateCache.learning === serialized) return;
    stateCache.learning = serialized;

    const stats = data.stats || {};
    const tasksElem = getEl("learning-tasks-eval");
    const rateElem = getEl("learning-success-rate");
    const scoreElem = getEl("learning-avg-score");
    const stratsElem = getEl("learning-valid-strats");
    const propsElem = getEl("learning-pending-props");
    const expsElem = getEl("learning-active-exps");

    if (tasksElem) tasksElem.textContent = stats.tasks_evaluated || 0;
    if (rateElem) rateElem.textContent = `${Math.round((stats.success_rate || 1.0) * 100)}%`;
    if (scoreElem) scoreElem.textContent = (stats.average_overall_score || 0.0).toFixed(2);
    if (stratsElem) stratsElem.textContent = stats.validated_strategies_count || 0;
    if (propsElem) propsElem.textContent = `${stats.pending_proposals_count || 0} pending`;
    if (expsElem) expsElem.textContent = `${stats.active_experiments_count || 0} active`;

    const lessonsContainer = getEl("learning-lessons-container");
    if (lessonsContainer && data.recent_lessons) {
      if (data.recent_lessons.length === 0) {
        lessonsContainer.innerHTML = `<div class="empty-placeholder" style="color: #718096;">No lessons recorded yet.</div>`;
      } else {
        lessonsContainer.innerHTML = data.recent_lessons
          .slice(-3)
          .map((l) => {
            const mType = l.memory_type || "EXPERIENCE";
            const tagClass = mType === "ERROR_PATTERN" ? "tag-warning" : "tag-success";
            return `<div style="padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.04);">
              <span class="tag ${tagClass}" style="font-size: 8px;">${escapeHtml(mType)}</span>
              <span style="font-size: 10px; color: #cbd5e0;">${escapeHtml(l.lesson || "")}</span>
            </div>`;
          })
          .join("");
      }
    }
  };

  // =========================================================================
  // 4. Centralized Polling Scheduler (with In-Flight Guard & AbortController)
  // =========================================================================

  class PollingScheduler {
    constructor() {
      this.resources = new Map();
      this.timerId = null;
      this.tickIntervalMs = 1000;
      this.isPaused = false;
      this.isRunning = false;
    }

    registerResource(name, intervalMs, fetchFn) {
      this.resources.set(name, {
        name,
        intervalMs,
        fetchFn,
        lastRun: 0,
        inFlight: false,
        abortController: null,
      });
      return this;
    }

    start() {
      if (this.isRunning) return;
      this.isRunning = true;
      this.isPaused = false;

      // Master tick interval
      this.timerId = setInterval(() => {
        this.tick();
      }, this.tickIntervalMs);

      // Trigger initial run for all resources immediately, staggered
      let delay = 0;
      for (const res of this.resources.values()) {
        setTimeout(() => {
          if (this.isRunning && !this.isPaused) {
            this.dispatch(res);
          }
        }, delay);
        delay += 150; // 150ms stagger between initial boot fetches
      }
    }

    stop() {
      this.isRunning = false;
      if (this.timerId) {
        clearInterval(this.timerId);
        this.timerId = null;
      }
      this.abortAll();
    }

    pause() {
      this.isPaused = true;
      this.abortAll();
    }

    resume() {
      if (!this.isRunning) {
        this.start();
        return;
      }
      this.isPaused = false;
      // Perform one synchronized refresh of due resources
      const now = Date.now();
      let delay = 0;
      for (const res of this.resources.values()) {
        if (now - res.lastRun >= res.intervalMs) {
          setTimeout(() => {
            if (this.isRunning && !this.isPaused) {
              this.dispatch(res);
            }
          }, delay);
          delay += 100;
        }
      }
    }

    abortAll() {
      for (const res of this.resources.values()) {
        if (res.abortController && res.inFlight) {
          try {
            res.abortController.abort();
          } catch (_) {}
          res.inFlight = false;
          res.abortController = null;
        }
      }
    }

    tick() {
      if (!this.isRunning || this.isPaused) return;

      const now = Date.now();
      for (const res of this.resources.values()) {
        if (now - res.lastRun >= res.intervalMs) {
          this.dispatch(res);
        }
      }
    }

    async dispatch(res, force = false) {
      if (!res || (!force && (res.inFlight || this.isPaused))) {
        return; // In-flight guard: never overlap requests for the same resource
      }

      if (res.inFlight && force) {
        // Supersede active in-flight request on force
        if (res.abortController) {
          try {
            res.abortController.abort();
          } catch (_) {}
        }
      }

      res.inFlight = true;
      res.abortController = typeof AbortController !== "undefined" ? new AbortController() : null;
      const signal = res.abortController ? res.abortController.signal : null;

      try {
        await res.fetchFn(signal);
      } catch (err) {
        if (err && err.name === "AbortError") {
          // Stale request aborted cleanly
        } else {
          // Silent failure with controlled warning
        }
      } finally {
        res.inFlight = false;
        res.lastRun = Date.now();
        res.abortController = null;
      }
    }

    trigger(resourceName) {
      const res = this.resources.get(resourceName);
      if (res) {
        return this.dispatch(res, true);
      }
      return Promise.resolve();
    }
  }

  // Create single scheduler instance
  const scheduler = new PollingScheduler();

  // Resource Fetch Implementations
  const fetchStatus = async (signal) => {
    const res = await fetch("/api/status", { signal });
    if (res.ok) {
      const data = await res.json();
      updateStatusUI(data);
    }
  };

  const fetchWorld = async (signal) => {
    const res = await fetch("/api/world", { signal });
    if (res.ok) {
      const data = await res.json();
      updateWorldUI(data);
    }
  };

  const fetchTasks = async (signal) => {
    const res = await fetch("/api/tasks", { signal });
    if (res.ok) {
      const data = await res.json();
      updateTasksUI(data);
    }
  };

  const fetchProject = async (signal) => {
    const res = await fetch("/api/projects", { signal });
    if (res.ok) {
      const data = await res.json();
      if (data.projects && data.projects.length > 0) {
        updateProjectUI(data.projects[0]);
      }
    }
  };

  const fetchMemory = async (signal) => {
    const res = await fetch("/api/memory", { signal });
    if (res.ok) {
      const data = await res.json();
      updateMemoryUI(data);
    }
  };

  const fetchWorkers = async (signal) => {
    const res = await fetch("/api/workers", { signal });
    if (res.ok) {
      const data = await res.json();
      updateWorkersUI(data);
    }
  };

  const fetchModels = async (signal) => {
    const res = await fetch("/api/models/status", { signal });
    let statusData = null;
    if (res.ok) {
      statusData = await res.json();
    }

    let catalogData = null;
    // Only fetch catalog occasionally or if first time
    if (!stateCache.modelsCatalog) {
      const mRes = await fetch("/api/models", { signal });
      if (mRes.ok) {
        catalogData = await mRes.json();
      }
    }
    updateModelsUI(statusData, catalogData);
  };

  const fetchLearning = async (signal) => {
    const res = await fetch("/api/learning/status", { signal });
    if (res.ok) {
      const data = await res.json();
      updateLearningUI(data);
    }
  };

  // Register all polling resources with designated cadences
  scheduler
    .registerResource("status", 3000, fetchStatus)
    .registerResource("tasks", 3000, fetchTasks)
    .registerResource("workers", 3000, fetchWorkers)
    .registerResource("world", 4000, fetchWorld)
    .registerResource("projects", 6000, fetchProject)
    .registerResource("models", 6000, fetchModels)
    .registerResource("learning", 6000, fetchLearning)
    .registerResource("memory", 6000, fetchMemory);

  // =========================================================================
  // 5. WebSocket Single-Connection Manager & Reconnect Controller
  // =========================================================================

  class WebSocketManager {
    constructor() {
      this.ws = null;
      this.state = WSConnectionState.DISCONNECTED;
      this.reconnectTimer = null;
      this.retryCount = 0;
      this.baseDelayMs = 1000;
      this.maxDelayMs = 15000;
      this.backoffFactor = 1.5;
    }

    connect() {
      // Single-connection guarantee: if connecting or open, no-op
      if (
        this.state === WSConnectionState.CONNECTING ||
        this.state === WSConnectionState.CONNECTED ||
        (this.ws && (this.ws.readyState === 0 || this.ws.readyState === 1))
      ) {
        return;
      }

      this.clearReconnectTimer();
      this.state = WSConnectionState.CONNECTING;

      const connectionBadge = getEl("connection-badge");
      if (connectionBadge) {
        connectionBadge.className = "badge badge-pulse offline";
        connectionBadge.textContent = "CONNECTING...";
      }

      const protocol = typeof window !== "undefined" && window.location && window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = typeof window !== "undefined" && window.location && window.location.host ? window.location.host : "127.0.0.1:8420";
      const wsUrl = `${protocol}//${host}/ws`;

      try {
        this.ws = new WebSocket(wsUrl);
      } catch (err) {
        this.handleDisconnect("Failed to create WebSocket instance");
        return;
      }

      this.ws.onopen = () => {
        this.state = WSConnectionState.CONNECTED;
        this.retryCount = 0;
        this.clearReconnectTimer();

        if (connectionBadge) {
          connectionBadge.className = "badge badge-pulse online";
          connectionBadge.textContent = "ONLINE";
        }
        logTerminal("Connected to ZARA real-time event stream.", "success");
      };

      this.ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          this.handleMessage(msg);
        } catch (err) {
          console.error("WS Parse error:", err);
        }
      };

      this.ws.onerror = () => {
        // Handled cleanly in onclose
      };

      this.ws.onclose = () => {
        if (this.state !== WSConnectionState.CLOSED) {
          this.handleDisconnect("Connection closed");
        }
      };
    }

    handleDisconnect(reason) {
      if (this.state === WSConnectionState.CLOSED) return;

      this.state = WSConnectionState.DISCONNECTED;
      this.ws = null;

      const connectionBadge = getEl("connection-badge");
      if (connectionBadge) {
        connectionBadge.className = "badge badge-pulse offline";
        connectionBadge.textContent = "OFFLINE";
      }

      // Exponential backoff with jitter
      this.retryCount += 1;
      const exponentialDelay = Math.min(
        this.maxDelayMs,
        this.baseDelayMs * Math.pow(this.backoffFactor, this.retryCount - 1)
      );
      const jitter = Math.floor(Math.random() * 300);
      const delay = Math.round(exponentialDelay + jitter);

      this.state = WSConnectionState.RECONNECT_WAIT;
      logTerminal(`Disconnected from ZARA real-time feed. Reconnecting in ${(delay / 1000).toFixed(1)}s...`, "warning");

      this.clearReconnectTimer();
      this.reconnectTimer = setTimeout(() => {
        this.connect();
      }, delay);
    }

    clearReconnectTimer() {
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    }

    disconnect() {
      this.state = WSConnectionState.CLOSED;
      this.clearReconnectTimer();
      if (this.ws) {
        try {
          this.ws.close();
        } catch (_) {}
        this.ws = null;
      }
    }

    handleMessage(msg) {
      if (!msg || !msg.type) return;

      // CRITICAL: WebSocket events MUST NOT start new polling intervals or call init()
      if (msg.type === "init") {
        logTerminal("Synchronizing initial session state...", "info");
        if (msg.world) updateWorldUI(msg.world);
        if (msg.project) updateProjectUI(msg.project);
        if (msg.tasks) updateTasksUI(msg.tasks);
        if (msg.events && Array.isArray(msg.events)) {
          msg.events.slice(-MAX_EVENTS_LOG).forEach((e) => eventsLog.push(e));
          renderEvents();
        }
      } else if (msg.type === "world_update") {
        if (msg.world) updateWorldUI(msg.world);
        else if (msg.data) updateWorldUI(msg.data);
        addEventRow({ type: "world_update", message: "World model state refreshed", timestamp: new Date() });
      } else if (msg.type === "screen_refreshed" || msg.type === "screen_changed") {
        const screenPreview = getEl("screen-preview");
        const screenTimeTag = getEl("screen-time-tag");
        if (screenPreview) {
          screenPreview.src = `/api/screenshot/latest?t=${Date.now()}`;
        }
        if (screenTimeTag) {
          screenTimeTag.textContent = `Last: ${formatTime()}`;
        }
      } else if (msg.type === "event") {
        const payload = msg.event || msg.data || msg;
        addEventRow(payload);
        if (payload && payload.terminal_output) {
          logTerminal(payload.terminal_output, "info");
        }
      } else if (msg.type === "task_completed") {
        const taskId = msg.summary ? msg.summary.task : (msg.data ? msg.data.task_id : "unknown");
        logTerminal(`Task finished: ${taskId}`, "success");
        scheduler.trigger("tasks");
      } else if (msg.type === "plan_approved") {
        const banner = getEl("approval-banner");
        if (banner) banner.classList.add("hidden");
        scheduler.trigger("tasks");
      } else if (msg.type === "status") {
        updateStatusUI(msg.data || msg);
      }
    }
  }

  const wsManager = new WebSocketManager();

  // Backward compatible export function for tests
  const connectWebSocket = () => {
    wsManager.connect();
  };

  // =========================================================================
  // 6. UI Event Listeners (Attached Exactly Once)
  // =========================================================================

  const attachEventListeners = () => {
    if (listenersAttached) return;
    listenersAttached = true;

    // Command Form (isolated from polling AbortControllers)
    const commandForm = getEl("command-form");
    const commandInput = getEl("command-input");
    const btnSubmitCmd = getEl("btn-submit-cmd");

    if (commandForm && commandInput && btnSubmitCmd) {
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
            body: JSON.stringify({ command: cmd }),
          });
          const data = await res.json();
          if (res.ok) {
            logTerminal(`Response: ${data.response || data.status || "Acknowledged"}`, "success");
            commandInput.value = "";
            scheduler.trigger("tasks");
            scheduler.trigger("world");
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
    }

    // Refresh World button
    const btnRefreshWorld = getEl("btn-refresh-world");
    if (btnRefreshWorld) {
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
    }

    // Live screen capture button
    const btnCaptureScreen = getEl("btn-capture-screen");
    const screenPreview = getEl("screen-preview");
    const screenTimeTag = getEl("screen-time-tag");
    if (btnCaptureScreen) {
      btnCaptureScreen.addEventListener("click", async () => {
        logTerminal("Capturing live screen snapshot...", "system");
        try {
          const res = await fetch("/api/screen/refresh", { method: "POST" });
          if (res.ok) {
            if (screenPreview) screenPreview.src = `/api/screenshot/latest?t=${Date.now()}`;
            if (screenTimeTag) screenTimeTag.textContent = `Last: ${formatTime()}`;
            logTerminal("Screen updated.", "success");
          }
        } catch (err) {
          logTerminal(`Screen capture failed: ${err.message}`, "error");
        }
      });
    }

    // Voice interrupt
    const btnVoiceInterrupt = getEl("btn-voice-interrupt");
    if (btnVoiceInterrupt) {
      btnVoiceInterrupt.addEventListener("click", async () => {
        logTerminal("Interrupting active voice playback...", "warning");
        try {
          await fetch("/api/voice/interrupt", { method: "POST" });
          logTerminal("Voice playback halted.", "system");
        } catch (err) {
          logTerminal(`Interrupt failed: ${err.message}`, "error");
        }
      });
    }

    // World diff view
    const btnViewDiff = getEl("btn-view-diff");
    const diffContainer = getEl("diff-container");
    const diffContent = getEl("diff-content");
    if (btnViewDiff && diffContainer && diffContent) {
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
    }

    // Plan approve & dismiss
    const btnApprovePlan = getEl("btn-approve-plan");
    const btnDismissApproval = getEl("btn-dismiss-approval");
    const approvalBanner = getEl("approval-banner");
    if (btnApprovePlan) {
      btnApprovePlan.addEventListener("click", async () => {
        try {
          const res = await fetch("/api/plan/approve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: true }),
          });
          if (res.ok) {
            logTerminal("Plan approved by operator.", "success");
            if (approvalBanner) approvalBanner.classList.add("hidden");
            scheduler.trigger("tasks");
          }
        } catch (err) {
          logTerminal(`Approval failed: ${err.message}`, "error");
        }
      });
    }
    if (btnDismissApproval && approvalBanner) {
      btnDismissApproval.addEventListener("click", () => {
        approvalBanner.classList.add("hidden");
      });
    }

    // Project controls
    const btnPauseProj = getEl("btn-pause-proj");
    const btnResumeProj = getEl("btn-resume-proj");
    const btnCancelProj = getEl("btn-cancel-proj");

    if (btnPauseProj) {
      btnPauseProj.addEventListener("click", async () => {
        await fetch("/api/project/pause", { method: "POST" });
        scheduler.trigger("projects");
      });
    }
    if (btnResumeProj) {
      btnResumeProj.addEventListener("click", async () => {
        await fetch("/api/project/resume", { method: "POST" });
        scheduler.trigger("projects");
      });
    }
    if (btnCancelProj) {
      btnCancelProj.addEventListener("click", async () => {
        if (confirm("Halt active project?")) {
          await fetch("/api/project/cancel", { method: "POST" });
          scheduler.trigger("projects");
        }
      });
    }

    // Event filter chips
    const filterChips = getAll(".chip-filter");
    filterChips.forEach((chip) => {
      chip.addEventListener("click", () => {
        filterChips.forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        currentFilter = chip.getAttribute("data-filter") || "all";
        renderEvents();
      });
    });

    // Memory search
    const btnSearchMemory = getEl("btn-search-memory");
    const memorySearchInput = getEl("memory-search-input");
    if (btnSearchMemory && memorySearchInput) {
      const execSearch = async () => {
        const query = memorySearchInput.value.trim();
        const url = query ? `/api/memory/search?q=${encodeURIComponent(query)}` : "/api/memory";
        try {
          const res = await fetch(url);
          if (res.ok) {
            const data = await res.json();
            updateMemoryUI(data);
          }
        } catch (err) {
          console.error("Memory search failed:", err);
        }
      };

      btnSearchMemory.addEventListener("click", execSearch);
      memorySearchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          execSearch();
        }
      });
    }

    // Tab visibility handling (Pauses polling when hidden, resumes with one sync when visible)
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
          scheduler.pause();
        } else {
          scheduler.resume();
        }
      });
    }

    // Clean shutdown on window unload
    if (typeof window !== "undefined") {
      window.addEventListener("beforeunload", () => {
        shutdownApp();
      });
    }
  };

  // =========================================================================
  // 7. Idempotent Initialization & Shutdown
  // =========================================================================

  const initApp = () => {
    // Idempotency guard: calling initApp multiple times is a safe no-op
    if (isInitialized) {
      return {
        status: "ALREADY_INITIALIZED",
        lifecycle: currentLifecycle,
        scheduler,
        wsManager,
      };
    }

    currentLifecycle = AppLifecycleState.INITIALIZING;
    isInitialized = true;

    // Attach listeners once
    attachEventListeners();

    // Connect WebSocket once
    wsManager.connect();

    // Start single polling scheduler once
    scheduler.start();

    currentLifecycle = AppLifecycleState.RUNNING;
    return {
      status: "INITIALIZED",
      lifecycle: currentLifecycle,
      scheduler,
      wsManager,
    };
  };

  const shutdownApp = () => {
    currentLifecycle = AppLifecycleState.SHUTDOWN;
    scheduler.stop();
    wsManager.disconnect();
    isInitialized = false;
  };

  // Expose ZaraApp interface for runtime inspection and tests
  const ZaraApp = {
    init: initApp,
    shutdown: shutdownApp,
    scheduler,
    wsManager,
    connectWebSocket,
    getLifecycleState: () => currentLifecycle,
    isInitialized: () => isInitialized,
    getEventsLog: () => eventsLog,
    MAX_EVENTS_LOG,
    MAX_TERMINAL_LINES,
    AppLifecycleState,
    WSConnectionState,
  };

  if (typeof window !== "undefined") {
    window.ZaraApp = ZaraApp;
    window.connectWebSocket = connectWebSocket;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = ZaraApp;
  }

  // Auto-boot if in browser environment
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => {
        initApp();
      });
    } else {
      initApp();
    }
  }
})();
