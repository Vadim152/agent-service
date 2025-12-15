from infrastructure.fs_repo import FsRepository
from tools.step_extractor import StepExtractor
from domain.enums import StepKeyword, StepPatternType


def test_extracts_java_class_and_method_context(tmp_path) -> None:
    source = """
    package steps;

    public class UiSteps {
        @Given("^user opens (.*)$")
        public void openSite(String url) {}
    }
    """

    root = tmp_path
    (root / "UiSteps.java").write_text(source)

    extractor = StepExtractor(FsRepository(str(root)), patterns=["**/*.java"])
    steps = extractor.extract_steps()

    assert len(steps) == 1
    step = steps[0]

    assert step.keyword is StepKeyword.GIVEN
    assert step.pattern_type is StepPatternType.REGULAR_EXPRESSION
    assert step.implementation.class_name == "UiSteps"
    assert step.implementation.method_name == "openSite"

    assert len(step.parameters) == 1
    assert step.parameters[0].name == "url"
    assert step.parameters[0].placeholder == "(.*)"
    assert step.parameters[0].type == "String"


def test_extracts_kotlin_cucumber_expression(tmp_path) -> None:
    source = """
    package steps

    class UiSteps {
        @When("user opens {string}")
        fun openSite(baseUrl: String) {
        }
    }
    """

    root = tmp_path
    (root / "UiSteps.kt").write_text(source)

    extractor = StepExtractor(FsRepository(str(root)), patterns=["**/*.kt"])
    steps = extractor.extract_steps()

    assert len(steps) == 1
    step = steps[0]

    assert step.keyword is StepKeyword.WHEN
    assert step.pattern_type is StepPatternType.CUCUMBER_EXPRESSION
    assert step.implementation.class_name == "UiSteps"
    assert step.implementation.method_name == "openSite"

    assert len(step.parameters) == 1
    assert step.parameters[0].name == "baseUrl"
    assert step.parameters[0].placeholder == "{string}"
    assert step.parameters[0].type == "string"
