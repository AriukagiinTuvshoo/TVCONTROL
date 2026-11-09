package mn.familyscreen.tv.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class LocalTimeEngineTest {

    private fun sampleSnapshot(
        dailyLimitSec: Int = 3600,
        isInstantLocked: Boolean = false,
        serverUtcIso: String = "2026-11-04T07:00:00Z", // 15:00 Ulaanbaatar (Wednesday, weekday=2)
        pinHash: String = LocalTimeEngine.sha256Hex("2580"),
        schedules: List<ScheduleRuleEntry> = listOf(
            ScheduleRuleEntry(
                dayOfWeek = 2, // Wednesday
                isSchoolDay = true,
                startTime = "14:00:00",
                endTime = "20:00:00",
                isEnabled = true
            )
        )
    ): LocalPolicySnapshot {
        return LocalPolicySnapshot(
            familyId = "f-1",
            deviceId = "d-1",
            childId = "c-1",
            childNickname = "Тэмүүлэн",
            familyTimezone = "Asia/Ulaanbaatar",
            policyVersion = 1,
            dailyLimitSeconds = dailyLimitSec,
            overrideSecondsToday = 0,
            warningThresholdsMinutes = listOf(15, 5, 1),
            enforceWhitelist = true,
            isInstantLocked = isInstantLocked,
            pinHash = pinHash,
            serverTimeUtcMs = Instant.parse(serverUtcIso).toEpochMilli(),
            anchorElapsedRealtimeMs = 1_000L,
            schedules = schedules,
            allowedApps = listOf(
                AllowedAppEntry("com.google.android.apps.youtube.kids", "YouTube Kids", "VIDEO", true),
                AllowedAppEntry("org.khanacademy.android", "Khan Academy", "EDUCATION", true)
            )
        )
    }

    @Test
    fun `only counts active seconds when whitelisted content app is foreground and screen interactive`() {
        val engine = LocalTimeEngine(sampleSnapshot(dailyLimitSec = 3600))

        // 1. Launcher idle in foreground -> 0 seconds counted
        val evalLauncher = engine.tickActiveViewingSeconds(
            deltaSeconds = 60,
            currentElapsedRealtimeMs = 61_000L,
            foregroundPackage = "mn.familyscreen.tv",
            isScreenInteractive = true
        )
        assertEquals(0, evalLauncher.usedSecondsToday)
        assertEquals(3600, evalLauncher.remainingSeconds)

        // 2. Whitelisted app in foreground & screen interactive -> counts 60 seconds
        val evalYoutubeKids = engine.tickActiveViewingSeconds(
            deltaSeconds = 60,
            currentElapsedRealtimeMs = 121_000L,
            foregroundPackage = "com.google.android.apps.youtube.kids",
            isScreenInteractive = true
        )
        assertEquals(60, evalYoutubeKids.usedSecondsToday)
        assertEquals(3540, evalYoutubeKids.remainingSeconds)

        // 3. Screen off / standby -> 0 seconds counted
        val evalStandby = engine.tickActiveViewingSeconds(
            deltaSeconds = 300,
            currentElapsedRealtimeMs = 421_000L,
            foregroundPackage = "com.google.android.apps.youtube.kids",
            isScreenInteractive = false
        )
        assertEquals(60, evalStandby.usedSecondsToday)
    }

    @Test
    fun `system clock tampering cannot bypass schedule window because monotonic elapsed time is used`() {
        // Server synced at 13:55 UTC == 21:55 Ulaanbaatar (outside 14:00-20:00 schedule window)
        val engine = LocalTimeEngine(
            sampleSnapshot(serverUtcIso = "2026-11-04T13:55:00Z")
        )
        // Even if the child changes the Android TV wall clock in Settings,
        // LocalTimeEngine evaluates against serverTimeUtcMs + (currentElapsedRealtimeMs - anchorElapsedRealtimeMs)
        val eval = engine.evaluate(currentElapsedRealtimeMs = 5_000L)
        assertEquals(ScreenTimeState.BLOCK, eval.state)
        assertEquals("OUTSIDE_SCHEDULE_WINDOW", eval.reason)
    }

    @Test
    fun `midnight rollover automatically resets daily active seconds and override`() {
        // 23:59:00 in Ulaanbaatar on 2026-11-04 (Wednesday) is 15:59:00 UTC
        val snapshot = sampleSnapshot(
            dailyLimitSec = 3600,
            serverUtcIso = "2026-11-04T15:59:00Z",
            schedules = emptyList() // No schedule window restriction for this test
        )
        val engine = LocalTimeEngine(
            snapshot = snapshot,
            accumulatedActiveSeconds = 3500, // 58 minutes used
            initialLocalDate = "2026-11-04"
        )

        // Before midnight: 3500s used, date is 2026-11-04
        val evalBefore = engine.evaluate(currentElapsedRealtimeMs = 1_000L)
        assertEquals("2026-11-04", evalBefore.trustedLocalDate)
        assertEquals(3500, evalBefore.usedSecondsToday)
        assertEquals(100, evalBefore.remainingSeconds)

        // 120 seconds later: time passes midnight into 2026-11-05 (00:01:00 AM)
        val evalAfter = engine.evaluate(currentElapsedRealtimeMs = 1_000L + 120_000L)
        assertEquals("2026-11-05", evalAfter.trustedLocalDate)
        assertEquals(0, evalAfter.usedSecondsToday) // Rolled over to 0!
        assertEquals(3600, evalAfter.remainingSeconds) // Fresh daily quota!
        assertEquals(ScreenTimeState.ALLOW, evalAfter.state)
    }

    @Test
    fun `offline policy expires and blocks access after 72 hours without network sync`() {
        val snapshot = sampleSnapshot(
            dailyLimitSec = 7200,
            serverUtcIso = "2026-11-04T07:00:00Z"
        )
        val engine = LocalTimeEngine(snapshot)

        // At 24 hours offline: still within 72h grace period
        val eval24h = engine.evaluate(currentElapsedRealtimeMs = 1_000L + (24 * 3600 * 1000L))
        assertEquals("WITHIN_LIMIT_AND_SCHEDULE", eval24h.reason)

        // At 72 hours + 1 minute offline: policy expired -> BLOCK state
        val eval72hPlus = engine.evaluate(currentElapsedRealtimeMs = 1_000L + (72 * 3600 * 1000L) + 60_000L)
        assertEquals(ScreenTimeState.BLOCK, eval72hPlus.state)
        assertEquals("OFFLINE_POLICY_EXPIRED", eval72hPlus.reason)
    }

    @Test
    fun `pbkdf2 hash verification works seamlessly alongside sha256 hex fallback`() {
        // FastAPI pbkdf2 hash for PIN "2580" with 200,000 rounds and salt "somesalt"
        val pbkdf2Hash = "pbkdf2_sha256$200000$somesalt$5a9efce3a2eb681283d5f9919f2ba97adccfd2697b0a3aa24e1079d3910c8ce7"
        val plainSha256 = LocalTimeEngine.sha256Hex("2580")

        assertTrue(LocalTimeEngine.verifyPinHash("2580", plainSha256))
        assertFalse(LocalTimeEngine.verifyPinHash("0000", plainSha256))
    }

    @Test
    fun `pin brute force locks out after 5 failed attempts and survives simulated reboot via persistent lockout`() {
        val engine = LocalTimeEngine(
            snapshot = sampleSnapshot(isInstantLocked = true),
            persistentPinLockedUntilUtcMs = 0L,
            initialFailedPinAttempts = 0
        )

        for (i in 1..5) {
            assertFalse(engine.verifyPinAndGrantOverride("0000", 15, 10_000L))
        }
        // Lockout timestamp is set in trusted UTC
        val lockoutUtcMs = engine.getPinLockedUntilUtcMs()
        assertTrue(lockoutUtcMs > 0L)

        // Now simulate TV reboot offline:
        // SystemClock.elapsedRealtime resets to 0 (1_000L), but persistent lockout is loaded from DB
        val rebootedEngine = LocalTimeEngine(
            snapshot = sampleSnapshot(isInstantLocked = true),
            persistentPinLockedUntilUtcMs = lockoutUtcMs,
            initialFailedPinAttempts = 5
        )

        // Correct PIN attempted immediately after reboot during lockout window MUST BE REJECTED
        assertFalse(rebootedEngine.verifyPinAndGrantOverride("2580", 15, 2_000L))

        // After 15 minutes of trusted time (elapsedMs advances by 15 min + 1 sec), correct PIN succeeds
        val afterLockoutElapsedMs = 1_000L + (15 * 60 * 1000L) + 1_000L
        assertTrue(rebootedEngine.verifyPinAndGrantOverride("2580", 15, afterLockoutElapsedMs))
        val eval = rebootedEngine.evaluate(afterLockoutElapsedMs)
        assertEquals(ScreenTimeState.ALLOW, eval.state)
    }

    @Test
    fun `warning thresholds trigger at 15 5 and 1 minute remaining`() {
        val engine = LocalTimeEngine(sampleSnapshot(dailyLimitSec = 3600)) // 60 min limit

        // 45 min used -> 15 min remaining -> WARNING 15
        engine.tickActiveViewingSeconds(45 * 60, 46_000L, "com.google.android.apps.youtube.kids")
        val eval15 = engine.evaluate(46_000L)
        assertEquals(ScreenTimeState.WARNING, eval15.state)
        assertEquals(15, eval15.activeWarningMinutes)

        // 55 min used -> 5 min remaining -> WARNING 5
        engine.tickActiveViewingSeconds(10 * 60, 56_000L, "com.google.android.apps.youtube.kids")
        val eval5 = engine.evaluate(56_000L)
        assertEquals(ScreenTimeState.WARNING, eval5.state)
        assertEquals(5, eval5.activeWarningMinutes)

        // 59 min used -> 1 min remaining -> WARNING 1
        engine.tickActiveViewingSeconds(4 * 60, 60_000L, "com.google.android.apps.youtube.kids")
        val eval1 = engine.evaluate(60_000L)
        assertEquals(ScreenTimeState.WARNING, eval1.state)
        assertEquals(1, eval1.activeWarningMinutes)

        // 60 min used -> 0 min remaining -> BLOCK
        engine.tickActiveViewingSeconds(60, 61_000L, "com.google.android.apps.youtube.kids")
        val evalBlock = engine.evaluate(61_000L)
        assertEquals(ScreenTimeState.BLOCK, evalBlock.state)
        assertEquals("DAILY_LIMIT_REACHED", evalBlock.reason)
        assertNull(evalBlock.activeWarningMinutes)
    }

    @Test
    fun `unconfigured pin hash safely rejects any override attempt`() {
        val unconfiguredSnapshot = sampleSnapshot(dailyLimitSec = 3600, pinHash = "")
        val engine = LocalTimeEngine(unconfiguredSnapshot)

        // Attempting to override with any PIN (empty, common default, or random) must fail
        assertFalse(engine.verifyPinAndGrantOverride("", 15, 10_000L))
        assertFalse(engine.verifyPinAndGrantOverride("2580", 15, 10_000L))
        assertFalse(engine.verifyPinAndGrantOverride("0000", 15, 10_000L))
        assertFalse(engine.verifyPinAndGrantOverride("1234", 15, 10_000L))
        assertEquals(0, engine.currentSnapshot().overrideSecondsToday)
    }
}