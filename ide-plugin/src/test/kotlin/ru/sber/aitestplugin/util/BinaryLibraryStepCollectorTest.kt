package ru.sber.aitestplugin.util

import com.intellij.openapi.application.ReadAction
import com.intellij.openapi.vfs.JarFileSystem
import com.intellij.openapi.vfs.LocalFileSystem
import com.intellij.testFramework.fixtures.BasePlatformTestCase
import org.objectweb.asm.ClassWriter
import org.objectweb.asm.Opcodes
import java.nio.file.Files
import java.nio.file.Path
import java.util.jar.JarEntry
import java.util.jar.JarOutputStream

class BinaryLibraryStepCollectorTest : BasePlatformTestCase() {

    fun testCollectsStepsFromCompiledBinaryJar() {
        val jarPath = buildBinaryLibraryJar()
        val localJar = LocalFileSystem.getInstance().refreshAndFindFileByNioFile(jarPath)
        assertNotNull(localJar)
        val jarRoot = JarFileSystem.getInstance().getJarRootForLocalFile(localJar!!)
        assertNotNull(jarRoot)

        val result = ReadAction.compute<BinaryLibraryScanResult, RuntimeException> {
            BinaryLibraryStepCollector.collectFromRoots(project, listOf(jarRoot!!))
        }

        assertEquals(1, result.steps.size)
        assertEquals(1, result.classRoots.size)

        val step = result.steps.single()
        assertEquals("Given", step.keyword)
        assertEquals("open dependency app", step.pattern)
        assertEquals("cucumberExpression", step.patternType)
        assertTrue(step.id.startsWith("dep["))
        assertNotNull(step.implementation)
        assertTrue(step.implementation!!.file!!.contains("binary-steps.jar!/cucumber/steps/commons/CommonActionsSteps.class"))
        assertEquals("cucumber.steps.commons.CommonActionsSteps", step.implementation!!.className)
        assertEquals("openDependencyApp", step.implementation!!.methodName)
        assertEquals(1, step.parameters!!.size)
        assertEquals("screenName", step.parameters!!.single().name)
        assertEquals("String", step.parameters!!.single().type)
    }

    fun testCollectsStepsFromCompiledBinaryJarWithRussianAnnotations() {
        val jarPath = buildBinaryLibraryJar(annotationInternalName = "io/cucumber/java/ru/Когда")
        val localJar = LocalFileSystem.getInstance().refreshAndFindFileByNioFile(jarPath)
        assertNotNull(localJar)
        val jarRoot = JarFileSystem.getInstance().getJarRootForLocalFile(localJar!!)
        assertNotNull(jarRoot)

        val result = ReadAction.compute<BinaryLibraryScanResult, RuntimeException> {
            BinaryLibraryStepCollector.collectFromRoots(project, listOf(jarRoot!!))
        }

        assertEquals(1, result.steps.size)
        val step = result.steps.single()
        assertEquals("When", step.keyword)
        assertEquals("open dependency app", step.pattern)
        assertNotNull(step.implementation)
        assertEquals("cucumber.steps.commons.CommonActionsSteps", step.implementation!!.className)
        assertEquals("openDependencyApp", step.implementation!!.methodName)
    }

    private fun buildBinaryLibraryJar(
        annotationInternalName: String = "io/cucumber/java/en/Given",
    ): Path {
        val workspace = Files.createTempDirectory("binary-library-steps")
        val outputRoot = Files.createDirectories(workspace.resolve("out"))
        val jarPath = workspace.resolve("binary-steps.jar")

        writeClass(
            outputRoot.resolve("$annotationInternalName.class"),
            buildStepAnnotationClass(annotationInternalName)
        )
        writeClass(
            outputRoot.resolve("cucumber/steps/commons/CommonActionsSteps.class"),
            buildStepClass(annotationInternalName)
        )

        jarCompiledClasses(outputRoot, jarPath)
        return jarPath
    }

    private fun writeClass(target: Path, bytes: ByteArray) {
        Files.createDirectories(target.parent)
        Files.write(target, bytes)
    }

    private fun buildStepAnnotationClass(annotationInternalName: String): ByteArray {
        val writer = ClassWriter(0)
        writer.visit(
            Opcodes.V17,
            Opcodes.ACC_PUBLIC or Opcodes.ACC_ABSTRACT or Opcodes.ACC_INTERFACE or Opcodes.ACC_ANNOTATION,
            annotationInternalName,
            null,
            "java/lang/Object",
            arrayOf("java/lang/annotation/Annotation")
        )
        writer.visitAnnotation("Ljava/lang/annotation/Retention;", true).apply {
            visitEnum("value", "Ljava/lang/annotation/RetentionPolicy;", "RUNTIME")
            visitEnd()
        }
        writer.visitAnnotation("Ljava/lang/annotation/Target;", true).apply {
            val values = visitArray("value")
            values.visitEnum(null, "Ljava/lang/annotation/ElementType;", "METHOD")
            values.visitEnd()
            visitEnd()
        }
        writer.visitMethod(
            Opcodes.ACC_PUBLIC or Opcodes.ACC_ABSTRACT,
            "value",
            "()Ljava/lang/String;",
            null,
            null
        ).visitEnd()
        writer.visitEnd()
        return writer.toByteArray()
    }

    private fun buildStepClass(annotationInternalName: String): ByteArray {
        val writer = ClassWriter(ClassWriter.COMPUTE_FRAMES or ClassWriter.COMPUTE_MAXS)
        writer.visit(
            Opcodes.V17,
            Opcodes.ACC_PUBLIC,
            "cucumber/steps/commons/CommonActionsSteps",
            null,
            "java/lang/Object",
            null
        )

        val constructor = writer.visitMethod(Opcodes.ACC_PUBLIC, "<init>", "()V", null, null)
        constructor.visitCode()
        constructor.visitVarInsn(Opcodes.ALOAD, 0)
        constructor.visitMethodInsn(Opcodes.INVOKESPECIAL, "java/lang/Object", "<init>", "()V", false)
        constructor.visitInsn(Opcodes.RETURN)
        constructor.visitMaxs(0, 0)
        constructor.visitEnd()

        val method = writer.visitMethod(
            Opcodes.ACC_PUBLIC,
            "openDependencyApp",
            "(Ljava/lang/String;)V",
            null,
            null
        )
        method.visitParameter("screenName", 0)
        val annotation = method.visitAnnotation("L$annotationInternalName;", true)
        annotation.visit("value", "open dependency app")
        annotation.visitEnd()
        method.visitCode()
        method.visitInsn(Opcodes.RETURN)
        method.visitMaxs(0, 0)
        method.visitEnd()

        writer.visitEnd()
        return writer.toByteArray()
    }

    private fun jarCompiledClasses(outputRoot: Path, jarPath: Path) {
        JarOutputStream(Files.newOutputStream(jarPath)).use { stream ->
            Files.walk(outputRoot)
                .filter { path -> Files.isRegularFile(path) }
                .forEach { file ->
                    val entryName = outputRoot.relativize(file).toString().replace('\\', '/')
                    stream.putNextEntry(JarEntry(entryName))
                    Files.copy(file, stream)
                    stream.closeEntry()
                }
        }
    }
}
