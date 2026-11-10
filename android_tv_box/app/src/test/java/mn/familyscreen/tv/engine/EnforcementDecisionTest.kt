package mn.familyscreen.tv.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class EnforcementDecisionTest {

    private lateinit var stateMachine: UsageEventStateMachine
    private val allowedPackages = setOf(
        "com.google.android.apps.youtube.kids",
        "org.khanacademy.android"
    )

    @Before
    fun setUp() {
        stateMachine = UsageEventStateMachine(
            ownPackageName = "mn.familyscreen.tv"
        )
    }

    @Test
    fun `unauthorized package triggers EnforceBlock with UNAUTHORIZED_APP and non-null blockedPackage`() {
        val detection = ForegroundDetectionState.KnownForeground(
            packageName = "com.android.chrome",
            className = "ChromeActivity",
            timestamp = 10_000L,
            activeActivityCount = 1
        )

        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = detection,
            isPackageAllowed = { allowedPackages.contains(it) },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 15_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L
        )

        assertTrue(decision is EnforcementDecision.EnforceBlock)
        val block = decision as EnforcementDecision.EnforceBlock
        assertEquals("UNAUTHORIZED_APP", block.reason)
        assertEquals("com.android.chrome", block.blockedPackage)
        assertTrue(block.shouldTriggerLaunch)
        assertNull(billingPkg)
    }

    @Test
    fun `system exempt package like com android systemui triggers AllowSystemOrIdle and null billing package`() {
        val detection = ForegroundDetectionState.KnownForeground(
            packageName = "com.android.systemui",
            className = "VolumePanel",
            timestamp = 10_000L,
            activeActivityCount = 1
        )

        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = detection,
            isPackageAllowed = { allowedPackages.contains(it) },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 15_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L
        )

        assertTrue(decision is EnforcementDecision.AllowSystemOrIdle)
        assertNull(billingPkg)
    }

    @Test
    fun `launcher package triggers AllowSystemOrIdle and null billing package`() {
        val detection = ForegroundDetectionState.KnownForeground(
            packageName = "mn.familyscreen.tv",
            className = "FamilyScreenLauncherActivity",
            timestamp = 10_000L,
            activeActivityCount = 1
        )

        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = detection,
            isPackageAllowed = { allowedPackages.contains(it) },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 15_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L
        )

        assertTrue(decision is EnforcementDecision.AllowSystemOrIdle)
        assertNull(billingPkg)
    }

    @Test
    fun `allowed package triggers AllowActiveContent and non-null billing package`() {
        val detection = ForegroundDetectionState.KnownForeground(
            packageName = "com.google.android.apps.youtube.kids",
            className = "MainActivity",
            timestamp = 10_000L,
            activeActivityCount = 1
        )

        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = detection,
            isPackageAllowed = { allowedPackages.contains(it) },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 15_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L
        )

        assertTrue(decision is EnforcementDecision.AllowActiveContent)
        assertEquals("com.google.android.apps.youtube.kids", (decision as EnforcementDecision.AllowActiveContent).packageName)
        assertEquals("com.google.android.apps.youtube.kids", billingPkg)
    }

    @Test
    fun `allowed package when daily quota expired triggers EnforceBlock with quota reason`() {
        val detection = ForegroundDetectionState.KnownForeground(
            packageName = "com.google.android.apps.youtube.kids",
            className = "MainActivity",
            timestamp = 10_000L,
            activeActivityCount = 1
        )

        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = detection,
            isPackageAllowed = { allowedPackages.contains(it) },
            isTimeLimitBlocked = { true },
            timeLimitBlockReason = { "DAILY_LIMIT_REACHED" },
            nowElapsedMs = 15_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L
        )

        assertTrue(decision is EnforcementDecision.EnforceBlock)
        val block = decision as EnforcementDecision.EnforceBlock
        assertEquals("DAILY_LIMIT_REACHED", block.reason)
        assertEquals("com.google.android.apps.youtube.kids", block.blockedPackage)
        assertTrue(block.shouldTriggerLaunch)
        assertNull(billingPkg)
    }

    @Test
    fun `repeated block within 2000ms throttle window sets shouldTriggerLaunch to false to avoid intent loops`() {
        val detection = ForegroundDetectionState.KnownForeground(
            packageName = "com.android.chrome",
            className = "ChromeActivity",
            timestamp = 10_000L,
            activeActivityCount = 1
        )

        // First enforcement at nowElapsed = 10_000L
        val (decision1, _) = stateMachine.evaluateEnforcement(
            detectionState = detection,
            isPackageAllowed = { allowedPackages.contains(it) },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 10_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L
        )
        assertTrue((decision1 as EnforcementDecision.EnforceBlock).shouldTriggerLaunch)

        // Second tick 1000ms later for SAME package -> should be throttled
        val (decision2, _) = stateMachine.evaluateEnforcement(
            detectionState = detection,
            isPackageAllowed = { allowedPackages.contains(it) },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 11_000L,
            lastEnforcedPackage = "com.android.chrome",
            lastEnforcedTimestampMs = 10_000L
        )
        assertFalse((decision2 as EnforcementDecision.EnforceBlock).shouldTriggerLaunch)

        // Third tick after 2500ms -> throttle expired, should trigger launch again if still visible
        val (decision3, _) = stateMachine.evaluateEnforcement(
            detectionState = detection,
            isPackageAllowed = { allowedPackages.contains(it) },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 13_000L,
            lastEnforcedPackage = "com.android.chrome",
            lastEnforcedTimestampMs = 10_000L
        )
        assertTrue((decision3 as EnforcementDecision.EnforceBlock).shouldTriggerLaunch)
    }

    @Test
    fun `different unauthorized app resets throttle and immediately triggers launch`() {
        val detection = ForegroundDetectionState.KnownForeground(
            packageName = "com.zhiliaoapp.musically", // TikTok
            className = "TikTokActivity",
            timestamp = 11_000L,
            activeActivityCount = 1
        )

        // Previously blocked chrome at 10_000L, but now a DIFFERENT package is frontmost
        val (decision, _) = stateMachine.evaluateEnforcement(
            detectionState = detection,
            isPackageAllowed = { allowedPackages.contains(it) },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 11_000L,
            lastEnforcedPackage = "com.android.chrome",
            lastEnforcedTimestampMs = 10_000L
        )
        assertTrue((decision as EnforcementDecision.EnforceBlock).shouldTriggerLaunch)
        assertEquals("com.zhiliaoapp.musically", decision.blockedPackage)
    }

    @Test
    fun `PermissionMissing state triggers RequestPermission decision`() {
        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = ForegroundDetectionState.PermissionMissing,
            isPackageAllowed = { true },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 10_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L
        )

        assertTrue(decision is EnforcementDecision.RequestPermission)
        assertNull(billingPkg)
    }

    @Test
    fun `Unknown detection state triggers fail-safe AllowSystemOrIdle with null billing package`() {
        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = ForegroundDetectionState.Unknown("NO_EVENTS_YET"),
            isPackageAllowed = { true },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 10_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L
        )

        assertTrue(decision is EnforcementDecision.AllowSystemOrIdle)
        assertNull(billingPkg)
    }
}
