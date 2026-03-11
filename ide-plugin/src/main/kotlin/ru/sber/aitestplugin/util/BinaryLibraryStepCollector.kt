package ru.sber.aitestplugin.util

import com.intellij.openapi.application.ReadAction
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.roots.ContentIterator
import com.intellij.openapi.roots.OrderEnumerator
import com.intellij.openapi.vfs.VfsUtilCore
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.psi.JavaPsiFacade
import com.intellij.psi.PsiAnnotation
import com.intellij.psi.PsiClass
import com.intellij.psi.PsiClassOwner
import com.intellij.psi.PsiLiteralExpression
import com.intellij.psi.PsiManager
import com.intellij.psi.PsiMethod
import ru.sber.aitestplugin.model.StepDefinitionDto
import ru.sber.aitestplugin.model.StepImplementationDto
import ru.sber.aitestplugin.model.StepParameterDto
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import java.security.MessageDigest

data class BinaryLibraryScanResult(
    val classRoots: List<String>,
    val steps: List<StepDefinitionDto>,
)

object BinaryLibraryStepCollector {
    private val logger = Logger.getInstance(BinaryLibraryStepCollector::class.java)

    private val annotationKeywords = mapOf(
        "io.cucumber.java.en.Given" to "Given",
        "io.cucumber.java.en.When" to "When",
        "io.cucumber.java.en.Then" to "Then",
        "io.cucumber.java.en.And" to "And",
        "io.cucumber.java.en.But" to "But",
        "io.cucumber.java.ru.Дано" to "Given",
        "io.cucumber.java.ru.Пусть" to "Given",
        "io.cucumber.java.ru.Допустим" to "Given",
        "io.cucumber.java.ru.Когда" to "When",
        "io.cucumber.java.ru.Если" to "When",
        "io.cucumber.java.ru.Тогда" to "Then",
        "io.cucumber.java.ru.То" to "Then",
        "io.cucumber.java.ru.И" to "And",
        "io.cucumber.java.ru.Но" to "But",
        "io.cucumber.java.ru.А" to "But",
        "cucumber.api.java.en.Given" to "Given",
        "cucumber.api.java.en.When" to "When",
        "cucumber.api.java.en.Then" to "Then",
        "cucumber.api.java.en.And" to "And",
        "cucumber.api.java.en.But" to "But",
        "cucumber.api.java.ru.Дано" to "Given",
        "cucumber.api.java.ru.Пусть" to "Given",
        "cucumber.api.java.ru.Допустим" to "Given",
        "cucumber.api.java.ru.Когда" to "When",
        "cucumber.api.java.ru.Если" to "When",
        "cucumber.api.java.ru.Тогда" to "Then",
        "cucumber.api.java.ru.То" to "Then",
        "cucumber.api.java.ru.И" to "And",
        "cucumber.api.java.ru.Но" to "But",
        "cucumber.api.java.ru.А" to "But",
    )

    fun collect(project: Project): BinaryLibraryScanResult {
        val classRoots = resolveClassRoots(project)
        val steps = ReadAction.compute<List<StepDefinitionDto>, RuntimeException> {
            collectFromRoots(project, classRoots).steps
        }
        logger.info(
            "Collected ${steps.size} binary library steps from ${classRoots.size} class roots"
        )
        return BinaryLibraryScanResult(
            classRoots = classRoots.mapNotNull { normalizeRootIdentity(it.url) },
            steps = steps
        )
    }

    internal fun collectFromRoots(
        project: Project,
        classRoots: Iterable<VirtualFile>,
    ): BinaryLibraryScanResult {
        val psiManager = PsiManager.getInstance(project)
        val evaluator = JavaPsiFacade.getInstance(project).constantEvaluationHelper
        val normalizedRoots = linkedMapOf<String, VirtualFile>()
        classRoots.forEach { root ->
            val identity = normalizeRootIdentity(root.url) ?: return@forEach
            normalizedRoots.putIfAbsent(identity, root)
        }

        val steps = mutableListOf<StepDefinitionDto>()
        normalizedRoots.forEach { (rootIdentity, root) ->
            val stepsBefore = steps.size
            VfsUtilCore.iterateChildrenRecursively(root, null, ContentIterator { file ->
                if (!isSupportedClassFile(file)) {
                    return@ContentIterator true
                }
                val psiFile = psiManager.findFile(file) as? PsiClassOwner ?: return@ContentIterator true
                psiFile.classes.forEach { psiClass ->
                    steps += collectStepsFromClass(
                        rootIdentity = rootIdentity,
                        classFile = file,
                        psiClass = psiClass,
                        evaluator = evaluator,
                    )
                }
                true
            })
            val rootStepCount = steps.size - stepsBefore
            if (rootStepCount == 0) {
                logger.info("No Cucumber steps found in binary library root: $rootIdentity")
            } else {
                logger.debug("Collected $rootStepCount steps from binary library root: $rootIdentity")
            }
        }

        return BinaryLibraryScanResult(
            classRoots = normalizedRoots.keys.toList(),
            steps = steps,
        )
    }

    private fun resolveClassRoots(project: Project): List<VirtualFile> {
        val roots = linkedMapOf<String, VirtualFile>()
        OrderEnumerator.orderEntries(project)
            .librariesOnly()
            .withoutSdk()
            .classes()
            .roots
            .forEach { root ->
                val identity = normalizeRootIdentity(root.url) ?: return@forEach
                roots.putIfAbsent(identity, root)
            }
        return roots.values.toList()
    }

    private fun collectStepsFromClass(
        rootIdentity: String,
        classFile: VirtualFile,
        psiClass: PsiClass,
        evaluator: com.intellij.psi.PsiConstantEvaluationHelper,
    ): List<StepDefinitionDto> {
        val className = psiClass.qualifiedName ?: psiClass.name ?: return emptyList()
        val depPrefix = dependencyPrefix(rootIdentity)
        val fileRef = "$depPrefix:${normalizeClassFileRef(classFile.url)}"

        val steps = mutableListOf<StepDefinitionDto>()
        psiClass.methods.forEach { method ->
            var annotationIndex = 0
            method.modifierList.annotations.forEach { annotation ->
                val keyword = keywordForAnnotation(annotation) ?: return@forEach
                val pattern = extractPattern(annotation, evaluator) ?: return@forEach
                val id = stableStepId(
                    depPrefix = depPrefix,
                    rootIdentity = rootIdentity,
                    className = className,
                    method = method,
                    annotationIndex = annotationIndex,
                    pattern = pattern,
                )
                val implementation = StepImplementationDto(
                    file = fileRef,
                    line = null,
                    className = className,
                    methodName = method.name,
                )
                steps += StepDefinitionDto(
                    id = id,
                    keyword = keyword,
                    pattern = pattern,
                    codeRef = "$fileRef#${method.name}",
                    patternType = detectPatternType(pattern),
                    regex = null,
                    parameters = method.parameterList.parameters.mapIndexed { index, parameter ->
                        StepParameterDto(
                            name = parameter.name.takeUnless { it.isBlank() } ?: "arg${index + 1}",
                            type = parameter.type.presentableText,
                            placeholder = null,
                        )
                    },
                    tags = emptyList(),
                    language = null,
                    implementation = implementation,
                    summary = null,
                    docSummary = null,
                    examples = emptyList(),
                )
                annotationIndex += 1
            }
        }
        return steps
    }

    private fun isSupportedClassFile(file: VirtualFile): Boolean {
        if (file.isDirectory) return false
        if (!file.name.endsWith(".class", ignoreCase = true)) return false
        if (file.name == "module-info.class" || file.name == "package-info.class") return false
        return !file.name.contains('$')
    }

    private fun keywordForAnnotation(annotation: PsiAnnotation): String? {
        val qualifiedName = annotation.qualifiedName
        if (!qualifiedName.isNullOrBlank()) {
            return annotationKeywords[qualifiedName]
        }
        return when (annotation.nameReferenceElement?.referenceName) {
            "Given" -> "Given"
            "When" -> "When"
            "Then" -> "Then"
            "And" -> "And"
            "But" -> "But"
            "Дано" -> "Given"
            "Пусть" -> "Given"
            "Допустим" -> "Given"
            "Когда" -> "When"
            "Если" -> "When"
            "Тогда" -> "Then"
            "То" -> "Then"
            "И" -> "And"
            "Но" -> "But"
            "А" -> "But"
            else -> null
        }
    }

    private fun extractPattern(
        annotation: PsiAnnotation,
        evaluator: com.intellij.psi.PsiConstantEvaluationHelper,
    ): String? {
        val attribute = annotation.findAttributeValue("value")
            ?: annotation.findDeclaredAttributeValue("value")
            ?: annotation.parameterList.attributes.firstOrNull()?.value
            ?: return null
        val literal = (attribute as? PsiLiteralExpression)?.value as? String
        if (!literal.isNullOrBlank()) {
            return literal
        }
        val constant = evaluator.computeConstantExpression(attribute)
        return (constant as? String)?.takeIf { it.isNotBlank() }
    }

    private fun detectPatternType(pattern: String): String {
        val trimmed = pattern.trim()
        return if (
            trimmed.startsWith("^") ||
            listOf("\\", "[", "]", "(?", "$").any(pattern::contains)
        ) {
            "regularExpression"
        } else {
            "cucumberExpression"
        }
    }

    private fun stableStepId(
        depPrefix: String,
        rootIdentity: String,
        className: String,
        method: PsiMethod,
        annotationIndex: Int,
        pattern: String,
    ): String {
        val signature = buildString {
            append(rootIdentity)
            append('|')
            append(className)
            append('#')
            append(method.name)
            append('|')
            append(annotationIndex)
            append('|')
            append(pattern)
        }
        return "$depPrefix:${sha1(signature).take(12)}"
    }

    private fun dependencyPrefix(rootIdentity: String): String {
        return "dep[${sha1(rootIdentity).take(10)}]"
    }

    private fun normalizeClassFileRef(url: String): String {
        return VfsUtilCore.urlToPath(url).trim().removeSuffix("!/")
    }

    private fun normalizeRootIdentity(url: String): String? {
        val rawPath = VfsUtilCore.urlToPath(url).trim().removeSuffix("!/")
        if (rawPath.isBlank()) return null
        return try {
            val jarSeparator = "!/"
            val separatorIndex = rawPath.indexOf(jarSeparator)
            if (separatorIndex >= 0) {
                val archivePath = Paths.get(rawPath.substring(0, separatorIndex)).normalize()
                if (!Files.isRegularFile(archivePath)) return null
                return archivePath.toString()
            }

            val path = Paths.get(rawPath).normalize()
            if (!isSupportedRoot(path)) return null
            path.toString()
        } catch (_: Exception) {
            null
        }
    }

    private fun isSupportedRoot(path: Path): Boolean {
        if (Files.isDirectory(path)) return true
        if (!Files.isRegularFile(path)) return false
        return path.fileName.toString().endsWith(".jar", ignoreCase = true)
    }

    private fun sha1(value: String): String {
        val digest = MessageDigest.getInstance("SHA-1").digest(value.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { byte -> "%02x".format(byte) }
    }
}
