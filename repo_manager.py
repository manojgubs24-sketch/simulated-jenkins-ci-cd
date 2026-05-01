import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from terminal_logger import log


DEFAULT_REMOTE_URL = os.getenv(
    "SIM_JENKINS_REMOTE_URL",
    "https://github.com/manojgubs24-sketch/simulated-jenkins-ci-cd.git",
)
DEFAULT_RUNTIME_ROOT = os.getenv("SIM_JENKINS_RUNTIME_ROOT", "")
DISABLE_REMOTE_PUSH = os.getenv("SIM_JENKINS_DISABLE_REMOTE_PUSH", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


class GitRepoManager:
    def __init__(self, project_root: Path | None = None, remote_url: str | None = None) -> None:
        self.project_root = Path(project_root or Path(__file__).resolve().parent)
        if DEFAULT_RUNTIME_ROOT:
            self.runtime_root = Path(DEFAULT_RUNTIME_ROOT)
        else:
            self.runtime_root = self.project_root.parent / ".simulated_jenkins_runtime"
        self.mirror_path = self.runtime_root / "repo_mirror"
        self.remote_name = "github"
        self.remote_url = (remote_url or DEFAULT_REMOTE_URL).strip()
        self.disable_remote_push = DISABLE_REMOTE_PUSH
        self.lock = threading.Lock()
        self.base_branch = "master"

    def get_status(self) -> dict[str, Any]:
        repo_url = self.remote_url.removesuffix(".git") if self.remote_url else ""
        return {
            "remote_name": self.remote_name,
            "remote_url": self.remote_url,
            "repository_url": repo_url,
            "mirror_path": str(self.mirror_path),
            "base_branch": self.base_branch,
            "branch_pattern": "sim/<repo>/<branch>",
            "remote_push_enabled": not self.disable_remote_push,
        }

    def apply_job_update(self, job: dict) -> dict[str, Any]:
        with self.lock:
            self._bootstrap_mirror()
            target_branch = self._target_branch_name(job["repo"], job["branch"])
            self._checkout_branch(target_branch)

            payload = self._write_job_artifacts(job=job, target_branch=target_branch)
            self._run_git(["add", "--all"])
            self._run_git(
                [
                    "commit",
                    "-m",
                    (
                        f"ci: process {job['repo']} {job['branch']} "
                        f"priority={job['priority']}"
                    ),
                ]
            )
            commit_sha = self._run_git(["rev-parse", "HEAD"]).stdout.strip()

            push_status = "local_commit_only"
            push_error = None
            if self.remote_url and not self.disable_remote_push:
                try:
                    self._ensure_remote()
                    self._run_git(
                        [
                            "push",
                            self.remote_name,
                            f"HEAD:refs/heads/{target_branch}",
                        ]
                    )
                    push_status = "pushed"
                except subprocess.CalledProcessError as exc:
                    push_status = "push_failed"
                    push_error = self._format_process_error(exc)
                    log(
                        f"[REPO] push failed branch={target_branch} "
                        f"error={push_error}"
                    )

            return {
                "commit_sha": commit_sha,
                "push_status": push_status,
                "push_error": push_error,
                "target_branch": target_branch,
                "repository_url": self.remote_url.removesuffix(".git"),
                "artifact_path": payload["artifact_path"],
            }

    def _bootstrap_mirror(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        if not (self.mirror_path / ".git").exists():
            if self.mirror_path.exists():
                shutil.rmtree(self.mirror_path)
            self.base_branch = self._current_source_branch()
            shutil.copytree(
                self.project_root,
                self.mirror_path,
                ignore=shutil.ignore_patterns(
                    ".git",
                    "__pycache__",
                    ".ci_runtime",
                    ".simulated_jenkins_runtime",
                ),
            )
            subprocess.run(
                ["git", "init", "-b", self.base_branch],
                cwd=self.mirror_path,
                check=True,
                capture_output=True,
                text=True,
            )
            self._copy_identity_from_source()
            self._run_git(["add", "--all"])
            self._run_git(["commit", "-m", "chore: bootstrap simulated Jenkins mirror"])
        self.base_branch = self._run_git(["branch", "--show-current"]).stdout.strip() or "master"
        self._ensure_remote()

    def _copy_identity_from_source(self) -> None:
        for key in ("user.name", "user.email"):
            value = subprocess.run(
                ["git", "config", "--local", "--get", key],
                cwd=self.project_root,
                check=False,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if value:
                self._run_git(["config", key, value])

    def _current_source_branch(self) -> str:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=self.project_root,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "master"

    def _ensure_remote(self) -> None:
        if not self.remote_url:
            return
        current_remote = self._run_git(
            ["remote", "get-url", self.remote_name],
            check=False,
        )
        if current_remote.returncode == 0:
            if current_remote.stdout.strip() != self.remote_url:
                self._run_git(["remote", "set-url", self.remote_name, self.remote_url])
            return
        self._run_git(["remote", "add", self.remote_name, self.remote_url])

    def _checkout_branch(self, target_branch: str) -> None:
        current_branch = self._run_git(["branch", "--show-current"]).stdout.strip()
        if current_branch == target_branch:
            return

        branch_exists = self._run_git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{target_branch}"],
            check=False,
        )
        if branch_exists.returncode == 0:
            self._run_git(["checkout", target_branch])
            return

        self._run_git(["checkout", self.base_branch])
        self._run_git(["checkout", "-b", target_branch])

    def _write_job_artifacts(self, job: dict, target_branch: str) -> dict[str, str]:
        repo_slug = self._slug(job["repo"])
        branch_slug = self._slug(job["branch"])
        artifact_dir = self.mirror_path / "ci_pipeline_updates" / repo_slug / branch_slug
        artifact_dir.mkdir(parents=True, exist_ok=True)

        history_file = artifact_dir / "history.ndjson"
        run_number = 1
        if history_file.exists():
            run_number = len(history_file.read_text(encoding="utf-8").splitlines()) + 1

        payload = {
            "job_id": job["id"],
            "repo": job["repo"],
            "branch": job["branch"],
            "language": job["language"],
            "priority": job["priority"],
            "priority_reason": job["priority_reason"],
            "dispatch_order": job["dispatch_order"],
            "target_branch": target_branch,
            "run_number": run_number,
            "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        latest_file = artifact_dir / "latest.json"
        latest_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        with history_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

        summary_file = artifact_dir / "README.md"
        summary_file.write_text(
            "\n".join(
                [
                    f"# {job['repo']} / {job['branch']}",
                    "",
                    f"- Priority: `{job['priority']}`",
                    f"- Reason: {job['priority_reason']}",
                    f"- Latest job id: `{job['id']}`",
                    f"- Run count: `{run_number}`",
                    f"- Git branch: `{target_branch}`",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        return {"artifact_path": str(latest_file.relative_to(self.mirror_path))}

    def _target_branch_name(self, repo: str, branch: str) -> str:
        repo_part = self._slug(repo)
        branch_part = "/".join(self._slug(part) for part in branch.split("/"))
        return f"sim/{repo_part}/{branch_part}"

    def _slug(self, value: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower())
        return sanitized.strip("-") or "unknown"

    def _run_git(
        self,
        args: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.mirror_path,
            check=check,
            capture_output=True,
            text=True,
        )

    def _format_process_error(self, exc: subprocess.CalledProcessError) -> str:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        return stderr or stdout or str(exc)
