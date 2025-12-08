from tools.step_extractor import StepExtractor
from domain.enums import StepKeyword


def test_extracts_russian_keywords() -> None:
    lines = [
        '@Когда("пользователь нажимает кнопку")',
        '@И("открывается новая страница")',
        '@Тогда("он видит приветствие")',
    ]

    annotations = list(StepExtractor._iter_annotations(lines))

    assert [annotation.keyword for annotation in annotations] == [
        StepKeyword.WHEN,
        StepKeyword.AND,
        StepKeyword.THEN,
    ]
