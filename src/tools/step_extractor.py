"""Извлечение Cucumber-шагов из исходных файлов тестового фреймворка."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

from domain.enums import StepKeyword, StepPatternType
from domain.models import StepDefinition, StepImplementation, StepParameter
from infrastructure.fs_repo import FsRepository


_SUPPORTED_KEYWORDS_PATTERN = "|".join(
    re.escape(keyword) for keyword in sorted(StepKeyword.supported_keywords(), key=len, reverse=True)
)
_ANNOTATION_RE = re.compile(
    rf"@\s*({_SUPPORTED_KEYWORDS_PATTERN})\s*\(\s*([\"\'])(.+?)\2\s*\)",
    re.IGNORECASE,
)


@dataclass
class ExtractedAnnotation:
    """Вспомогательная структура для найденной аннотации шага."""

    keyword: StepKeyword
    pattern: str
    line_number: int

    @property
    def regex(self) -> str:
        """Возвращает строковое представление регулярки (пока тот же паттерн)."""

        return self.pattern


class StepExtractor:
    """Извлекает определения шагов BDD из исходников, используя FsRepository.

    Поддерживаются аннотации Java/Kotlin/Groovy/Python вида
    ``@Given("...")``, ``@When("^")`` и т.д. Логика намеренно простая и
    ориентирована на построчный разбор файлов, чтобы быстро получить черновой
    индекс шагов. В будущем сюда можно добавить полноценный разбор AST и
    расширить поддержку языков.
    """

    def __init__(
        self,
        fs_repo: FsRepository,
        patterns: List[str] | None = None,
    ) -> None:
        self.fs_repo = fs_repo
        self.patterns = patterns or [
            "**/*Steps.java",
            "**/*Steps.kt",
            "**/*Steps.groovy",
            "**/*Steps.py",
        ]

    def extract_steps(self) -> list[StepDefinition]:
        """Проходит по исходникам и возвращает список найденных шагов."""

        steps: list[StepDefinition] = []
        for relative_path in self.fs_repo.iter_source_files(self.patterns):
            content = self.fs_repo.read_text_file(relative_path)
            annotations = list(self._iter_annotations(content.splitlines()))
            for annotation in annotations:
                step_id = f"{relative_path}:{annotation.line_number}"
                steps.append(
                    StepDefinition(
                        id=step_id,
                        keyword=annotation.keyword,
                        pattern=annotation.pattern,
                        regex=annotation.regex,
                        code_ref=step_id,
                        pattern_type=StepPatternType.REGULAR_EXPRESSION,
                        parameters=self._extract_parameters(annotation.pattern),
                        tags=[],
                        language=None,
                        implementation=StepImplementation(
                            file=str(relative_path),
                            line=annotation.line_number,
                        ),
                    )
                )
        return steps

    @staticmethod
    def _iter_annotations(lines: Iterable[str]) -> Iterable[ExtractedAnnotation]:
        """Находит аннотации шагов по строкам файла."""

        for idx, line in enumerate(lines, start=1):
            match = _ANNOTATION_RE.search(line)
            if not match:
                continue
            raw_keyword, _, pattern = match.groups()
            keyword = StepKeyword.from_string(raw_keyword)
            yield ExtractedAnnotation(keyword=keyword, pattern=pattern, line_number=idx)

    @staticmethod
    def _extract_parameters(pattern: str) -> list[StepParameter]:
        """Пытается извлечь имена параметров из шаблона по простым скобкам."""

        params: list[StepParameter] = []
        for idx, match in enumerate(re.finditer(r"\([^)]*\)", pattern), start=1):
            params.append(
                StepParameter(
                    name=f"param{idx}",
                    placeholder=match.group(0),
                )
            )
        return params
