"""ExecutionSupervisor: явная state machine run -> classify -> remediate -> rerun."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from app.observability import metrics, traced_span
from infrastructure.artifact_store import ArtifactStore
from infrastructure.run_state_store import RunStateStore
from self_healing.failure_classifier import FailureClassifier
from self_healing.remediation import RemediationPlaybooks


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExecutionSupervisor:
    def __init__(
        self,
        *,
        orchestrator,
        run_state_store: RunStateStore,
        artifact_store: ArtifactStore,
        max_auto_reruns: int = 2,
        max_total_duration_s: int = 300,
    ) -> None:
        self.orchestrator = orchestrator
        self.run_state_store = run_state_store
        self.artifact_store = artifact_store
        self.classifier = FailureClassifier()
        self.playbooks = RemediationPlaybooks()
        self.max_auto_reruns = max_auto_reruns
        self.max_total_duration_s = max_total_duration_s

    async def execute_job(self, job_id: str) -> None:
        job = self.run_state_store.get_job(job_id)
        if not job:
            return
        metrics.inc("jobs.started")

        run_id = str(uuid.uuid4())
        self.run_state_store.patch_job(job_id, run_id=run_id, status="running")
        self.run_state_store.append_event(job_id, "job.running", {"jobId": job_id, "runId": run_id})

        start = asyncio.get_running_loop().time()
        succeeded = False
        incident: dict[str, Any] | None = None

        for attempt_index in range(self.max_auto_reruns + 1):
            if asyncio.get_running_loop().time() - start > self.max_total_duration_s:
                break

            attempt_id = str(uuid.uuid4())
            self.run_state_store.append_event(
                job_id,
                "attempt.started",
                {
                    "jobId": job_id,
                    "runId": run_id,
                    "attemptId": attempt_id,
                    "status": "started",
                },
            )

            if self.run_state_store.get_job(job_id).get("status") == "cancelled":
                return

            try:
                with traced_span("run_test_execution"):
                    result = self.orchestrator.generate_feature(
                        job["project_root"],
                        job["test_case_text"],
                        job.get("target_path"),
                        create_file=bool(job.get("create_file")),
                        overwrite_existing=bool(job.get("overwrite_existing")),
                        language=job.get("language"),
                    )
                feature = result.get("feature", {})
                unmatched = feature.get("unmappedSteps", [])
                has_failure = len(unmatched) > 0
                stdout_path = self.artifact_store.write_json(
                    job_id=job_id,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    name="feature-result.json",
                    payload=result,
                )
                artifacts = {"result": str(unmatched), "stdout": f"artifact:{stdout_path}"}

                if not has_failure:
                    succeeded = True
                    metrics.inc("jobs.succeeded_without_rerun")
                    self.run_state_store.append_event(
                        job_id,
                        "attempt.succeeded",
                        {"jobId": job_id, "runId": run_id, "attemptId": attempt_id, "status": "succeeded"},
                    )
                    break

                classification = self.classifier.classify(artifacts)
                self.artifact_store.write_json(
                    job_id=job_id,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    name="failure-classification.json",
                    payload=classification.to_dict(),
                )
                self.run_state_store.append_event(
                    job_id,
                    "attempt.classified",
                    {
                        "jobId": job_id,
                        "runId": run_id,
                        "attemptId": attempt_id,
                        "status": "failed",
                        "classification": classification.to_dict(),
                    },
                )

                if classification.confidence < 0.55:
                    metrics.inc("jobs.low_confidence_failures")
                    incident = self._build_incident(job, run_id, attempt_id, classification.to_dict(), "Low confidence")
                    break

                decision = self.playbooks.decide(classification.category)
                apply_result = self.playbooks.apply(decision)
                self.run_state_store.append_event(
                    job_id,
                    "attempt.remediated",
                    {
                        "jobId": job_id,
                        "runId": run_id,
                        "attemptId": attempt_id,
                        "status": "remediated",
                        "remediation": decision.to_dict(),
                        "result": apply_result,
                    },
                )
                if not apply_result.get("applied"):
                    incident = self._build_incident(job, run_id, attempt_id, classification.to_dict(), decision.notes)
                    break

                self.run_state_store.append_event(
                    job_id,
                    "attempt.rerun_scheduled",
                    {
                        "jobId": job_id,
                        "runId": run_id,
                        "attemptId": attempt_id,
                        "status": "rerun_scheduled",
                    },
                )
                metrics.inc("jobs.rerun_scheduled")
                await asyncio.sleep(0.05)
            except Exception as exc:
                incident = self._build_incident(job, run_id, attempt_id, {"category": "automation", "confidence": 0.9}, str(exc))
                break

        final_status = "succeeded" if succeeded else "needs_attention"
        metrics.inc(f"jobs.final_status.{final_status}")
        incident_uri = None
        if incident:
            incident_uri = self.artifact_store.write_incident(job_id, incident)
            self.run_state_store.append_event(
                job_id,
                "job.incident",
                {
                    "jobId": job_id,
                    "runId": run_id,
                    "incident": incident,
                    "incidentUri": incident_uri,
                },
            )

        self.run_state_store.patch_job(
            job_id,
            status=final_status,
            finished_at=_utcnow(),
            incident_uri=incident_uri,
        )
        self.run_state_store.append_event(
            job_id,
            "job.finished",
            {"jobId": job_id, "runId": run_id, "status": final_status, "incidentUri": incident_uri},
        )

    @staticmethod
    def _build_incident(
        job: dict[str, Any], run_id: str, attempt_id: str, classification: dict[str, Any], reason: str
    ) -> dict[str, Any]:
        return {
            "jobId": job["job_id"],
            "runId": run_id,
            "attemptId": attempt_id,
            "source": "execution_supervisor",
            "classification": classification,
            "summary": f"Auto-remediation stopped: {reason}",
            "createdAt": _utcnow(),
            "hypotheses": [
                "Проверить инфраструктурные зависимости",
                "Проверить тестовые данные и стабильность окружения",
            ],
        }
