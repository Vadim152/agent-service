package ru.sber.aitestplugin.util

import com.intellij.openapi.project.Project
import com.intellij.openapi.project.ProjectManager
import java.nio.file.Path
import java.nio.file.Paths

internal fun resolveIdeProject(
    preferredProject: Project? = null,
    projectRootHint: String? = null,
): Project {
    val projectManager = ProjectManager.getInstance()
    val openProjects = projectManager.openProjects.filter { !it.isDisposed && !it.isDefault }
    val preferredActiveProject = preferredProject?.takeUnless { it.isDisposed || it.isDefault }

    selectProjectBasePath(projectRootHint, openProjects.mapNotNull(Project::getBasePath))
        ?.let { matchedBasePath ->
            openProjects.firstOrNull { it.basePath == matchedBasePath }?.let { return it }
        }

    return preferredActiveProject
        ?: openProjects.firstOrNull()
        ?: preferredProject?.takeUnless { it.isDisposed }
        ?: projectManager.defaultProject
}

internal fun selectProjectBasePath(
    projectRootHint: String?,
    candidateBasePaths: List<String>,
): String? {
    val normalizedHint = normalizeProjectPath(projectRootHint) ?: return null
    val candidates = candidateBasePaths.mapNotNull { candidate ->
        normalizeProjectPath(candidate)?.let { normalized -> candidate to normalized }
    }
    candidates.firstOrNull { (_, normalizedCandidate) -> normalizedCandidate == normalizedHint }
        ?.let { return it.first }
    candidates.firstOrNull { (_, normalizedCandidate) ->
        normalizedHint.startsWith(normalizedCandidate) || normalizedCandidate.startsWith(normalizedHint)
    }?.let { return it.first }
    return null
}

private fun normalizeProjectPath(rawPath: String?): Path? {
    val trimmed = rawPath?.trim().orEmpty()
    if (trimmed.isBlank()) {
        return null
    }
    return try {
        Paths.get(trimmed).normalize()
    } catch (_: Exception) {
        null
    }
}
