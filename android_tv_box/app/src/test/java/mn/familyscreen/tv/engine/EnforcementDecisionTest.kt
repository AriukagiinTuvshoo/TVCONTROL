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
    fun `Unknown state within grace period returns AllowSystemOrIdle with zero billing`() {
        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = ForegroundDetectionState.Unknown("NO_EVENTS_YET"),
            isPackageAllowed = { true },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 12_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L,
            unknownSinceElapsedMs = 10_000L,
            unknownGracePeriodMs = 5000L
        )

        assertTrue(decision is EnforcementDecision.AllowSystemOrIdle)
        assertNull(billingPkg)
    }

    @Test
    fun `Unknown state exceeding grace period triggers EnforceHoldingScreen with shouldTriggerLaunch true`() {
        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = ForegroundDetectionState.Unknown("NO_EVENTS_YET"),
            isPackageAllowed = { true },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 16_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L,
            unknownSinceElapsedMs = 10_000L,
            lastHoldingLaunchedMs = 0L,
            unknownGracePeriodMs = 5000L,
            holdingThrottleWindowMs = 5000L
        )

        assertTrue(decision is EnforcementDecision.EnforceHoldingScreen)
        val holding = decision as EnforcementDecision.EnforceHoldingScreen
        assertEquals("HOLDING_UNKNOWN_STATE", holding.reason)
        assertTrue(holding.shouldTriggerLaunch)
        assertNull(billingPkg)
    }

    @Test
    fun `Unknown state holding screen is throttled if repeated within holding throttle window`() {
        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = ForegroundDetectionState.Unknown("NO_EVENTS_YET"),
            isPackageAllowed = { true },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 17_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L,
            unknownSinceElapsedMs = 10_000L,
            lastHoldingLaunchedMs = 15_000L, // Launched 2000ms ago, window is 5000ms
            unknownGracePeriodMs = 5000L,
            holdingThrottleWindowMs = 5000L
        )

        assertTrue(decision is EnforcementDecision.EnforceHoldingScreen)
        val holding = decision as EnforcementDecision.EnforceHoldingScreen
        assertEquals("HOLDING_UNKNOWN_STATE", holding.reason)
        assertFalse(holding.shouldTriggerLaunch) // Throttled!
        assertNull(billingPkg)
    }

    @Test
    fun `holding screen launch is NOT suppressed by unauthorized-app throttle`() {
        // An unauthorized app was enforced 500ms ago (within 2000ms unauthorized throttle)
        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = ForegroundDetectionState.Unknown("NO_EVENTS_YET"),
            isPackageAllowed = { true },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 16_000L,
            lastEnforcedPackage = "com.unauthorized.game",
            lastEnforcedTimestampMs = 15_500L, // 500ms ago
            throttleWindowMs = 2000L,
            unknownSinceElapsedMs = 10_000L,
            lastHoldingLaunchedMs = 0L, // Never launched holding
            unknownGracePeriodMs = 5000L,
            holdingThrottleWindowMs = 5000L
        )

        assertTrue(decision is EnforcementDecision.EnforceHoldingScreen)
        val holding = decision as EnforcementDecision.EnforceHoldingScreen
        assertTrue("Holding screen must launch independently of app throttle", holding.shouldTriggerLaunch)
        assertNull(billingPkg)
    }

    @Test
    fun `recovery from Unknown to known allowed package restores active content and billing`() {
        val knownAllowed = ForegroundDetectionState.KnownForeground(
            packageName = "com.google.android.apps.youtube.kids",
            className = "MainActivity",
            timestamp = 16_000L,
            activeActivityCount = 1
        )

        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = knownAllowed,
            isPackageAllowed = { allowedPackages.contains(it) },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 16_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L
        )

        assertTrue(decision is EnforcementDecision.AllowActiveContent)
        assertEquals("com.google.android.apps.youtube.kids", billingPkg)
    }

    @Test
    fun `recovery from Unknown to known unauthorized package triggers immediate block`() {
        val knownUnauthorized = ForegroundDetectionState.KnownForeground(
            packageName = "com.zhiliaoapp.musically",
            className = "MainActivity",
            timestamp = 16_000L,
            activeActivityCount = 1
        )

        val (decision, billingPkg) = stateMachine.evaluateEnforcement(
            detectionState = knownUnauthorized,
            isPackageAllowed = { allowedPackages.contains(it) },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 16_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L
        )

        assertTrue(decision is EnforcementDecision.EnforceBlock)
        val block = decision as EnforcementDecision.EnforceBlock
        assertEquals("UNAUTHORIZED_APP", block.reason)
        assertEquals("com.zhiliaoapp.musically", block.blockedPackage)
        assertTrue(block.shouldTriggerLaunch)
        assertNull(billingPkg)
    }

    @Test
    fun `monotonic elapsed calculation accurately triggers holding after clock advance across reset`() {
        stateMachine.reset(0L)

        // T0: Unknown starts at elapsed 50_000L
        val (decisionT0, _) = stateMachine.evaluateEnforcement(
            detectionState = ForegroundDetectionState.Unknown("NO_EVENTS_YET"),
            isPackageAllowed = { true },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 50_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L,
            unknownSinceElapsedMs = 50_000L,
            unknownGracePeriodMs = 5000L
        )
        assertTrue(decisionT0 is EnforcementDecision.AllowSystemOrIdle)

        // T1: 4999ms later -> still within grace period
        val (decisionT1, _) = stateMachine.evaluateEnforcement(
            detectionState = ForegroundDetectionState.Unknown("NO_EVENTS_YET"),
            isPackageAllowed = { true },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 54_999L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L,
            unknownSinceElapsedMs = 50_000L,
            unknownGracePeriodMs = 5000L
        )
        assertTrue(decisionT1 is EnforcementDecision.AllowSystemOrIdle)

        // T2: 5000ms later -> grace period expired
        val (decisionT2, _) = stateMachine.evaluateEnforcement(
            detectionState = ForegroundDetectionState.Unknown("NO_EVENTS_YET"),
            isPackageAllowed = { true },
            isTimeLimitBlocked = { false },
            timeLimitBlockReason = { "NONE" },
            nowElapsedMs = 55_000L,
            lastEnforcedPackage = null,
            lastEnforcedTimestampMs = 0L,
            unknownSinceElapsedMs = 50_000L,
            lastHoldingLaunchedMs = 0L,
            unknownGracePeriodMs = 5000L
        )
        assertTrue(decisionT2 is EnforcementDecision.EnforceHoldingScreen)
        assertTrue((decisionT2 as EnforcementDecision.EnforceHoldingScreen).shouldTriggerLaunch)
    }
}
