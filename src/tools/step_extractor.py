"""Извлечение Cucumber-шагов из исходных файлов тестового фреймворка."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from domain.enums import StepKeyword, StepPatternType
from domain.models import StepDefinition, StepImplementation, StepParameter
from infrastructure.fs_repo import FsRepository
from tools.cucumber_expression import cucumber_expression_to_regex


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
    class_name: str | None = None
    method_name: str | None = None
    method_parameters: list[tuple[str | None, str | None]] = None  # (name, type)

    def __post_init__(self) -> None:
        self.method_parameters = self.method_parameters or []

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
                pattern_type = self._detect_pattern_type(annotation.pattern)
                regex = (
                    cucumber_expression_to_regex(annotation.pattern)
                    if pattern_type is StepPatternType.CUCUMBER_EXPRESSION
                    else annotation.pattern
                )
                steps.append(
                    StepDefinition(
                        id=step_id,
                        keyword=annotation.keyword,
                        pattern=annotation.pattern,
                        regex=regex,
                        code_ref=step_id,
                        pattern_type=pattern_type,
                        parameters=self._extract_parameters(
                            annotation.pattern,
                            pattern_type,
                            annotation.method_parameters,
                        ),
                        tags=[],
                        language=None,
                        implementation=StepImplementation(
                            file=str(relative_path),
                            line=annotation.line_number,
                            class_name=annotation.class_name,
                            method_name=annotation.method_name,
                        ),
                    )
                )
        return steps

    @staticmethod
    def _iter_annotations(lines: Iterable[str]) -> Iterable[ExtractedAnnotation]:
        """Находит аннотации шагов по строкам файла и окружение класса/метода."""

        normalized_lines = list(lines)
        class_stack: list[tuple[str, int]] = []  # (class_name, depth_at_open)
        pending_class: str | None = None
        brace_depth = 0
        for idx, line in enumerate(normalized_lines, start=1):
            open_braces = line.count("{")
            close_braces = line.count("}")

            if pending_class and open_braces:
                class_stack.append((pending_class, brace_depth + open_braces))
                pending_class = None

            class_match = re.search(r"\b(class|object)\s+(?P<name>[A-Za-z_][\w]*)", line)
            if class_match:
                class_name = class_match.group("name")
                if open_braces:
                    class_stack.append((class_name, brace_depth + open_braces))
                else:
                    pending_class = class_name

            match = _ANNOTATION_RE.search(line)
            if match:
                raw_keyword, _, pattern = match.groups()
                annotation_keyword = StepKeyword.from_string(raw_keyword)
                method_name, method_params = StepExtractor._find_method_context(
                    normalized_lines, idx
                )
                class_name = class_stack[-1][0] if class_stack else None
                yield ExtractedAnnotation(
                    keyword=annotation_keyword,
                    pattern=pattern,
                    line_number=idx,
                    class_name=class_name,
                    method_name=method_name,
                    method_parameters=method_params,
                )

            brace_depth += open_braces - close_braces
            while class_stack and brace_depth < class_stack[-1][1]:
                class_stack.pop()

    @staticmethod
    def _find_method_context(
        lines: Sequence[str], start_index: int
    ) -> tuple[str | None, list[tuple[str | None, str | None]]]:
        """Ищет объявление метода в нескольких следующих строках."""

        METHOD_RE = re.compile(
            r"(?P<name>[A-Za-z_][\w]*)\s*\((?P<params>[^)]*)\)", re.UNICODE
        )
        parameters: list[tuple[str | None, str | None]] = []
        for line in lines[start_index - 1 : start_index + 6]:
            if _ANNOTATION_RE.search(line):
                continue
            method_match = METHOD_RE.search(line)
            if not method_match:
                continue
            method_name = method_match.group("name")
            params_block = method_match.group("params")
            parameters = StepExtractor._parse_method_parameters(params_block)
            return method_name, parameters
        return None, parameters

    @staticmethod
    def _parse_method_parameters(params_block: str) -> list[tuple[str | None, str | None]]:
        """Грубый разбор параметров метода Java/Kotlin."""

        parameters: list[tuple[str | None, str | None]] = []
        for raw_param in filter(None, (part.strip() for part in params_block.split(","))):
            if ":" in raw_param:  # Kotlin стиль
                name_part, type_part = [segment.strip() for segment in raw_param.split(":", 1)]
                name_tokens = name_part.split()
                name = name_tokens[-1] if name_tokens else None
                parameters.append((name, type_part or None))
                continue

            tokens = raw_param.split()
            if not tokens:
                continue
            name = tokens[-1]
            type_hint = " ".join(tokens[:-1]) if len(tokens) > 1 else None
            parameters.append((name, type_hint or None))
        return parameters

    @staticmethod
    def _detect_pattern_type(pattern: str) -> StepPatternType:
        """Определяет тип паттерна шага."""

        stripped = pattern.strip()
        if stripped.startswith("^") or re.search(r"\\.|\[|\]|\(\?|\$", pattern):
            return StepPatternType.REGULAR_EXPRESSION
        if "{" in pattern and "}" in pattern:
            return StepPatternType.CUCUMBER_EXPRESSION
        return StepPatternType.CUCUMBER_EXPRESSION

    @staticmethod
    def _extract_parameters(
        pattern: str,
        pattern_type: StepPatternType,
        method_parameters: list[tuple[str | None, str | None]] | None = None,
    ) -> list[StepParameter]:
        """Извлекает параметры шага с именами, типами и плейсхолдерами."""

        method_parameters = method_parameters or []
        if pattern_type is StepPatternType.CUCUMBER_EXPRESSION:
            raw_parameters = StepExtractor._parse_cucumber_placeholders(pattern)
        else:
            raw_parameters = StepExtractor._parse_regex_groups(pattern)

        parameters: list[StepParameter] = []
        for idx, raw in enumerate(raw_parameters):
            method_param = method_parameters[idx] if idx < len(method_parameters) else (None, None)
            name = method_param[0] or raw.get("name") or f"group{idx + 1}"
            param_type = raw.get("type") or method_param[1]
            parameters.append(
                StepParameter(
                    name=name,
                    type=param_type,
                    placeholder=raw.get("placeholder"),
                )
            )
        return parameters

    @staticmethod
    def _parse_cucumber_placeholders(pattern: str) -> list[dict[str, str | None]]:
        """Извлекает плейсхолдеры Cucumber Expression и их типы."""

        type_map = {
            "int": "int",
            "integer": "int",
            "float": "float",
            "double": "double",
            "word": "word",
            "string": "string",
            "byte": "byte",
            "short": "short",
            "long": "long",
            "bigdecimal": "bigdecimal",
        }

        parameters: list[dict[str, str | None]] = []
        for idx, match in enumerate(re.finditer(r"\{([^{}]+)\}", pattern), start=1):
            placeholder = match.group(0)
            content = match.group(1).strip()
            normalized = content.casefold()
            inferred_type = type_map.get(normalized)
            sanitized_name = re.sub(r"\W+", "_", content).strip("_") or None
            name = sanitized_name or (f"arg{idx}" if inferred_type else None)
            parameters.append(
                {
                    "name": name,
                    "type": inferred_type,
                    "placeholder": placeholder,
                }
            )
        return parameters

    @staticmethod
    def _parse_regex_groups(pattern: str) -> list[dict[str, str | None]]:
        """Извлекает именованные и позиционные группы из регулярного выражения."""

        parameters: list[dict[str, str | None]] = []
        group_pattern = re.compile(r"\((?!\?:)(?P<body>\?P<(?P<name>[^>]+)>[^)]*|[^)]*)\)")
        for match in group_pattern.finditer(pattern):
            full_group = match.group(0)
            name = match.group("name")
            parameters.append({"name": name, "placeholder": full_group, "type": None})
        return parameters
