from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes_steps import router
from domain.enums import StepKeyword, StepPatternType
from domain.models import StepDefinition, StepImplementation, StepParameter


class _OrchestratorStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.step_index_store = SimpleNamespace(load_steps=lambda _project_root: [])

    def scan_steps(self, project_root: str, additional_roots=None, provided_steps=None) -> dict[str, object]:
        provided_steps = list(provided_steps or [])
        self.calls.append(
            {
                "project_root": project_root,
                "additional_roots": list(additional_roots or []),
                "provided_steps": provided_steps,
            }
        )
        return {
            "projectRoot": project_root,
            "stepsCount": len(provided_steps),
            "scenariosCount": 0,
            "updatedAt": datetime.utcnow().isoformat(),
            "sampleSteps": provided_steps,
            "sampleScenarios": [],
        }


def _build_app() -> tuple[FastAPI, _OrchestratorStub]:
    orchestrator = _OrchestratorStub()
    app = FastAPI()
    app.state.orchestrator = orchestrator
    app.include_router(router)
    return app, orchestrator


def test_scan_steps_accepts_plugin_provided_steps(tmp_path) -> None:
    app, orchestrator = _build_app()
    client = TestClient(app)
    project_root = tmp_path / "project"
    project_root.mkdir()

    payload = {
        "projectRoot": str(project_root),
        "additionalRoots": [],
        "providedSteps": [
            {
                "id": "dep[plugin]:binary-step",
                "keyword": "Given",
                "pattern": "open dependency app",
                "patternType": "cucumberExpression",
                "codeRef": "dep[plugin]:binary-steps.jar!/cucumber/steps/CommonActionsSteps.class#openDependencyApp",
                "parameters": [
                    {
                        "name": "screenName",
                        "type": "String",
                    }
                ],
                "implementation": {
                    "file": "dep[plugin]:binary-steps.jar!/cucumber/steps/CommonActionsSteps.class",
                    "line": None,
                    "className": "cucumber.steps.CommonActionsSteps",
                    "methodName": "openDependencyApp",
                },
            }
        ],
    }

    response = client.post("/platform/steps/scan-steps", json=payload)

    assert response.status_code == 200
    assert response.json()["stepsCount"] == 1
    recorded = orchestrator.calls[-1]
    assert recorded["project_root"] == str(project_root)
    assert recorded["additional_roots"] == []

    provided = recorded["provided_steps"]
    assert isinstance(provided, list)
    assert len(provided) == 1
    step = provided[0]
    assert isinstance(step, StepDefinition)
    assert step.keyword is StepKeyword.GIVEN
    assert step.pattern_type is StepPatternType.CUCUMBER_EXPRESSION
    assert step.implementation == StepImplementation(
        file="dep[plugin]:binary-steps.jar!/cucumber/steps/CommonActionsSteps.class",
        line=None,
        class_name="cucumber.steps.CommonActionsSteps",
        method_name="openDependencyApp",
    )
    assert step.parameters == [StepParameter(name="screenName", type="String", placeholder=None)]
