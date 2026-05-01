import os
import threading
import time
import webbrowser

from flask import Flask, jsonify, render_template, request

from queue_manager import JobQueueManager
from repo_manager import GitRepoManager
from scheduler import Scheduler
from terminal_logger import configure_terminal_output, log


configure_terminal_output()
app = Flask(__name__, template_folder="templates")
queue_manager = JobQueueManager()
repo_manager = GitRepoManager()
scheduler = Scheduler(queue_manager, repo_manager)
scheduler.start()
HOST = os.getenv("SIM_JENKINS_HOST", "0.0.0.0")
PORT = int(os.getenv("SIM_JENKINS_PORT", "8085"))
@app.get("/")
def portal():
    return render_template("index.html")


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


@app.get("/history")
def history():
    return jsonify(queue_manager.get_history()), 200


@app.get("/summary")
def summary():
    return jsonify(queue_manager.get_summary()), 200


@app.get("/catalog")
def catalog():
    return jsonify(queue_manager.get_repo_catalog()), 200


@app.get("/integration/status")
def integration_status():
    payload = repo_manager.get_status()
    payload.update(
        {
            "sample_push_count": queue_manager.get_sample_push_count(),
            "repo_count": len(queue_manager.get_repo_catalog()),
            "failure_rate": float(os.getenv("SIM_JENKINS_FAILURE_RATE", "0.0")),
        }
    )
    return jsonify(payload), 200


@app.post("/simulate/sample-pushes")
def simulate_sample_pushes():
    jobs = queue_manager.create_sample_pushes()
    return jsonify(jobs), 202


@app.post("/reset")
def reset():
    queue_manager.reset()
    return jsonify({"message": "Portal queue and history reset."}), 200


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
