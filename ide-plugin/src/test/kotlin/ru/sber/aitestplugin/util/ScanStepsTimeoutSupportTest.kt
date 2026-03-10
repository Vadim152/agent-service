package ru.sber.aitestplugin.util

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.InterruptedIOException

class ScanStepsTimeoutSupportTest {

    @Test
    fun `detects timeout from exception chain and formats user message`() {
        val error = IllegalStateException("wrapper", InterruptedIOException("timeout"))

        assertTrue(ScanStepsTimeoutSupport.isTimeout(error))
        assertTrue(ScanStepsTimeoutSupport.userMessage(300_000).contains("300 сек"))
    }

    @Test
    fun `ignores non timeout failures`() {
        assertFalse(ScanStepsTimeoutSupport.isTimeout(IllegalStateException("boom")))
    }
}
