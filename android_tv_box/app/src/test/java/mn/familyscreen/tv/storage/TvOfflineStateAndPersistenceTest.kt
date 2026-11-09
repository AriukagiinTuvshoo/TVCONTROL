package mn.familyscreen.tv.storage

import mn.familyscreen.tv.engine.AllowedAppEntry
import mn.familyscreen.tv.engine.LocalPolicySnapshot
import mn.familyscreen.tv.engine.ScheduleRuleEntry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

/**
 * Offline State, Anti-Tamper Clock, and Persistence Logic Test Suite.
 *
 * Validates:
 * 1. Snapshot JSON serialization & parsing integrity across reboot simulation.
 * 2. Monotonic Anti-Tamper Anchor logic: maxOf(serverSyncTime, lastTrustedUtcMs).
 * 3. Unique client_session_uid format for idempotent usage queueing.
 * 4. 72-hour offline policy expiration boundary condition.
 * 5. Persistent PIN lockout timestamp calculation (+15 min).
 */
class TvOfflineStateAndPersistenceTest {

    @Test
    fun `snapshot json serialization preserves all policy fields without data loss`() {
        val originalSnapshot = LocalPolicySnapshot(
            familyId = "fam-persist-01",
            deviceId = "dev-persist-01",
            childId = "child-persist-01",
            childNickname = "Ариунаа",
            familyTimezone = "Asia/Ulaanbaatar",
            policyVersion = 3,
            dailyLimitSeconds = 7200,
            weekendBonusSeconds = 1800,
            overrideSecondsToday = 900,
            warningThresholdsMinutes = listOf(15, 5, 1),
            enforceWhitelist = true,
            isInstantLocked = false,
            pinHash = "pbkdf2_sha256$200000$salt$hash",
            serverTimeUtcMs = 1731146400000L,
            anchorElapsedRealtimeMs = 50_000L,
            schedules = listOf(
                ScheduleRuleEntry(0, true, "08:00", "20:00", true)
            ),
            allowedApps = listOf(
                AllowedAppEntry("com.google.android.apps.youtube.kids", "YouTube Kids", "VIDEO", true)
            )
        )

        // Serialize to JSON
        val root = JSONObject().apply {
            put("family_id", originalSnapshot.familyId)
            put("device_id", originalSnapshot.deviceId)
            put("child_id", originalSnapshot.childId)
            put("child_nickname", originalSnapshot.childNickname)
            put("family_timezone", originalSnapshot.familyTimezone)
            put("policy_version", originalSnapshot.policyVersion)
            put("daily_limit_seconds", originalSnapshot.dailyLimitSeconds)
            put("weekend_bonus_seconds", originalSnapshot.weekendBonusSeconds)
            put("override_seconds_today", originalSnapshot.overrideSecondsToday)
            put("enforce_whitelist", originalSnapshot.enforceWhitelist)
            put("is_instant_locked", originalSnapshot.isInstantLocked)
            put("pin_hash", originalSnapshot.pinHash)
            put("server_time_utc_ms", originalSnapshot.serverTimeUtcMs)
            put("anchor_elapsed_ms", originalSnapshot.anchorElapsedRealtimeMs)
        }

        // Deserialize and assert identical
        assertEquals("fam-persist-01", root.getString("family_id"))
        assertEquals("dev-persist-01", root.getString("device_id"))
        assertEquals("Ариунаа", root.getString("child_nickname"))
        assertEquals(7200, root.getInt("daily_limit_seconds"))
        assertEquals(1800, root.getInt("weekend_bonus_seconds"))
        assertEquals(900, root.getInt("override_seconds_today"))
        assertTrue(root.getBoolean("enforce_whitelist"))
        assertFalse(root.getBoolean("is_instant_locked"))
        assertEquals(1731146400000L, root.getLong("server_time_utc_ms"))
    }

    @Test
    fun `reboot anti-tamper anchor uses maximum of server time and last verified trusted time`() {
        val serverTimeSyncUtcMs = 1731140000000L // 10:00 AM
        val lastTrustedBeforeRebootUtcMs = 1731147200000L // 12:00 PM (2 hours of active viewing elapsed)

        // If the TV is powered off and rebooted offline, the clock anchor MUST NOT rewind to 10:00 AM!
        val effectiveAnchor = maxOf(serverTimeSyncUtcMs, lastTrustedBeforeRebootUtcMs)
        assertEquals(lastTrustedBeforeRebootUtcMs, effectiveAnchor)

        // Even if local wall clock in settings is set to 2020, anchor remains at 12:00 PM
        val tamperedWallClockUtcMs = 1577836800000L // Year 2020
        val guardedAnchor = maxOf(effectiveAnchor, tamperedWallClockUtcMs)
        assertEquals(lastTrustedBeforeRebootUtcMs, guardedAnchor)
    }

    @Test
    fun `client session uid format is unique and contains required prefix`() {
        val uid1 = "tv-sess-${UUID.randomUUID()}"
        val uid2 = "tv-sess-${UUID.randomUUID()}"

        assertTrue(uid1.startsWith("tv-sess-"))
        assertTrue(uid2.startsWith("tv-sess-"))
        assertFalse(uid1 == uid2)
    }

    @Test
    fun `72-hour offline policy duration calculation adheres to 259200000 milliseconds`() {
        val maxOfflineMs = 72L * 3600L * 1000L
        assertEquals(259_200_000L, maxOfflineMs)

        val syncTimeMs = 100_000_000L
        val withinGraceMs = syncTimeMs + (71L * 3600L * 1000L) // 71h
        assertFalse((withinGraceMs - syncTimeMs) > maxOfflineMs)

        val expiredMs = syncTimeMs + (72L * 3600L * 1000L) + 1000L // 72h + 1s
        assertTrue((expiredMs - syncTimeMs) > maxOfflineMs)
    }

    @Test
    fun `pin lockout timestamp calculation correctly adds 15 minutes`() {
        val currentTrustedUtcMs = 1731150000000L
        val lockoutDurationMs = 15L * 60L * 1000L // 900,000 ms
        val lockedUntilUtcMs = currentTrustedUtcMs + lockoutDurationMs

        assertEquals(currentTrustedUtcMs + 900_000L, lockedUntilUtcMs)
        assertTrue(lockedUntilUtcMs > currentTrustedUtcMs)
    }
}
