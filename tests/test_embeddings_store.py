import tempfile
import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from domain.enums import ScenarioType, StepKeyword
from domain.models import ScenarioCatalogEntry, StepDefinition
from infrastructure.embeddings_store import EmbeddingsStore


class EmbeddingsStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store = EmbeddingsStore(persist_directory=self.tmp_dir.name)
        self.project_root = "/tmp/project-a"
        self.steps = [
            StepDefinition(
                id="1",
                keyword=StepKeyword.GIVEN,
                pattern="user is logged in",
                regex=None,
                code_ref="steps/login.py::login",
                parameters=["user"],
                tags=["auth"],
                language="en",
            ),
            StepDefinition(
                id="2",
                keyword=StepKeyword.WHEN,
                pattern="user opens dashboard",
                regex=None,
                code_ref="steps/navigation.py::open_dashboard",
                parameters=[],
                tags=["navigation"],
                language="en",
            ),
            StepDefinition(
                id="3",
                keyword=StepKeyword.THEN,
                pattern="dashboard is displayed",
                regex=None,
                code_ref="steps/navigation.py::assert_dashboard",
                parameters=[],
                tags=["assert"],
                language="en",
            ),
        ]
        self.scenarios = [
            ScenarioCatalogEntry(
                id="sc-1",
                name="Dashboard: Open dashboard",
                feature_path="dashboard.feature",
                scenario_name="Open dashboard",
                tags=["ui"],
                background_steps=["Given user is logged in"],
                steps=["When user opens dashboard", "Then dashboard is displayed"],
                scenario_type=ScenarioType.NAVIGATION,
                document="Dashboard Open dashboard Given user is logged in When user opens dashboard Then dashboard is displayed",
            )
        ]

    def tearDown(self) -> None:
        self.store.close()
        self.tmp_dir.cleanup()

    def test_index_and_search_returns_similar_steps(self) -> None:
        self.store.index_steps(self.project_root, self.steps)

        results = self.store.search_similar(self.project_root, "user login", top_k=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].pattern, "user is logged in")
        self.assertEqual(results[0].keyword, StepKeyword.GIVEN)

    def test_clear_removes_project_index(self) -> None:
        self.store.index_steps(self.project_root, self.steps)

        self.store.clear(self.project_root)
        results = self.store.search_similar(self.project_root, "dashboard", top_k=3)

        self.assertEqual(results, [])

    def test_index_and_search_returns_similar_scenarios(self) -> None:
        self.store.index_scenarios(self.project_root, self.scenarios)

        results = self.store.get_top_k_scenarios(self.project_root, "open dashboard", top_k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0].scenario_name, "Open dashboard")


if __name__ == "__main__":
    unittest.main()
