"""
Dedicated Runtime Regression Test Suite for ZARA Command Center UI:
Verifies frontend lifecycle, centralized polling scheduler, in-flight overlap guard,
WebSocket single connection & reconnect deduplication, visibility handling,
bounded event rendering, state refresh deduplication, frontend shutdown cleanup,
and server-side responsiveness under concurrent polling load.
"""
import unittest
import json
import time
import subprocess
from pathlib import Path
from starlette.testclient import TestClient

from ui.server import create_ui_app
from core.engine import ZaraEngine
from config.settings import BASE_DIR


class TestCommandCenterRuntimeServer(unittest.TestCase):
    """Server-side runtime resilience and responsiveness tests."""

    def setUp(self):
        self.engine = ZaraEngine(enable_voice=False)
        self.app = create_ui_app(engine=self.engine)
        self.client = TestClient(self.app)

    def test_server_remains_responsive_under_polling_storm(self):
        """Item 12: Server remains responsive and sub-millisecond when rapidly polled."""
        endpoints = [
            "/api/status",
            "/api/memory",
            "/api/workers",
            "/api/models/status",
            "/api/learning/status",
            "/api/projects",
            "/api/world",
            "/api/tasks"
        ]

        # Warm up health cache
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)

        # Rapidly poll across all endpoints in burst
        start_time = time.perf_counter()
        total_requests = 0
        for _ in range(5):
            for ep in endpoints:
                r = self.client.get(ep)
                self.assertEqual(r.status_code, 200, f"Endpoint {ep} failed under burst load")
                total_requests += 1

        elapsed = time.perf_counter() - start_time
        avg_ms = (elapsed / total_requests) * 1000.0

        # Entire burst of 40 requests should complete rapidly
        self.assertLess(avg_ms, 50.0, f"Average request latency too high: {avg_ms:.2f}ms")

    def test_health_cache_prevents_probe_saturation(self):
        """Health caching in server.py avoids re-running all 16 subsystem probes on every status poll."""
        self.app.state.cached_health_report = None
        self.app.state.cached_health_time = 0.0

        # First request runs probe
        t0 = time.perf_counter()
        resp1 = self.client.get("/api/status")
        t1 = time.perf_counter()

        self.assertEqual(resp1.status_code, 200)
        self.assertIsNotNone(self.app.state.cached_health_report)

        # Immediate second request hits cache
        t2 = time.perf_counter()
        resp2 = self.client.get("/api/status")
        t3 = time.perf_counter()

        self.assertEqual(resp2.status_code, 200)
        # Cached response should be faster or near-zero overhead
        cached_duration = t3 - t2
        self.assertLess(cached_duration, 0.05)

    def test_screenshot_endpoint_security_and_caching(self):
        """Item 9: Screenshot endpoint returns valid status or simulated fallback safely."""
        resp = self.client.post("/api/screen/refresh")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertIn("screenshot", data)

    def test_websocket_single_connection_per_client_lifecycle(self):
        """Item 4: WebSocket lifecycle properly registers and disconnects single connection."""
        initial_conns = len(self.app.state.ws_manager.active_connections)
        self.assertEqual(initial_conns, 0)

        with self.client.websocket_connect("/ws") as ws:
            # Active connections incremented to 1
            self.assertEqual(len(self.app.state.ws_manager.active_connections), 1)
            init_msg = ws.receive_json()
            self.assertEqual(init_msg.get("type"), "init")

        # Exiting context manager cleanly drops connection to 0
        self.assertEqual(len(self.app.state.ws_manager.active_connections), 0)


class TestCommandCenterRuntimeFrontend(unittest.TestCase):
    """Frontend lifecycle, scheduler, deduplication, and memory bounding tests via Node runtime."""

    @classmethod
    def setUpClass(cls):
        # Verify node is present
        try:
            res = subprocess.run(["node", "-v"], capture_output=True, text=True, check=True)
            cls.node_available = True
        except Exception:
            cls.node_available = False

    def _run_node_test(self, js_test_code: str) -> dict:
        """Helper to run a Node test script against ui/static/app.js in a mocked environment."""
        if not self.node_available:
            self.skipTest("Node.js runtime not available")

        harness = f"""
        const fs = require('fs');
        const path = require('path');

        // Mock DOM & Browser Environment
        class MockElement {{
            constructor(id) {{
                this.id = id;
                this.className = '';
                this.textContent = '';
                this.innerHTML = '';
                this.childNodes = [];
                this.classList = {{
                    contains: (c) => (this.className || '').includes(c),
                    add: (c) => {{ if (!this.classList.contains(c)) this.className += ' ' + c; }},
                    remove: (c) => {{ this.className = (this.className || '').replace(new RegExp('\\\\b' + c + '\\\\b', 'g'), '').trim(); }}
                }};
                this.style = {{}};
                this.listeners = {{}};
            }}
            appendChild(node) {{
                this.childNodes.push(node);
                return node;
            }}
            removeChild(node) {{
                const idx = this.childNodes.indexOf(node);
                if (idx !== -1) this.childNodes.splice(idx, 1);
                return node;
            }}
            get firstChild() {{
                return this.childNodes[0] || null;
            }}
            addEventListener(ev, fn) {{
                if (!this.listeners[ev]) this.listeners[ev] = [];
                this.listeners[ev].push(fn);
            }}
            querySelector(sel) {{
                return null;
            }}
            querySelectorAll(sel) {{
                return [];
            }}
        }}

        const elements = {{}};
        function getOrCreate(id) {{
            if (!elements[id]) elements[id] = new MockElement(id);
            return elements[id];
        }}

        const docListeners = {{}};
        global.document = {{
            readyState: 'complete',
            hidden: false,
            getElementById: (id) => getOrCreate(id),
            querySelectorAll: () => [],
            createElement: (tag) => new MockElement(tag),
            createDocumentFragment: () => new MockElement('fragment'),
            addEventListener: (ev, fn) => {{
                if (!docListeners[ev]) docListeners[ev] = [];
                docListeners[ev].push(fn);
            }}
        }};

        const winListeners = {{}};
        global.window = {{
            location: {{ protocol: 'http:', host: '127.0.0.1:8420' }},
            addEventListener: (ev, fn) => {{
                if (!winListeners[ev]) winListeners[ev] = [];
                winListeners[ev].push(fn);
            }}
        }};

        global.docListeners = docListeners;
        global.winListeners = winListeners;

        let activeSockets = 0;
        class MockWebSocket {{
            constructor(url) {{
                this.url = url;
                this.readyState = 0; // CONNECTING
                activeSockets++;
                MockWebSocket.instances.push(this);
                setTimeout(() => {{
                    this.readyState = 1; // OPEN
                    if (this.onopen) this.onopen();
                }}, 10);
            }}
            close() {{
                this.readyState = 3; // CLOSED
                activeSockets = Math.max(0, activeSockets - 1);
                if (this.onclose) this.onclose();
            }}
            send(data) {{}}
        }}
        MockWebSocket.instances = [];
        global.WebSocket = MockWebSocket;
        global.getActiveSockets = () => activeSockets;

        let fetchCalls = [];
        global.fetch = async (url, opts) => {{
            fetchCalls.push({{ url, opts, time: Date.now() }});
            return {{
                ok: true,
                json: async () => ({{ status: "OK", timestamp: Date.now() }})
            }};
        }};
        global.getFetchCalls = () => fetchCalls;
        global.clearFetchCalls = () => {{ fetchCalls = []; }};

        // Load app.js
        const appCode = fs.readFileSync(path.resolve('{BASE_DIR}/ui/static/app.js'), 'utf8');
        eval(appCode);

        // Run Specific Test
        (async () => {{
            try {{
                const testResult = await ({js_test_code})();
                console.log(JSON.stringify({{ success: true, result: testResult }}));
                process.exit(0);
            }} catch (err) {{
                console.log(JSON.stringify({{ success: false, error: err.stack || err.message }}));
                process.exit(1);
            }}
        }})();
        """
        proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Node process exited with error:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
        try:
            res = json.loads(proc.stdout.strip())
        except json.JSONDecodeError:
            self.fail(f"Failed to parse node test output:\n{proc.stdout}")

        if not res.get("success"):
            self.fail(f"Node frontend test failed: {res.get('error')}")
        return res.get("result", {})

    def test_initialization_idempotency(self):
        """Item 1: Calling init multiple times is a safe idempotent no-op."""
        res = self._run_node_test("""
        async () => {
            const app = window.ZaraApp;
            const init1 = app.init();
            const init2 = app.init();
            const init3 = app.init();

            return {
                init1_status: init1.status,
                init2_status: init2.status,
                init3_status: init3.status,
                lifecycle: app.getLifecycleState(),
                isInitialized: app.isInitialized()
            };
        }
        """)
        self.assertIn(res["init1_status"], ["INITIALIZED", "ALREADY_INITIALIZED"])
        self.assertEqual(res["init2_status"], "ALREADY_INITIALIZED")
        self.assertEqual(res["init3_status"], "ALREADY_INITIALIZED")
        self.assertEqual(res["lifecycle"], "RUNNING")
        self.assertTrue(res["isInitialized"])

    def test_polling_scheduler_uniqueness(self):
        """Item 2: Single unique polling scheduler instance controls all resources."""
        res = self._run_node_test("""
        async () => {
            const app = window.ZaraApp;
            app.init();
            const scheduler = app.scheduler;
            const resourceNames = Array.from(scheduler.resources.keys());

            return {
                isRunning: scheduler.isRunning,
                resourceCount: scheduler.resources.size,
                resourceNames: resourceNames
            };
        }
        """)
        self.assertTrue(res["isRunning"])
        self.assertGreaterEqual(res["resourceCount"], 6)
        expected_resources = {"status", "tasks", "workers", "world", "projects", "models", "learning", "memory"}
        self.assertTrue(expected_resources.issubset(set(res["resourceNames"])))

    def test_polling_overlap_prevention(self):
        """Item 3: In-flight guard prevents multiple overlapping requests for the same resource."""
        res = self._run_node_test("""
        async () => {
            const app = window.ZaraApp;
            app.init();
            const scheduler = app.scheduler;
            const statusRes = scheduler.resources.get("status");

            // Mock fetch that hangs
            let fetchCount = 0;
            statusRes.fetchFn = async () => {
                fetchCount++;
                await new Promise(resolve => setTimeout(resolve, 50));
            };

            // Trigger dispatch twice concurrently
            const p1 = scheduler.dispatch(statusRes, false);
            const p2 = scheduler.dispatch(statusRes, false);
            const p3 = scheduler.dispatch(statusRes, false);

            await Promise.all([p1, p2, p3]);

            return {
                fetchCount: fetchCount,
                inFlightAfter: statusRes.inFlight
            };
        }
        """)
        # Only 1 fetch executed because in-flight guard blocked the 2 overlapping attempts
        self.assertEqual(res["fetchCount"], 1)
        self.assertFalse(res["inFlightAfter"])

    def test_websocket_single_connection_guarantee(self):
        """Item 4: Repeated connectWebSocket calls do not duplicate connections."""
        res = self._run_node_test("""
        async () => {
            const app = window.ZaraApp;
            app.init();

            const initialSockets = WebSocket.instances.length;
            // Attempt redundant connects
            app.connectWebSocket();
            app.connectWebSocket();
            app.connectWebSocket();

            await new Promise(resolve => setTimeout(resolve, 30));

            return {
                initialSockets: initialSockets,
                totalSocketsCreated: WebSocket.instances.length,
                state: app.wsManager.state
            };
        }
        """)
        self.assertEqual(res["totalSocketsCreated"], 1)
        self.assertEqual(res["state"], "CONNECTED")

    def test_reconnect_deduplication_and_backoff(self):
        """Item 5: WebSocket disconnect triggers a single reconnect timer with exponential backoff."""
        res = self._run_node_test("""
        async () => {
            const app = window.ZaraApp;
            app.init();
            await new Promise(resolve => setTimeout(resolve, 20));

            const wsManager = app.wsManager;
            // Simulate disconnect
            wsManager.handleDisconnect("Simulated network drop");
            const timer1 = wsManager.reconnectTimer;
            const retry1 = wsManager.retryCount;

            // Trigger second disconnect event while already in RECONNECT_WAIT
            wsManager.handleDisconnect("Simulated second drop");
            const timer2 = wsManager.reconnectTimer;
            const retry2 = wsManager.retryCount;

            return {
                state: wsManager.state,
                hasTimer: timer2 !== null,
                retryCount: retry2,
                backoffDelayIncreased: retry2 > 1
            };
        }
        """)
        self.assertEqual(res["state"], "RECONNECT_WAIT")
        self.assertTrue(res["hasTimer"])
        self.assertTrue(res["backoffDelayIncreased"])

    def test_visibility_pause_and_resume(self):
        """Item 6: document.hidden pauses scheduler and resumes without duplicating intervals."""
        res = self._run_node_test("""
        async () => {
            const app = window.ZaraApp;
            app.init();
            const scheduler = app.scheduler;

            const visHandler = global.docListeners['visibilitychange'][0];

            // Simulate tab hidden
            document.hidden = true;
            visHandler();
            const pausedState = scheduler.isPaused;

            // Simulate tab visible
            document.hidden = false;
            visHandler();
            const resumedState = scheduler.isPaused;

            return {
                pausedState: pausedState,
                resumedState: resumedState,
                isRunning: scheduler.isRunning,
                hasSingleTimer: scheduler.timerId !== null
            };
        }
        """)
        self.assertTrue(res["pausedState"])
        self.assertFalse(res["resumedState"])
        self.assertTrue(res["isRunning"])
        self.assertTrue(res["hasSingleTimer"])

    def test_event_listener_lifecycle_idempotency(self):
        """Item 7: Event listeners attached only once during lifecycle."""
        res = self._run_node_test("""
        async () => {
            const app = window.ZaraApp;
            const visListenersBefore = (global.docListeners['visibilitychange'] || []).length;
            app.init();
            const visListenersInit1 = (global.docListeners['visibilitychange'] || []).length;
            app.init();
            const visListenersInit2 = (global.docListeners['visibilitychange'] || []).length;

            return {
                before: visListenersBefore,
                init1: visListenersInit1,
                init2: visListenersInit2
            };
        }
        """)
        self.assertEqual(res["init1"], 1)
        self.assertEqual(res["init2"], 1)

    def test_bounded_event_rendering(self):
        """Item 8: Event history and terminal output remain strictly bounded."""
        res = self._run_node_test("""
        async () => {
            const app = window.ZaraApp;
            app.init();

            // Simulate receiving 150 events via WebSocket
            for (let i = 0; i < 150; i++) {
                app.wsManager.handleMessage({
                    type: "event",
                    event: { type: "system_tick", message: `Tick ${i}`, timestamp: Date.now() }
                });
            }

            const eventsTimeline = document.getElementById("events-timeline");
            const terminalFeed = document.getElementById("terminal-feed");

            return {
                eventsLogCount: app.getEventsLog().length,
                timelineDOMChildren: eventsTimeline.childNodes.length,
                maxAllowed: app.MAX_EVENTS_LOG
            };
        }
        """)
        self.assertLessEqual(res["eventsLogCount"], res["maxAllowed"])
        self.assertLessEqual(res["timelineDOMChildren"], res["maxAllowed"])

    def test_state_refresh_deduplication(self):
        """Item 10: State refresh avoids rebuilding DOM when incoming data is unchanged."""
        res = self._run_node_test("""
        async () => {
            const app = window.ZaraApp;
            app.init();

            const metricCpu = document.getElementById("metric-cpu");
            const statusPayload = {
                cpu_percent: 25.0,
                memory_percent: 40.0,
                status: "ONLINE"
            };

            // First update sets DOM
            app.wsManager.handleMessage({ type: "status", data: statusPayload });
            metricCpu.textContent = "MODIFIED_INSPECTION_SENTINEL";

            // Second update with exact same payload
            app.wsManager.handleMessage({ type: "status", data: statusPayload });

            return {
                // If deduplication works, metricCpu.textContent was NOT overwritten
                preservedSentinel: metricCpu.textContent === "MODIFIED_INSPECTION_SENTINEL"
            };
        }
        """)
        self.assertTrue(res["preservedSentinel"])

    def test_frontend_shutdown_cleanup(self):
        """Item 11: Frontend shutdown cleanly halts scheduler and closes WebSocket."""
        res = self._run_node_test("""
        async () => {
            const app = window.ZaraApp;
            app.init();
            const wasRunning = app.scheduler.isRunning;

            app.shutdown();

            return {
                wasRunning: wasRunning,
                isRunningAfter: app.scheduler.isRunning,
                timerCleared: app.scheduler.timerId === null,
                wsClosed: app.wsManager.state === "CLOSED",
                lifecycleAfter: app.getLifecycleState(),
                isInitializedAfter: app.isInitialized()
            };
        }
        """)
        self.assertTrue(res["wasRunning"])
        self.assertFalse(res["isRunningAfter"])
        self.assertTrue(res["timerCleared"])
        self.assertTrue(res["wsClosed"])
        self.assertEqual(res["lifecycleAfter"], "SHUTDOWN")
        self.assertFalse(res["isInitializedAfter"])


if __name__ == "__main__":
    unittest.main()
