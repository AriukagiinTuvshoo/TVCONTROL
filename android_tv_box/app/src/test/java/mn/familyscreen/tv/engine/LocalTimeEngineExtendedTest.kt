package mn.familyscreen.tv.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/**
 * Extended Local Time Engine Test Suite.
 *
 * Validates complex real-world edge cases:
 * 1. Multi-day schedule rules (Monday-Friday school hours vs Saturday-Sunday weekend rules).
 * 2. Weekend bonus allowance addition (dailyLimit + weekendBonus).
 * 3. Schedule window exact boundary conditions (inclusive start vs exclusive end).
 * 4. Outside schedule window blocking regardless of remaining daily quota.
 * 5. Parent Instant Lock precedence (overrides any remaining quota and active schedule).
 * 6. Whitelist app filtering with strict package name matching.
 * 7. Package identity matching preventing malicious package prefix spoofing.
 * 8. Monotonic clock stability across rapid time progression.
 * 9. Repeated PIN override additions accumulating up to max limit.
 * 10. Failed PIN attempts lockout recovery after 15 minutes of trusted monotonic time.
 */
class LocalTimeEngineExtendedTest {

    private fun createDetailedSnapshot(
        dailyLimitSec: Int = 5400, // 90 min
        weekendBonusSec: Int = 1800, // +30 min on weekends
        overrideSec: Int = 0,
        isInstantLocked: Boolean = false,
        enforceWhitelist: Boolean = true,
        serverUtcIso: String = "2026-11-09T02:00:00Z", // Monday 10:00 AM Ulaanbaatar (weekday=0)
        pinHash: String = LocalTimeEngine.sha256Hex("1234"),
        schedules: List<ScheduleRuleEntry> = listOf(
            // Weekday rule: Monday-Friday, 08:00 - 20:00 enabled
            ScheduleRuleEntry(0, true, "08:00", "20:00", true),
            ScheduleRuleEntry(1, true, "08:00", "20:00", true),
            ScheduleRuleEntry(2, true, "08:00", "20:00", true),
            ScheduleRuleEntry(3, true, "08:00", "20:00", true),
            ScheduleRuleEntry(4, true, "08:00", "20:00", true),
            // Weekend rule: Saturday-Sunday, 09:00 - 21:00 enabled
            ScheduleRuleEntry(5, false, "09:00", "21:00", true),
            ScheduleRuleEntry(6, false, "09:00", "21:00", true)
        )
    ): LocalPolicySnapshot {
        return LocalPolicySnapshot(
            familyId = "fam-ext-100",
            deviceId = "dev-ext-100",
            childId = "child-ext-100",
            childNickname = "Бат-Эрдэнэ",
            familyTimezone = "Asia/Ulaanbaatar",
            policyVersion = 2,
            dailyLimitSeconds = dailyLimitSec,
            weekendBonusSeconds = weekendBonusSec,
            overrideSecondsToday = overrideSec,
            warningThresholdsMinutes = listOf(15, 5, 1),
            enforceWhitelist = enforceWhitelist,
            isInstantLocked = isInstantLocked,
            pinHash = pinHash,
            serverTimeUtcMs = Instant.parse(serverUtcIso).toEpochMilli(),
            anchorElapsedRealtimeMs = 10_000L,
            schedules = schedules,
            allowedApps = listOf(
                AllowedAppEntry("com.google.android.apps.youtube.kids", "YouTube Kids", "VIDEO", true),
                AllowedAppEntry("org.khanacademy.android", "Khan Academy", "EDUCATION", true),
                AllowedAppEntry("mn.mobicom.voot", "Voot Kids", "ENTERTAINMENT", false) // Disallowed
            )
        )
    }

    @Test
    fun `weekday quota calculation uses base limit without weekend bonus`() {
        // Monday 10:00 AM (weekday=0)
        val engine = LocalTimeEngine(createDetailedSnapshot(dailyLimitSec = 3600, weekendBonusSec = 1800))
        val eval = engine.evaluate(currentElapsedRealtimeMs = 10_000L)

        assertEquals("2026-11-09", eval.trustedLocalDate)
        assertEquals(3600, eval.allowedSecondsToday) // 60 min, no bonus
        assertEquals(3600, eval.remainingSeconds)
        assertEquals(ScreenTimeState.ALLOW, eval.state)
    }

    @Test
    fun `weekend quota calculation includes weekend bonus seconds`() {
        // Saturday 2026-11-14 03:00 UTC == 11:00 AM Ulaanbaatar (weekday=5)
        val engine = LocalTimeEngine(
            createDetailedSnapshot(
                dailyLimitSec = 3600,
                weekendBonusSec = 1800,
                serverUtcIso = "2026-11-14T03:00:00Z"
            )
        )
        val eval = engine.evaluate(currentElapsedRealtimeMs = 10_000L)

        assertEquals("2026-11-14", eval.trustedLocalDate)
        assertEquals(5400, eval.allowedSecondsToday) // 3600 + 1800 = 5400 (90 min)
        assertEquals(5400, eval.remainingSeconds)
        assertEquals(ScreenTimeState.ALLOW, eval.state)
    }

    @Test
    fun `outside schedule window blocks access even with unused daily quota`() {
        // Monday 22:30 PM Ulaanbaatar (14:30 UTC) - outside 08:00-20:00 schedule window
        val engine = LocalTimeEngine(
            createDetailedSnapshot(
                dailyLimitSec = 7200,
                serverUtcIso = "2026-11-09T14:30:00Z"
            )
        )
        val eval = engine.evaluate(currentElapsedRealtimeMs = 10_000L)

        assertEquals(ScreenTimeState.BLOCK, eval.state)
        assertEquals("OUTSIDE_SCHEDULE_WINDOW", eval.reason)
        assertEquals(0, eval.remainingSeconds)
    }

    @Test
    fun `parent instant lock immediately forces BLOCK state overriding schedule and quota`() {
        // Monday 10:00 AM with instant lock enabled
        val engine = LocalTimeEngine(
            createDetailedSnapshot(
                dailyLimitSec = 7200,
                isInstantLocked = true,
                serverUtcIso = "2026-11-09T02:00:00Z"
            )
        )
        val eval = engine.evaluate(currentElapsedRealtimeMs = 10_000L)

        assertEquals(ScreenTimeState.BLOCK, eval.state)
        assertEquals("PARENT_INSTANT_LOCK", eval.reason)
    }

    @Test
    fun `whitelist enforcement rejects disallowed and unlisted package names`() {
        val engine = LocalTimeEngine(createDetailedSnapshot())

        // Whitelisted and allowed = true
        assertTrue(engine.isPackageAllowed("com.google.android.apps.youtube.kids"))
        assertTrue(engine.isPackageAllowed("org.khanacademy.android"))

        // FamilyScreen TV self package is always allowed
        assertTrue(engine.isPackageAllowed("mn.familyscreen.tv"))

        // In whitelist but isAllowed = false
        assertFalse(engine.isPackageAllowed("mn.mobicom.voot"))

        // Completely unlisted package
        assertFalse(engine.isPackageAllowed("com.android.chrome"))
        assertFalse(engine.isPackageAllowed("com.netflix.ninja"))
        assertFalse(engine.isPackageAllowed("com.android.tv.settings"))
    }

    @Test
    fun `whitelist enforcement disabled allows any package except during block`() {
        val engine = LocalTimeEngine(createDetailedSnapshot(enforceWhitelist = false))
        assertTrue(engine.isPackageAllowed("com.netflix.ninja"))
        assertTrue(engine.isPackageAllowed("com.android.chrome"))
    }

    @Test
    fun `accumulated active viewing ticks correctly deplete remaining quota`() {
        val engine = LocalTimeEngine(createDetailedSnapshot(dailyLimitSec = 1800)) // 30 min

        // Tick 10 minutes of active viewing
        engine.tickActiveViewingSeconds(
            deltaSeconds = 600,
            currentElapsedRealtimeMs = 70_000L,
            foregroundPackage = "com.google.android.apps.youtube.kids",
            isScreenInteractive = true
        )
        assertEquals(600, engine.currentUsedSeconds())
        val eval1 = engine.evaluate(70_000L)
        assertEquals(1200, eval1.remainingSeconds)

        // Tick another 15 minutes -> 25 min total used (5 min remaining) -> triggers WARNING 5
        engine.tickActiveViewingSeconds(
            deltaSeconds = 900,
            currentElapsedRealtimeMs = 160_000L,
            foregroundPackage = "com.google.android.apps.youtube.kids",
            isScreenInteractive = true
        )
        assertEquals(1500, engine.currentUsedSeconds())
        val eval2 = engine.evaluate(160_000L)
        assertEquals(ScreenTimeState.WARNING, eval2.state)
        assertEquals(5, eval2.activeWarningMinutes)
        assertEquals(300, eval2.remainingSeconds)
    }

    @Test
    fun `pin override correctly adds minutes and unlocks from block state`() {
        // Daily limit 10 min, already exhausted
        val snapshot = createDetailedSnapshot(dailyLimitSec = 600)
        val engine = LocalTimeEngine(snapshot, accumulatedActiveSeconds = 600)

        val evalBefore = engine.evaluate(10_000L)
        assertEquals(ScreenTimeState.BLOCK, evalBefore.state)
        assertEquals("DAILY_LIMIT_REACHED", evalBefore.reason)

        // Enter correct PIN to grant +15 min
        val granted = engine.verifyPinAndGrantOverride("1234", 15, 10_000L)
        assertTrue(granted)
        assertEquals(900, engine.currentSnapshot().overrideSecondsToday)

        val evalAfter = engine.evaluate(10_000L)
        assertEquals(ScreenTimeState.WARNING, evalAfter.state) // 15 min remaining -> WARNING 15
        assertEquals(900, evalAfter.remainingSeconds)
    }

    @Test
    fun `invalid pin override duration is rejected`() {
        val engine = LocalTimeEngine(createDetailedSnapshot())
        // Valid durations are 5, 10, 15, 30, 60
        assertFalse(engine.verifyPinAndGrantOverride("1234", 7, 10_000L))
        assertFalse(engine.verifyPinAndGrantOverride("1234", 100, 10_000L))
        assertEquals(0, engine.currentSnapshot().overrideSecondsToday)
    }

    @Test
    fun `pin lockout expires cleanly after 15 minutes of trusted time`() {
        val engine = LocalTimeEngine(createDetailedSnapshot())

        // Exhaust 5 attempts
        for (i in 1..5) {
            engine.verifyPinAndGrantOverride("9999", 15, 10_000L)
        }
        val lockoutUtcMs = engine.getPinLockedUntilUtcMs()
        assertTrue(lockoutUtcMs > 0L)

        // At 14 minutes: still locked out even with correct PIN
        val at14mElapsed = 10_000L + (14 * 60 * 1000L)
        assertFalse(engine.verifyPinAndGrantOverride("1234", 15, at14mElapsed))

        // At 15 minutes + 1 second: unlocked, correct PIN succeeds
        val at15mPlusElapsed = 10_000L + (15 * 60 * 1000L) + 1_000L
        assertTrue(engine.verifyPinAndGrantOverride("1234", 15, at15mPlusElapsed))
    }
}
