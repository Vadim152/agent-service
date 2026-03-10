package ru.sber.aitestplugin.services

import com.sun.net.httpserver.HttpServer
import org.junit.Assert.assertEquals
import org.junit.Test
import ru.sber.aitestplugin.config.AiTestPluginSettings
import java.net.InetSocketAddress
import java.time.Instant
import kotlin.test.assertFailsWith

class HttpBackendClientScanTimeoutTest {

    @Test
    fun `scanSteps uses dedicated timeout instead of general request timeout`() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange ->
            Thread.sleep(150)
            val payload = when {
                exchange.requestURI.path.endsWith("/platform/steps/scan-steps") -> {
                    """{"projectRoot":"demo","stepsCount":1,"updatedAt":"${Instant.parse("2026-03-10T10:00:00Z")}","sampleSteps":[],"unmappedSteps":[]}"""
                }

                exchange.requestURI.path.endsWith("/platform/steps/") -> "[]"
                else -> "{}"
            }
            val bytes = payload.toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.use { it.write(bytes) }
        }
        server.start()

        try {
            val settings = AiTestPluginSettings(
                backendUrl = "http://127.0.0.1:${server.address.port}/api/v1",
                requestTimeoutMs = 50,
                scanStepsTimeoutMs = 500
            )
            val client = HttpBackendClient(settingsProvider = { settings })

            val scanResponse = client.scanSteps(projectRoot = "demo")
            assertEquals(1, scanResponse.stepsCount)

            assertFailsWith<BackendException> {
                client.listSteps("demo")
            }
        } finally {
            server.stop(0)
        }
    }
}
