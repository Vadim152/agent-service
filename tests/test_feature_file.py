import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from domain.models import FeatureFile, FeatureScenario
from tools.feature_generator import FeatureGenerator


class FeatureFileToGherkinTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = FeatureGenerator()

    def test_to_gherkin_with_tags_and_background(self) -> None:
        feature = FeatureFile(
            name="User login feature",
            description="Users can log in to the system.",
            language="en",
            tags=["ui", "smoke"],
            background_steps=["Given application is opened", "And user is on login page"],
            scenarios=[
                FeatureScenario(
                    name="Successful login",
                    tags=["positive"],
                    steps=[
                        "Given registered user exists",
                        "When the user submits valid credentials",
                        "Then the dashboard is displayed",
                    ],
                )
            ],
        )

        expected = self.generator.render_feature(feature)

        self.assertEqual(expected, feature.to_gherkin())

    def test_to_gherkin_without_tags_or_background(self) -> None:
        feature = FeatureFile(
            name="Password reset",
            description=None,
            language="ru",
            tags=[],
            background_steps=[],
            scenarios=[
                FeatureScenario(
                    name="User requests password reset",
                    tags=[],
                    steps=["Когда пользователь запрашивает сброс пароля"],
                )
            ],
        )

        expected = self.generator.render_feature(feature)

        self.assertEqual(expected, feature.to_gherkin())
        self.assertTrue(feature.to_gherkin().endswith("\n"))

    def test_to_gherkin_multiple_scenarios(self) -> None:
        feature = FeatureFile(
            name="Cart operations",
            description="Users manage items in cart.",
            language="en",
            tags=[],
            background_steps=[],
            scenarios=[
                FeatureScenario(
                    name="Add item",
                    tags=["critical"],
                    steps=[
                        "Given an empty cart",
                        "When user adds an item",
                        "Then the item appears in the cart",
                    ],
                ),
                FeatureScenario(
                    name="Remove item",
                    tags=[],
                    steps=[
                        "Given a cart with items",
                        "When user removes an item",
                        "Then the cart is updated",
                    ],
                ),
            ],
        )

        expected = self.generator.render_feature(feature)

        self.assertEqual(expected, feature.to_gherkin())

    def test_to_gherkin_renders_testcase_tag_for_feature_and_scenario(self) -> None:
        feature = FeatureFile(
            name="Jira testcase",
            description=None,
            language="en",
            tags=["SCBC-T1"],
            background_steps=[],
            scenarios=[
                FeatureScenario(
                    name="Resolved from Jira",
                    tags=["SCBC-T1"],
                    steps=["Given data is prepared"],
                )
            ],
        )

        rendered = feature.to_gherkin()
        lines = rendered.splitlines()
        self.assertEqual(lines[1], "@SCBC-T1")
        self.assertEqual(rendered.count("@SCBC-T1"), 2)
        self.assertIn("Scenario: Resolved from Jira", rendered)


if __name__ == "__main__":
    unittest.main()
