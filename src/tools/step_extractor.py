"""РР·РІР»РµС‡РµРЅРёРµ Cucumber-С€Р°РіРѕРІ РёР· РёСЃС…РѕРґРЅС‹С… С„Р°Р№Р»РѕРІ С‚РµСЃС‚РѕРІРѕРіРѕ С„СЂРµР№РјРІРѕСЂРєР°."""
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
    """Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅР°СЏ СЃС‚СЂСѓРєС‚СѓСЂР° РґР»СЏ РЅР°Р№РґРµРЅРЅРѕР№ Р°РЅРЅРѕС‚Р°С†РёРё С€Р°РіР°."""

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
        """Р’РѕР·РІСЂР°С‰Р°РµС‚ СЃС‚СЂРѕРєРѕРІРѕРµ РїСЂРµРґСЃС‚Р°РІР»РµРЅРёРµ СЂРµРіСѓР»СЏСЂРєРё (РїРѕРєР° С‚РѕС‚ Р¶Рµ РїР°С‚С‚РµСЂРЅ)."""

        return self.pattern


class StepExtractor:
    """РР·РІР»РµРєР°РµС‚ РѕРїСЂРµРґРµР»РµРЅРёСЏ С€Р°РіРѕРІ BDD РёР· РёСЃС…РѕРґРЅРёРєРѕРІ, РёСЃРїРѕР»СЊР·СѓСЏ FsRepository.

    РџРѕРґРґРµСЂР¶РёРІР°СЋС‚СЃСЏ Р°РЅРЅРѕС‚Р°С†РёРё Java/Kotlin/Groovy/Python РІРёРґР°
    ``@Given("...")``, ``@When("^")`` Рё С‚.Рґ. Р›РѕРіРёРєР° РЅР°РјРµСЂРµРЅРЅРѕ РїСЂРѕСЃС‚Р°СЏ Рё
    РѕСЂРёРµРЅС‚РёСЂРѕРІР°РЅР° РЅР° РїРѕСЃС‚СЂРѕС‡РЅС‹Р№ СЂР°Р·Р±РѕСЂ С„Р°Р№Р»РѕРІ, С‡С‚РѕР±С‹ Р±С‹СЃС‚СЂРѕ РїРѕР»СѓС‡РёС‚СЊ С‡РµСЂРЅРѕРІРѕР№
    РёРЅРґРµРєСЃ С€Р°РіРѕРІ. Р’ Р±СѓРґСѓС‰РµРј СЃСЋРґР° РјРѕР¶РЅРѕ РґРѕР±Р°РІРёС‚СЊ РїРѕР»РЅРѕС†РµРЅРЅС‹Р№ СЂР°Р·Р±РѕСЂ AST Рё
    СЂР°СЃС€РёСЂРёС‚СЊ РїРѕРґРґРµСЂР¶РєСѓ СЏР·С‹РєРѕРІ.
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
            "**/*StepDefinitions.java",
            "**/*StepDefinitions.kt",
            "**/*StepDefinitions.groovy",
            "**/*StepDefinitions.py",
            "**/*StepDefinition.java",
            "**/*StepDefinition.kt",
            "**/*StepDefinition.groovy",
            "**/*StepDefinition.py",
        ]

    def extract_steps(self) -> list[StepDefinition]:
        """РџСЂРѕС…РѕРґРёС‚ РїРѕ РёСЃС…РѕРґРЅРёРєР°Рј Рё РІРѕР·РІСЂР°С‰Р°РµС‚ СЃРїРёСЃРѕРє РЅР°Р№РґРµРЅРЅС‹С… С€Р°РіРѕРІ."""

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
        """РќР°С…РѕРґРёС‚ Р°РЅРЅРѕС‚Р°С†РёРё С€Р°РіРѕРІ РїРѕ СЃС‚СЂРѕРєР°Рј С„Р°Р№Р»Р° Рё РѕРєСЂСѓР¶РµРЅРёРµ РєР»Р°СЃСЃР°/РјРµС‚РѕРґР°."""

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
        """РС‰РµС‚ РѕР±СЉСЏРІР»РµРЅРёРµ РјРµС‚РѕРґР° РІ РЅРµСЃРєРѕР»СЊРєРёС… СЃР»РµРґСѓСЋС‰РёС… СЃС‚СЂРѕРєР°С…."""

        METHOD_RE = re.compile(
            r"(?:\bfun\s+)?(?P<name>[A-Za-z_][\w]*)\s*\((?P<params>[^)]*)\)",
            re.UNICODE,
        )
        parameters: list[tuple[str | None, str | None]] = []
        signature = ""
        started = False
        for line in lines[start_index - 1 : start_index + 20]:
            stripped = line.strip()
            if not stripped:
                continue
            if _ANNOTATION_RE.search(line):
                continue

            if "(" in stripped:
                started = True
            if started:
                signature = f"{signature} {stripped}".strip()

            method_match = METHOD_RE.search(signature if started else stripped)
            if not method_match:
                if started and "{" in stripped:
                    break
                continue
            method_name = method_match.group("name")
            params_block = method_match.group("params")
            parameters = StepExtractor._parse_method_parameters(params_block)
            return method_name, parameters
        return None, parameters

    @staticmethod
    def _parse_method_parameters(params_block: str) -> list[tuple[str | None, str | None]]:
        """Р“СЂСѓР±С‹Р№ СЂР°Р·Р±РѕСЂ РїР°СЂР°РјРµС‚СЂРѕРІ РјРµС‚РѕРґР° Java/Kotlin."""

        parameters: list[tuple[str | None, str | None]] = []
        for raw_param in filter(None, (part.strip() for part in params_block.split(","))):
            if ":" in raw_param:  # Kotlin СЃС‚РёР»СЊ
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
        """РћРїСЂРµРґРµР»СЏРµС‚ С‚РёРї РїР°С‚С‚РµСЂРЅР° С€Р°РіР°."""

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
        """РР·РІР»РµРєР°РµС‚ РїР°СЂР°РјРµС‚СЂС‹ С€Р°РіР° СЃ РёРјРµРЅР°РјРё, С‚РёРїР°РјРё Рё РїР»РµР№СЃС…РѕР»РґРµСЂР°РјРё."""

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
        """РР·РІР»РµРєР°РµС‚ РїР»РµР№СЃС…РѕР»РґРµСЂС‹ Cucumber Expression Рё РёС… С‚РёРїС‹."""

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
        for idx, match in enumerate(re.finditer(r"\{([^{}]*)\}", pattern), start=1):
            placeholder = match.group(0)
            content = match.group(1).strip()
            normalized = content.split(":")[-1].strip().casefold()
            if not normalized:
                normalized = "string"
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
        """Extracts named and positional capturing groups from a regex pattern."""

        parameters: list[dict[str, str | None]] = []
        stack: list[dict[str, int | bool | str | None]] = []
        escaped = False
        in_char_class = False
        i = 0
        while i < len(pattern):
            ch = pattern[i]
            if escaped:
                escaped = False
                i += 1
                continue

            if ch == "\\":
                escaped = True
                i += 1
                continue

            if ch == "[" and not in_char_class:
                in_char_class = True
                i += 1
                continue
            if ch == "]" and in_char_class:
                in_char_class = False
                i += 1
                continue
            if in_char_class:
                i += 1
                continue

            if ch == "(":
                name: str | None = None
                capturing = True
                if i + 1 < len(pattern) and pattern[i + 1] == "?":
                    suffix = pattern[i + 2 : i + 5]
                    if suffix.startswith("P<"):
                        name_start = i + 4
                        name_end = pattern.find(">", name_start)
                        if name_end > name_start:
                            name = pattern[name_start:name_end]
                            capturing = True
                    else:
                        capturing = False
                stack.append({"start": i, "capturing": capturing, "name": name})
                i += 1
                continue

            if ch == ")" and stack:
                group = stack.pop()
                if group.get("capturing"):
                    start = int(group["start"])
                    parameters.append(
                        {
                            "name": str(group.get("name")) if group.get("name") else None,
                            "placeholder": pattern[start : i + 1],
                            "type": None,
                        }
                    )
                i += 1
                continue

            i += 1
        return parameters

