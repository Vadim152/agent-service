package ru.sber.aitestplugin.util

import com.intellij.openapi.project.Project
import com.intellij.openapi.roots.OrderEnumerator
import com.intellij.openapi.vfs.VfsUtilCore
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths

object StepScanRootsResolver {
    fun resolveAdditionalRoots(project: Project, projectRoot: String): List<String> {
        val primary = normalizePath(projectRoot)
        val roots = linkedSetOf<String>()

        OrderEnumerator.orderEntries(project)
            .librariesOnly()
            .withoutSdk()
            .sources()
            .roots
            .forEach { root ->
                val candidate = normalizePath(VfsUtilCore.urlToPath(root.url)) ?: return@forEach
                if (primary != null && candidate == primary) return@forEach
                roots.add(candidate)
            }

        return roots.toList()
    }

    private fun normalizePath(raw: String): String? {
        val trimmed = raw.trim().removeSuffix("!/")
        if (trimmed.isBlank()) return null
        return try {
            val path = Paths.get(trimmed).normalize()
            if (!Files.exists(path)) return null
            if (!isSupported(path)) return null
            path.toString()
        } catch (_: Exception) {
            null
        }
    }

    private fun isSupported(path: Path): Boolean {
        if (Files.isDirectory(path)) return true
        if (!Files.isRegularFile(path)) return false
        return path.fileName.toString().endsWith(".jar", ignoreCase = true)
    }
}

