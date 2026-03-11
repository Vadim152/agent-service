package ru.sber.aitestplugin.util

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.nio.file.Files

class IdeProjectResolverTest {

    @Test
    fun `prefers exact base path match over parent project match`() {
        val workspace = Files.createTempDirectory("project-resolver")
        val projectRoot = Files.createDirectories(workspace.resolve("repo"))
        val moduleRoot = Files.createDirectories(projectRoot.resolve("module-a"))

        val result = selectProjectBasePath(
            projectRootHint = moduleRoot.toString(),
            candidateBasePaths = listOf(
                projectRoot.toString(),
                moduleRoot.toString(),
            )
        )

        assertEquals(moduleRoot.toString(), result)
    }

    @Test
    fun `matches parent project when root hint points to nested module`() {
        val workspace = Files.createTempDirectory("project-resolver-parent")
        val projectRoot = Files.createDirectories(workspace.resolve("repo"))
        val nestedRoot = Files.createDirectories(projectRoot.resolve("module-a").resolve("tests"))

        val result = selectProjectBasePath(
            projectRootHint = nestedRoot.toString(),
            candidateBasePaths = listOf(projectRoot.toString())
        )

        assertEquals(projectRoot.toString(), result)
    }

    @Test
    fun `returns null when hint does not match any open project`() {
        val workspace = Files.createTempDirectory("project-resolver-miss")
        val openProject = Files.createDirectories(workspace.resolve("open-repo"))
        val otherProject = Files.createDirectories(workspace.resolve("other-repo"))

        val result = selectProjectBasePath(
            projectRootHint = otherProject.toString(),
            candidateBasePaths = listOf(openProject.toString())
        )

        assertNull(result)
    }
}
