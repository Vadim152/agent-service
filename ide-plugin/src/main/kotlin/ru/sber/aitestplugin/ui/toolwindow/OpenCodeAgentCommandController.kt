package ru.sber.aitestplugin.ui.toolwindow

import ru.sber.aitestplugin.model.OpenCodeCommandDto
import ru.sber.aitestplugin.model.OpenCodeCommandExecutionRequestDto
import ru.sber.aitestplugin.model.OpenCodeCommandExecutionResponseDto
import ru.sber.aitestplugin.services.BackendClient

internal class OpenCodeAgentCommandController(
    private val backendClient: BackendClient
) {
    @Volatile
    private var upstreamCommands: List<OpenCodeCommandDto> = emptyList()

    fun refreshCatalog(projectRoot: String): List<OpenCodeCommandDto> {
        if (projectRoot.isBlank()) {
            upstreamCommands = emptyList()
            return currentCatalog()
        }
        upstreamCommands = backendClient.listOpenCodeCommands(projectRoot).items
        return currentCatalog()
    }

    fun currentCatalog(): List<OpenCodeCommandDto> = mergeCommandCatalog(upstreamCommands)

    fun filterSuggestions(token: String): List<OpenCodeCommandDto> =
        filterCommandCatalog(currentCatalog(), token)

    fun executeSlashCommand(
        sessionId: String?,
        projectRoot: String,
        input: String
    ): OpenCodeCommandExecutionResponseDto {
        val parsed = parseSlashInput(input)
            ?: throw IllegalArgumentException("Slash command is required")
        return backendClient.executeOpenCodeCommand(
            parsed.commandId,
            OpenCodeCommandExecutionRequestDto(
                sessionId = sessionId,
                projectRoot = projectRoot.takeIf { it.isNotBlank() },
                arguments = parsed.arguments,
                rawInput = parsed.rawInput
            )
        )
    }

    companion object {
        private val aliasCommands = listOf(
            OpenCodeCommandDto(
                name = "agents",
                description = "Inspect available agents",
                source = "plugin-alias",
                alias = true
            ),
            OpenCodeCommandDto(
                name = "editor",
                description = "Open the editor integration",
                source = "plugin-alias",
                alias = true,
                nativeAction = "open_editor"
            ),
            OpenCodeCommandDto(
                name = "help",
                description = "Show available OpenCode commands",
                source = "plugin-alias",
                alias = true
            ),
            OpenCodeCommandDto(
                name = "init",
                description = "Initialize OpenCode for the project",
                source = "plugin-alias",
                alias = true
            ),
            OpenCodeCommandDto(
                name = "mcps",
                description = "Inspect configured MCP servers",
                source = "plugin-alias",
                alias = true
            ),
            OpenCodeCommandDto(
                name = "models",
                description = "Inspect configured models",
                source = "plugin-alias",
                alias = true
            ),
            OpenCodeCommandDto(
                name = "new",
                description = "Create a new agent dialog",
                source = "plugin-alias",
                alias = true,
                hidden = true,
                nativeAction = "new_session"
            ),
            OpenCodeCommandDto(
                name = "review",
                description = "Run repository review",
                source = "plugin-alias",
                alias = true
            ),
            OpenCodeCommandDto(
                name = "sessions",
                description = "Open agent session history",
                source = "plugin-alias",
                alias = true,
                hidden = true,
                nativeAction = "open_history"
            ),
            OpenCodeCommandDto(
                name = "skills",
                description = "Inspect discovered skills",
                source = "plugin-alias",
                alias = true
            ),
            OpenCodeCommandDto(
                name = "status",
                description = "Show current agent status and diff",
                source = "plugin-alias",
                alias = true
            )
        )

        fun mergeCommandCatalog(upstreamCommands: List<OpenCodeCommandDto>): List<OpenCodeCommandDto> {
            val itemsByName = linkedMapOf<String, OpenCodeCommandDto>()
            upstreamCommands.forEach { itemsByName[it.name.lowercase()] = it }
            aliasCommands.forEach { alias ->
                itemsByName.putIfAbsent(alias.name.lowercase(), alias)
            }
            return itemsByName.values.sortedBy { it.name.lowercase() }
        }

        fun filterCommandCatalog(
            commands: List<OpenCodeCommandDto>,
            token: String
        ): List<OpenCodeCommandDto> {
            val normalizedToken = token.trim().lowercase()
            return commands
                .asSequence()
                .filterNot { it.hidden }
                .filter {
                    normalizedToken.isBlank() ||
                        it.name.lowercase().startsWith(normalizedToken) ||
                        (it.description?.lowercase()?.contains(normalizedToken) == true)
                }
                .toList()
        }

        fun renderSuggestion(command: OpenCodeCommandDto): String {
            val description = command.description?.takeIf { it.isNotBlank() } ?: command.source ?: "OpenCode command"
            return "/${command.name} - $description"
        }

        fun selectionText(command: OpenCodeCommandDto): String {
            val suffix = if (command.nativeAction != null || command.name in setOf("status", "help", "agents", "mcps", "models", "skills")) {
                ""
            } else {
                " "
            }
            return "/${command.name}$suffix"
        }

        fun parseSlashInput(input: String): ParsedSlashCommand? {
            val raw = input.trim()
            if (!raw.startsWith("/")) return null
            val body = raw.removePrefix("/").trim()
            if (body.isBlank()) return null
            val commandId = body.substringBefore(" ").trim().lowercase()
            if (commandId.isBlank()) return null
            val rawInput = body.substringAfter(" ", "").trim().ifBlank { null }
            val arguments = rawInput
                ?.split(Regex("\\s+"))
                ?.map { it.trim() }
                ?.filter { it.isNotBlank() }
                .orEmpty()
            return ParsedSlashCommand(
                commandId = commandId,
                rawInput = rawInput,
                arguments = arguments
            )
        }
    }
}

internal data class ParsedSlashCommand(
    val commandId: String,
    val rawInput: String?,
    val arguments: List<String>
)
