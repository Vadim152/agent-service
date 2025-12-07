"""Абстракция работы с файловой системой проекта.

FsRepository предоставляет единый интерфейс для агентов, позволяя искать
и читать файлы в репозитории независимо от конкретной IDE или ОС. Все пути
хранятся относительно корня проекта, чтобы избежать привязки к окружению
запуска.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


class FsRepository:
    """Работа с файловой системой репозитория проекта."""

    def __init__(self, root_path: str) -> None:
        self._root = Path(root_path).resolve()

    def get_root_path(self) -> str:
        """Возвращает абсолютный путь к корню проекта."""

        return str(self._root)

    def iter_source_files(self, patterns: list[str]) -> Iterable[str]:
        """Итерирует по файлам, соответствующим заданным glob-паттернам.

        Args:
            patterns: Список glob-паттернов (например, ["**/*Steps.java", "**/*.py"]).

        Yields:
            Относительные пути файлов, подходящих под паттерны.
        """

        seen: set[Path] = set()
        for pattern in patterns:
            for path in self._root.glob(pattern):
                if path.is_file():
                    rel_path = path.relative_to(self._root)
                    if rel_path not in seen:
                        seen.add(rel_path)
                        yield rel_path.as_posix()

    def read_text_file(self, relative_path: str) -> str:
        """Читает текстовый файл по относительному пути от корня проекта."""

        file_path = self._root / relative_path
        return file_path.read_text(encoding="utf-8")

    def write_text_file(self, relative_path: str, content: str, create_dirs: bool = True) -> None:
        """Записывает текстовый файл, при необходимости создавая директории."""

        file_path = self._root / relative_path
        if create_dirs:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    def exists(self, relative_path: str) -> bool:
        """Проверяет существование файла или директории по относительному пути."""

        return (self._root / relative_path).exists()

