package mn.familyscreen.tv.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class UsageEventStateMachineTest {

    private lateinit var stateMachine: UsageEventStateMachine

    @Before
    fun setUp() {
        stateMachine = UsageEventStateMachine(
            ownPackageName = "mn.familyscreen.tv"
        )
    }

    @Test
    fun `empty event history on cold boot results in Unknown NO_EVENTS_YET`() {
        val state = stateMachine.evaluateCurrentState()
        assertTrue(state is ForegroundDetectionState.Unknown)
        assertEquals("NO_EVENTS_YET", (state as ForegroundDetectionState.Unknown).reason)
    }

    @Test
    fun `API 29+ ACTIVITY_RESUMED and ACTIVITY_PAUSED transitions correctly tracked`() {
        // App resumed
        val state1 = stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "com.google.android.apps.youtube.kids",
                    className = "com.google.android.apps.youtube.kids.MainActivity",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                    timestamp = 10_000L
                )
            )
        )
        assertTrue(state1 is ForegroundDetectionState.KnownForeground)
        val fg1 = state1 as ForegroundDetectionState.KnownForeground
        assertEquals("com.google.android.apps.youtube.kids", fg1.packageName)
        assertEquals("com.google.android.apps.youtube.kids.MainActivity", fg1.className)
        assertEquals(1, fg1.activeActivityCount)

        // App paused
        val state2 = stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "com.google.android.apps.youtube.kids",
                    className = "com.google.android.apps.youtube.kids.MainActivity",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_PAUSED,
                    timestamp = 15_000L
                )
            )
        )
        assertTrue(state2 is ForegroundDetectionState.KnownBackground)
        val bg = state2 as ForegroundDetectionState.KnownBackground
        assertNull(bg.lastPackageName)
        assertEquals(15_000L, bg.timestamp)
    }

    @Test
    fun `legacy API 26-28 MOVE_TO_FOREGROUND and MOVE_TO_BACKGROUND events correctly tracked`() {
        val state1 = stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "org.khanacademy.android",
                    className = "org.khanacademy.android.ui.MainActivity",
                    eventType = UsageEventStateMachine.EVENT_MOVE_TO_FOREGROUND, // value 1
                    timestamp = 20_000L
                )
            )
        )
        assertTrue(state1 is ForegroundDetectionState.KnownForeground)
        assertEquals("org.khanacademy.android", (state1 as ForegroundDetectionState.KnownForeground).packageName)

        val state2 = stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "org.khanacademy.android",
                    className = "org.khanacademy.android.ui.MainActivity",
                    eventType = UsageEventStateMachine.EVENT_MOVE_TO_BACKGROUND, // value 2
                    timestamp = 25_000L
                )
            )
        )
        assertTrue(state2 is ForegroundDetectionState.KnownBackground)
    }

    @Test
    fun `multiple activities in one package - pausing one activity does not mark package as background if another remains`() {
        // 1. Launch MainActivity
        stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "com.google.android.apps.youtube.kids",
                    className = "MainActivity",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                    timestamp = 1_000L
                )
            )
        )
        assertEquals(1, stateMachine.getActiveActivityCount("com.google.android.apps.youtube.kids"))

        // 2. Launch VideoPlayerActivity inside same package
        stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "com.google.android.apps.youtube.kids",
                    className = "VideoPlayerActivity",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                    timestamp = 2_000L
                )
            )
        )
        assertEquals(2, stateMachine.getActiveActivityCount("com.google.android.apps.youtube.kids"))

        // 3. MainActivity pauses
        val stateAfterPause = stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "com.google.android.apps.youtube.kids",
                    className = "MainActivity",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_PAUSED,
                    timestamp = 2_100L
                )
            )
        )

        // Must STILL be in foreground because VideoPlayerActivity is still active!
        assertTrue(stateAfterPause is ForegroundDetectionState.KnownForeground)
        val fg = stateAfterPause as ForegroundDetectionState.KnownForeground
        assertEquals("com.google.android.apps.youtube.kids", fg.packageName)
        assertEquals(1, fg.activeActivityCount)

        // 4. VideoPlayerActivity pauses -> now whole package transitions to background
        val stateFinal = stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "com.google.android.apps.youtube.kids",
                    className = "VideoPlayerActivity",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_PAUSED,
                    timestamp = 5_000L
                )
            )
        )
        assertTrue(stateFinal is ForegroundDetectionState.KnownBackground)
        assertEquals(0, stateMachine.getActiveActivityCount("com.google.android.apps.youtube.kids"))
    }

    @Test
    fun `rapid app switching between two packages updates foreground in chronological order`() {
        val events = listOf(
            UsageEventRecord(
                packageName = "com.google.android.apps.youtube.kids",
                className = "MainActivity",
                eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                timestamp = 100L
            ),
            UsageEventRecord(
                packageName = "com.android.chrome",
                className = "ChromeTabbedActivity",
                eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                timestamp = 200L
            ),
            UsageEventRecord(
                packageName = "com.google.android.apps.youtube.kids",
                className = "MainActivity",
                eventType = UsageEventStateMachine.EVENT_ACTIVITY_PAUSED,
                timestamp = 210L
            )
        )
        val state = stateMachine.processEvents(events)
        assertTrue(state is ForegroundDetectionState.KnownForeground)
        assertEquals("com.android.chrome", (state as ForegroundDetectionState.KnownForeground).packageName)
    }

    @Test
    fun `duplicate events from overlapping query window are deduplicated idempotently`() {
        val event = UsageEventRecord(
            packageName = "com.google.android.apps.youtube.kids",
            className = "MainActivity",
            eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
            timestamp = 5_000L
        )

        stateMachine.processEvents(listOf(event))
        assertEquals(1, stateMachine.getActiveActivityCount("com.google.android.apps.youtube.kids"))

        // Duplicate delivery in next query tick
        stateMachine.processEvents(listOf(event))
        assertEquals(1, stateMachine.getActiveActivityCount("com.google.android.apps.youtube.kids"))
    }

    @Test
    fun `timestamp collisions are handled idempotently`() {
        val events = listOf(
            UsageEventRecord(
                packageName = "com.pkg.a",
                className = "ActA",
                eventType = UsageEventStateMachine.EVENT_ACTIVITY_PAUSED,
                timestamp = 10_000L
            ),
            UsageEventRecord(
                packageName = "com.pkg.b",
                className = "ActB",
                eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                timestamp = 10_000L
            )
        )
        val state = stateMachine.processEvents(events)
        assertTrue(state is ForegroundDetectionState.KnownForeground)
        assertEquals("com.pkg.b", (state as ForegroundDetectionState.KnownForeground).packageName)
    }

    @Test
    fun `missing pause event from crashing app - subsequent resumed app correctly takes foreground`() {
        // App A crashes without pause event
        stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "com.crashing.game",
                    className = "GameActivity",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                    timestamp = 1_000L
                )
            )
        )
        assertEquals("com.crashing.game", stateMachine.getCurrentPrimaryPackage())

        // App B (Launcher or YouTube) resumes
        val state = stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "mn.familyscreen.tv",
                    className = "FamilyScreenLauncherActivity",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                    timestamp = 2_000L
                )
            )
        )
        assertTrue(state is ForegroundDetectionState.KnownForeground)
        assertEquals("mn.familyscreen.tv", (state as ForegroundDetectionState.KnownForeground).packageName)
    }

    @Test
    fun `out-of-order event delivery is sorted chronologically`() {
        // Received in reverse order
        val events = listOf(
            UsageEventRecord(
                packageName = "com.pkg.second",
                className = "Act2",
                eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                timestamp = 2_000L
            ),
            UsageEventRecord(
                packageName = "com.pkg.first",
                className = "Act1",
                eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                timestamp = 1_000L
            )
        )
        val state = stateMachine.processEvents(events)
        assertTrue(state is ForegroundDetectionState.KnownForeground)
        assertEquals("com.pkg.second", (state as ForegroundDetectionState.KnownForeground).packageName)
    }

    @Test
    fun `screen non-interactive transitions state to KnownBackground`() {
        stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "com.google.android.apps.youtube.kids",
                    className = "MainActivity",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                    timestamp = 1_000L
                )
            )
        )
        assertTrue(stateMachine.evaluateCurrentState() is ForegroundDetectionState.KnownForeground)

        stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "android",
                    className = null,
                    eventType = UsageEventStateMachine.EVENT_SCREEN_NON_INTERACTIVE,
                    timestamp = 2_000L
                )
            )
        )
        val stateOff = stateMachine.evaluateCurrentState()
        assertTrue(stateOff is ForegroundDetectionState.KnownBackground)
        assertFalse(stateMachine.getScreenInteractive())
    }

    @Test
    fun `system UI and framework packages are identified as system exempt`() {
        assertTrue(stateMachine.isSystemExempt("com.android.systemui"))
        assertTrue(stateMachine.isSystemExempt("com.android.inputmethod.latin"))
        assertTrue(stateMachine.isSystemExempt("com.google.android.inputmethod.latin"))
        assertTrue(stateMachine.isSystemExempt("com.google.android.katniss"))
        assertTrue(stateMachine.isSystemExempt("com.android.permissioncontroller"))
        assertTrue(stateMachine.isSystemExempt("mn.familyscreen.tv"))

        // Third-party apps are NOT exempt
        assertFalse(stateMachine.isSystemExempt("com.android.chrome"))
        assertFalse(stateMachine.isSystemExempt("com.zhiliaoapp.musically")) // TikTok
        assertFalse(stateMachine.isSystemExempt("com.google.android.apps.youtube.kids"))
    }

    @Test
    fun `IME wildcard spoofing is strictly rejected by default system exempt policy`() {
        // Explicitly vetted system IMEs remain exempt
        assertTrue(stateMachine.isSystemExempt("com.android.inputmethod.latin"))
        assertTrue(stateMachine.isSystemExempt("com.google.android.inputmethod.latin"))

        // Malicious or third-party packages spoofing IME names are strictly rejected (F-02 remediation)
        assertFalse(stateMachine.isSystemExempt("com.action.game.ime"))
        assertFalse(stateMachine.isSystemExempt("com.evil.inputmethod.video"))
        assertFalse(stateMachine.isSystemExempt("com.sohu.inputmethod.sogou"))
        assertFalse(stateMachine.isSystemExempt("com.baidu.ime"))
        assertFalse(stateMachine.isSystemExempt("com.inputmethod.hack"))
    }

    @Test
    fun `custom system exempt packages can be provided via constructor for verified OEM keyboards`() {
        val customExempt = UsageEventStateMachine.DEFAULT_SYSTEM_EXEMPT_PACKAGES + setOf("com.sohu.inputmethod.sogou")
        val customMachine = UsageEventStateMachine(systemExemptPackages = customExempt)

        assertTrue(customMachine.isSystemExempt("com.sohu.inputmethod.sogou"))
        assertFalse(customMachine.isSystemExempt("com.evil.inputmethod.video"))
    }

    @Test
    fun `service reset clears active activities and resets timestamp cursor`() {
        stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "com.pkg.a",
                    className = "ActA",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                    timestamp = 10_000L
                )
            )
        )
        assertEquals(1, stateMachine.getActiveActivityCount("com.pkg.a"))

        stateMachine.reset(0L)
        assertEquals(0, stateMachine.getActiveActivityCount("com.pkg.a"))
        assertNull(stateMachine.getCurrentPrimaryPackage())
        assertTrue(stateMachine.evaluateCurrentState() is ForegroundDetectionState.Unknown)
    }

    @Test
    fun `null or blank className falls back to default safely`() {
        val state = stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "com.legacy.app",
                    className = null,
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                    timestamp = 5_000L
                )
            )
        )
        assertTrue(state is ForegroundDetectionState.KnownForeground)
        assertEquals(1, stateMachine.getActiveActivityCount("com.legacy.app"))
    }

    @Test
    fun `ACTIVITY_STOPPED event cleans up activity instance`() {
        stateMachine.processEvents(
            listOf(
                UsageEventRecord(
                    packageName = "com.test.app",
                    className = "SubActivity",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_RESUMED,
                    timestamp = 1_000L
                ),
                UsageEventRecord(
                    packageName = "com.test.app",
                    className = "SubActivity",
                    eventType = UsageEventStateMachine.EVENT_ACTIVITY_STOPPED,
                    timestamp = 2_000L
                )
            )
        )
        assertEquals(0, stateMachine.getActiveActivityCount("com.test.app"))
        assertTrue(stateMachine.evaluateCurrentState() is ForegroundDetectionState.KnownBackground)
    }
}
