package ru.sber.aitestplugin.util

import java.io.InterruptedIOException
import java.util.concurrent.TimeUnit

object ScanStepsTimeoutSupport {
    fun isTimeout(error: Throwable): Boolean {
        return generateSequence(error) { it.cause }.any { current ->
            current is InterruptedIOException ||
                current.message?.contains("timeout", ignoreCase = true) == true
        }
    }

    fun userMessage(timeoutMs: Int): String {
        val seconds = TimeUnit.MILLISECONDS.toSeconds(timeoutMs.toLong()).coerceAtLeast(1)
        return "Сканирование превысило client timeout (${seconds} сек). Backend мог продолжить обработку, повторно обновите индекс через некоторое время."
    }
}
