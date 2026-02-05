from __future__ import annotations

from pathlib import Path

from infrastructure.artifact_store import ArtifactStore
from infrastructure.run_state_store import RunStateStore
from self_healing.failure_classifier import FailureClassifier
from self_healing.remediation import RemediationPlaybooks


def test_failure_classifier_taxonomy() -> None:
    classifier = FailureClassifier()
    result = classifier.classify({"stderr": "connection reset by peer timeout 503"})
    assert result.category == "infra"
    assert result.confidence > 0.5


def test_remediation_playbooks_allowlist() -> None:
    playbooks = RemediationPlaybooks()
    decision = playbooks.decide("flaky")
    assert decision.safe is True
    applied = playbooks.apply(decision)
    assert applied["applied"] is True


def test_state_and_artifact_store(tmp_path: Path) -> None:
    state = RunStateStore()
    state.put_job({"job_id": "j1", "status": "queued"})
    state.append_event("j1", "job.queued", {"jobId": "j1"})
    events, size = state.list_events("j1")
    assert size == 1
    assert events[0]["event_type"] == "job.queued"

    artifacts = ArtifactStore(tmp_path)
    uri = artifacts.write_text(job_id="j1", run_id="r1", attempt_id="a1", name="stdout.log", content="ok")
    assert Path(uri).exists()
