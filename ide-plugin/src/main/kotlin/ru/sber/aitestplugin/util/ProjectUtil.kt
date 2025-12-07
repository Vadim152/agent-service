package ru.sber.aitestplugin.util

import com.intellij.openapi.project.Project

/**
 * Утилиты для работы с путями проекта.
 */
object ProjectUtil {
    /** Возвращает корень проекта или пустую строку. */
    fun projectRoot(project: Project?): String = project?.basePath ?: ""
}
