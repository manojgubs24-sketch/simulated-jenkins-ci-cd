import os
import threading
import time
import webbrowser

from flask import Flask, jsonify, render_template_string, request

from queue_manager import JobQueueManager
from repo_manager import GitRepoManager
from scheduler import Scheduler
from terminal_logger import configure_terminal_output, log


configure_terminal_output()
app = Flask(__name__)
queue_manager = JobQueueManager()
repo_manager = GitRepoManager()
scheduler = Scheduler(queue_manager, repo_manager)
scheduler.start()
HOST = os.getenv("SIM_JENKINS_HOST", "0.0.0.0")
PORT = int(os.getenv("SIM_JENKINS_PORT", "8085"))

PORTAL_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Simulated Jenkins Portal</title>
    <style>
        :root {
            --bg: #0f172a;
            --panel: #111827;
            --panel-2: #1f2937;
            --text: #e5eefb;
            --muted: #94a3b8;
            --accent: #22c55e;
            --accent-2: #38bdf8;
            --danger: #ef4444;
            --border: rgba(148, 163, 184, 0.2);
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: "Segoe UI", Arial, sans-serif;
            color: var(--text);
            background:
                radial-gradient(circle at top right, rgba(56, 189, 248, 0.18), transparent 28%),
                radial-gradient(circle at top left, rgba(34, 197, 94, 0.16), transparent 24%),
                linear-gradient(180deg, #020617 0%, #0f172a 100%);
            min-height: 100vh;
        }
        .page {
            max-width: 1100px;
            margin: 0 auto;
            padding: 32px 20px 48px;
        }
        .hero {
            display: grid;
            gap: 16px;
            margin-bottom: 24px;
        }
        .eyebrow {
            color: var(--accent-2);
            text-transform: uppercase;
            letter-spacing: 0.16em;
            font-size: 12px;
            font-weight: 700;
        }
        h1 {
            margin: 0;
            font-size: clamp(2rem, 4vw, 3.6rem);
            line-height: 1;
        }
        .subtitle {
            margin: 0;
            color: var(--muted);
            max-width: 720px;
            font-size: 1rem;
        }
        .layout {
            display: grid;
            gap: 20px;
            grid-template-columns: 1.1fr 0.9fr;
        }
        .card {
            background: rgba(17, 24, 39, 0.88);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 20px;
            backdrop-filter: blur(10px);
            box-shadow: 0 18px 40px rgba(2, 6, 23, 0.28);
        }
        .card h2 {
            margin: 0 0 14px;
            font-size: 1.1rem;
        }
        .grid {
            display: grid;
            gap: 14px;
        }
        label {
            display: grid;
            gap: 8px;
            color: var(--muted);
            font-size: 0.95rem;
        }
        select, button {
            width: 100%;
            border-radius: 12px;
            border: 1px solid var(--border);
            padding: 12px 14px;
            font: inherit;
        }
        select {
            background: var(--panel-2);
            color: var(--text);
        }
        button {
            cursor: pointer;
            background: linear-gradient(135deg, var(--accent) 0%, #16a34a 100%);
            color: #04110a;
            font-weight: 700;
        }
        button.secondary {
            background: linear-gradient(135deg, var(--accent-2) 0%, #0284c7 100%);
            color: #041018;
        }
        button:disabled {
            opacity: 0.65;
            cursor: progress;
        }
        .status {
            min-height: 24px;
            color: var(--muted);
            font-size: 0.95rem;
        }
        .status.error { color: #fca5a5; }
        .status.success { color: #86efac; }
        .repo-list {
            display: grid;
            gap: 12px;
        }
        .repo-item {
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 14px;
            background: rgba(31, 41, 55, 0.55);
        }
        .repo-item strong {
            display: block;
            margin-bottom: 6px;
        }
        .chips {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .chip {
            padding: 6px 10px;
            border-radius: 999px;
            background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.25);
            color: #bae6fd;
            font-size: 0.85rem;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.92rem;
        }
        th, td {
            text-align: left;
            padding: 10px 8px;
            border-bottom: 1px solid var(--border);
            vertical-align: top;
        }
        th {
            color: var(--muted);
            font-weight: 600;
        }
        .pill {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .pending { background: rgba(250, 204, 21, 0.12); color: #fde68a; }
        .running { background: rgba(56, 189, 248, 0.12); color: #bae6fd; }
        .completed { background: rgba(34, 197, 94, 0.12); color: #86efac; }
        .failed { background: rgba(239, 68, 68, 0.14); color: #fca5a5; }
        @media (max-width: 900px) {
            .layout { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="page">
        <section class="hero">
            <div class="eyebrow">Simulated Jenkins</div>
            <h1>CI/CD Trigger Portal</h1>
            <p class="subtitle">
                Use this portal to simulate Git push events across multiple repositories and branches.
                The backend applies deterministic priority scheduling before workers execute each job.
            </p>
        </section>
        <section class="layout">
            <div class="card">
                <h2>Trigger A Push Event</h2>
                <div class="grid">
                    <label>
                        Repository
                        <select id="repoSelect"></select>
                    </label>
                    <label>
                        Branch
                        <select id="branchSelect"></select>
                    </label>
                    <button id="triggerButton">Trigger Push</button>
                    <button id="sampleButton" class="secondary">Trigger All 6 Sample Pushes</button>
                    <div id="status" class="status">Portal ready.</div>
                </div>
            </div>
            <div class="card">
                <h2>GitHub Target And Priority Catalog</h2>
                <div id="integrationBox" style="margin-bottom: 16px; color: var(--muted);"></div>
                <div id="repoList" class="repo-list"></div>
            </div>
        </section>
        <section class="card" style="margin-top: 20px;">
            <h2>Queued And Executed Jobs</h2>
            <table>
                <thead>
                    <tr>
                        <th>Repo</th>
                        <th>Branch</th>
                        <th>Priority</th>
                        <th>Language</th>
                        <th>Status</th>
                        <th>Reason</th>
                    </tr>
                </thead>
                <tbody id="jobsTable"></tbody>
            </table>
        </section>
    </div>
    <script>
        const repoSelect = document.getElementById("repoSelect");
        const branchSelect = document.getElementById("branchSelect");
        const triggerButton = document.getElementById("triggerButton");
        const sampleButton = document.getElementById("sampleButton");
        const jobsTable = document.getElementById("jobsTable");
        const repoList = document.getElementById("repoList");
        const integrationBox = document.getElementById("integrationBox");
        const statusEl = document.getElementById("status");
        let catalog = [];

        function setStatus(message, type = "") {
            statusEl.textContent = message;
            statusEl.className = type ? `status ${type}` : "status";
        }

        function renderCatalog() {
            repoList.innerHTML = "";
            catalog.forEach((item) => {
                const wrapper = document.createElement("div");
                wrapper.className = "repo-item";
                wrapper.innerHTML = `
                    <strong>${item.repo}</strong>
                    <div style="color: var(--muted); margin-bottom: 10px;">
                        Language: ${item.language} | Repo rank: ${item.priority_rank}
                    </div>
                    <div class="chips">
                        ${item.branches.map((branch) => `<span class="chip">${branch}</span>`).join("")}
                    </div>
                `;
                repoList.appendChild(wrapper);
            });
        }

        function renderIntegration(info) {
            integrationBox.innerHTML = `
                <div><strong>Repository:</strong> ${info.repository_url || "Not configured"}</div>
                <div><strong>Branch pattern:</strong> ${info.branch_pattern}</div>
                <div><strong>Runtime mirror:</strong> ${info.mirror_path}</div>
            `;
        }

        function populateRepos() {
            repoSelect.innerHTML = "";
            catalog.forEach((item, index) => {
                const option = document.createElement("option");
                option.value = item.repo;
                option.textContent = item.repo;
                if (index === 0) {
                    option.selected = true;
                }
                repoSelect.appendChild(option);
            });
            populateBranches();
        }

        function populateBranches() {
            const selectedRepo = repoSelect.value;
            const entry = catalog.find((item) => item.repo === selectedRepo);
            branchSelect.innerHTML = "";
            (entry?.branches || []).forEach((branch, index) => {
                const option = document.createElement("option");
                option.value = branch;
                option.textContent = branch;
                if (index === 0) {
                    option.selected = true;
                }
                branchSelect.appendChild(option);
            });
        }

        function renderJobs(jobs) {
            jobsTable.innerHTML = "";
            jobs.forEach((job) => {
                const row = document.createElement("tr");
                row.innerHTML = `
                    <td>${job.repo}</td>
                    <td>${job.branch}</td>
                    <td>${job.priority}</td>
                    <td>${job.language}</td>
                    <td><span class="pill ${job.status}">${job.status}</span></td>
                    <td>${job.priority_reason}</td>
                `;
                jobsTable.appendChild(row);
            });
        }

        async function loadCatalog() {
            const response = await fetch("/catalog");
            catalog = await response.json();
            renderCatalog();
            populateRepos();
        }

        async function loadIntegration() {
            const response = await fetch("/integration/status");
            const info = await response.json();
            renderIntegration(info);
        }

        async function loadJobs() {
            const response = await fetch("/jobs");
            const jobs = await response.json();
            renderJobs(jobs);
        }

        async function triggerPush() {
            const selectedRepo = repoSelect.value;
            const selectedBranch = branchSelect.value;
            triggerButton.disabled = true;
            setStatus(`Triggering push for ${selectedRepo} / ${selectedBranch}...`);
            try {
                const response = await fetch("/webhook", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ repo: selectedRepo, branch: selectedBranch }),
                });
                const job = await response.json();
                if (!response.ok) {
                    throw new Error(job.error || "Webhook request failed.");
                }
                setStatus(
                    `Queued ${job.repo} / ${job.branch} with priority ${job.priority}.`,
                    "success"
                );
                await loadJobs();
            } catch (error) {
                setStatus(error.message, "error");
            } finally {
                triggerButton.disabled = false;
            }
        }

        async function triggerSamples() {
            sampleButton.disabled = true;
            setStatus("Triggering all 6 sample branch pushes...");
            try {
                const response = await fetch("/simulate/sample-pushes", { method: "POST" });
                const jobs = await response.json();
                if (!response.ok) {
                    throw new Error("Sample push request failed.");
                }
                setStatus(`Queued ${jobs.length} sample pushes.`, "success");
                await loadJobs();
            } catch (error) {
                setStatus(error.message, "error");
            } finally {
                sampleButton.disabled = false;
            }
        }

        repoSelect.addEventListener("change", populateBranches);
        triggerButton.addEventListener("click", triggerPush);
        sampleButton.addEventListener("click", triggerSamples);

        loadCatalog().then(loadJobs);
        loadIntegration();
        setInterval(loadJobs, 2000);
        setInterval(loadIntegration, 5000);
    </script>
</body>
</html>
"""


@app.get("/")
def portal():
    return render_template_string(PORTAL_HTML)


@app.post("/webhook")
def webhook():
    payload = request.get_json(silent=True) or {}
    repo = str(payload.get("repo", "")).strip()
    branch = str(payload.get("branch", "")).strip()
    language = queue_manager.resolve_language(
        repo=repo,
        language=str(payload.get("language", "")).strip(),
    )

    if not repo or not branch:
        return (
            jsonify(
                {
                    "error": (
                        "Request body must include non-empty 'repo' and 'branch' fields. "
                        "Language is optional for known repos."
                    )
                }
            ),
            400,
        )

    job = queue_manager.create_job(repo=repo, language=language, branch=branch)
    return jsonify(job), 202


@app.get("/jobs")
def jobs():
    return jsonify(queue_manager.get_all_jobs()), 200


@app.get("/catalog")
def catalog():
    return jsonify(queue_manager.get_repo_catalog()), 200


@app.get("/integration/status")
def integration_status():
    return jsonify(repo_manager.get_status()), 200


@app.post("/simulate/sample-pushes")
def simulate_sample_pushes():
    jobs = queue_manager.create_sample_pushes()
    return jsonify(jobs), 202


if __name__ == "__main__":
    def open_portal_when_ready() -> None:
        time.sleep(1.5)
        portal_url = f"http://127.0.0.1:{PORT}/"
        try:
            webbrowser.open(portal_url)
            log(f"[SERVER] opening trigger portal at {portal_url}")
        except Exception as exc:
            log(f"[SERVER] could not auto-open browser: {exc}")

    threading.Thread(target=open_portal_when_ready, daemon=True).start()
    log(f"[SERVER] starting Flask server on http://127.0.0.1:{PORT}")
    log(f"[SERVER] trigger portal will be available on http://127.0.0.1:{PORT}/")
    app.run(host=HOST, port=PORT, debug=False, threaded=True, use_reloader=False)
