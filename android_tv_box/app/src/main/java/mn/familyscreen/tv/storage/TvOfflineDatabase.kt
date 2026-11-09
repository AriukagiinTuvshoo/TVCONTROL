package mn.familyscreen.tv.storage

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import mn.familyscreen.tv.engine.AllowedAppEntry
import mn.familyscreen.tv.engine.LocalPolicySnapshot
import mn.familyscreen.tv.engine.ScheduleRuleEntry
import org.json.JSONArray
import org.json.JSONObject

data class QueuedUsageSession(
    val clientSessionUid: String,
    val familyId: String,
    val childId: String,
    val deviceId: String,
    val packageName: String,
    val startedAtIso: String,
    val endedAtIso: String,
    val activeSeconds: Int,
    val syncedFromOffline: Boolean
)

data class RestoredPolicyState(
    val snapshot: LocalPolicySnapshot,
    val usedSecondsToday: Int,
    val lastEvaluatedLocalDate: String?,
    val pinLockedUntilUtcMs: Long,
    val failedPinAttempts: Int
)

/**
 * SQLite + SharedPreferences Offline Persistence Store for FamilyScreen Box.
 *
 * Guarantees:
 * - Last valid [LocalPolicySnapshot] and accumulated daily usage survive network outages and TV reboots.
 * - Monotonic Trusted Time does not rewind across offline TV reboots (anchors to maxOf(syncUtc, lastTrustedUtc)).
 * - Offline usage sessions are queued with unique `client_session_uid` (idempotency key)
 *   and removed only after HTTP 200 acknowledgement from FastAPI.
 * - PIN lockout persists across reboots to prevent brute-force attacks by power cycling.
 * - Device hardware token (`X-Device-Token`) is stored in private mode (`Context.MODE_PRIVATE`).
 */
class TvOfflineDatabase(context: Context) :
    SQLiteOpenHelper(context, DB_NAME, null, DB_VERSION) {

    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS offline_usage_queue (
                client_session_uid TEXT PRIMARY KEY,
                family_id TEXT NOT NULL,
                child_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                package_name TEXT NOT NULL,
                started_at_iso TEXT NOT NULL,
                ended_at_iso TEXT NOT NULL,
                active_seconds INTEGER NOT NULL,
                created_at_ms INTEGER NOT NULL
            )
            """.trimIndent()
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        db.execSQL("DROP TABLE IF EXISTS offline_usage_queue")
        onCreate(db)
    }

    // -----------------------------------------------------------------------
    // Device Credentials & Token Storage
    // -----------------------------------------------------------------------

    fun saveDeviceCredentials(deviceId: String, familyId: String, deviceToken: String) {
        prefs.edit()
            .putString(KEY_DEVICE_ID, deviceId)
            .putString(KEY_FAMILY_ID, familyId)
            .putString(KEY_DEVICE_TOKEN, deviceToken)
            .apply()
    }

    fun getDeviceId(): String? = prefs.getString(KEY_DEVICE_ID, null)

    fun getFamilyId(): String? = prefs.getString(KEY_FAMILY_ID, null)

    fun getDeviceToken(): String? = prefs.getString(KEY_DEVICE_TOKEN, null)

    fun isDevicePaired(): Boolean = !getDeviceId().isNullOrBlank() && !getDeviceToken().isNullOrBlank()

    // -----------------------------------------------------------------------
    // Policy Snapshot & Used Quota Persistence (Reboot Restoration)
    // -----------------------------------------------------------------------

    fun savePolicySnapshot(
        snapshot: LocalPolicySnapshot,
        usedSecondsToday: Int,
        lastTrustedUtcMs: Long = System.currentTimeMillis(),
        lastLocalDate: String? = null,
        pinLockedUntilUtcMs: Long = 0L,
        failedPinAttempts: Int = 0
    ) {
        val root = JSONObject().apply {
            put("family_id", snapshot.familyId)
            put("device_id", snapshot.deviceId)
            put("child_id", snapshot.childId)
            put("child_nickname", snapshot.childNickname)
            put("family_timezone", snapshot.familyTimezone)
            put("policy_version", snapshot.policyVersion)
            put("daily_limit_seconds", snapshot.dailyLimitSeconds)
            put("weekend_bonus_seconds", snapshot.weekendBonusSeconds)
            put("override_seconds_today", snapshot.overrideSecondsToday)
            put("enforce_whitelist", snapshot.enforceWhitelist)
            put("is_instant_locked", snapshot.isInstantLocked)
            put("pin_hash", snapshot.pinHash)
            put("server_time_utc_ms", snapshot.serverTimeUtcMs)
            put("anchor_elapsed_ms", snapshot.anchorElapsedRealtimeMs)
            put("used_seconds_today", usedSecondsToday)

            val warnArr = JSONArray()
            snapshot.warningThresholdsMinutes.forEach { warnArr.put(it) }
            put("warning_minutes", warnArr)

            val schedArr = JSONArray()
            snapshot.schedules.forEach { s ->
                schedArr.put(
                    JSONObject().apply {
                        put("day_of_week", s.dayOfWeek)
                        put("is_school_day", s.isSchoolDay)
                        put("start_time", s.startTime)
                        put("end_time", s.endTime)
                        put("is_enabled", s.isEnabled)
                    }
                )
            }
            put("schedules", schedArr)

            val appsArr = JSONArray()
            snapshot.allowedApps.forEach { a ->
                appsArr.put(
                    JSONObject().apply {
                        put("package_name", a.packageName)
                        put("app_label", a.label)
                        put("category", a.category)
                        put("is_allowed", a.isAllowed)
                    }
                )
            }
            put("allowed_apps", appsArr)
        }

        prefs.edit()
            .putString(KEY_POLICY_SNAPSHOT_JSON, root.toString())
            .putInt(KEY_USED_SECONDS_TODAY, usedSecondsToday)
            .putLong(KEY_LAST_TRUSTED_UTC_MS, lastTrustedUtcMs)
            .putString(KEY_LAST_LOCAL_DATE, lastLocalDate)
            .putLong(KEY_PIN_LOCKED_UNTIL_UTC_MS, pinLockedUntilUtcMs)
            .putInt(KEY_FAILED_PIN_ATTEMPTS, failedPinAttempts)
            .apply()
    }

    fun loadPolicySnapshot(currentElapsedRealtimeMs: Long): RestoredPolicyState? {
        val raw = prefs.getString(KEY_POLICY_SNAPSHOT_JSON, null) ?: return null
        return try {
            val obj = JSONObject(raw)
            val warnings = mutableListOf<Int>()
            val warnArr = obj.optJSONArray("warning_minutes") ?: JSONArray()
            for (i in 0 until warnArr.length()) {
                warnings.add(warnArr.getInt(i))
            }

            val schedules = mutableListOf<ScheduleRuleEntry>()
            val schedArr = obj.optJSONArray("schedules") ?: JSONArray()
            for (i in 0 until schedArr.length()) {
                val s = schedArr.getJSONObject(i)
                schedules.add(
                    ScheduleRuleEntry(
                        dayOfWeek = s.getInt("day_of_week"),
                        isSchoolDay = s.optBoolean("is_school_day", true),
                        startTime = s.optString("start_time", "08:00"),
                        endTime = s.optString("end_time", "21:00"),
                        isEnabled = s.optBoolean("is_enabled", true)
                    )
                )
            }

            val apps = mutableListOf<AllowedAppEntry>()
            val appsArr = obj.optJSONArray("allowed_apps") ?: JSONArray()
            for (i in 0 until appsArr.length()) {
                val a = appsArr.getJSONObject(i)
                apps.add(
                    AllowedAppEntry(
                        packageName = a.getString("package_name"),
                        label = a.getString("app_label"),
                        category = a.optString("category", "EDUCATION"),
                        isAllowed = a.optBoolean("is_allowed", true)
                    )
                )
            }

            // Anti-tamper reboot recovery:
            // Anchor to the maximum of recorded server sync time and the last verified trusted time.
            // This prevents clock rewinding when restarting the TV offline.
            val storedServerTimeUtcMs = obj.optLong("server_time_utc_ms", System.currentTimeMillis())
            val lastTrustedUtcMs = prefs.getLong(KEY_LAST_TRUSTED_UTC_MS, storedServerTimeUtcMs)
            val effectiveAnchorUtcMs = maxOf(storedServerTimeUtcMs, lastTrustedUtcMs)

            val snapshot = LocalPolicySnapshot(
                familyId = obj.getString("family_id"),
                deviceId = obj.getString("device_id"),
                childId = obj.getString("child_id"),
                childNickname = obj.getString("child_nickname"),
                familyTimezone = obj.optString("family_timezone", "Asia/Ulaanbaatar"),
                policyVersion = obj.optInt("policy_version", 1),
                dailyLimitSeconds = obj.getInt("daily_limit_seconds"),
                weekendBonusSeconds = obj.optInt("weekend_bonus_seconds", 0),
                overrideSecondsToday = obj.optInt("override_seconds_today", 0),
                warningThresholdsMinutes = if (warnings.isEmpty()) listOf(15, 5, 1) else warnings,
                enforceWhitelist = obj.optBoolean("enforce_whitelist", true),
                isInstantLocked = obj.optBoolean("is_instant_locked", false),
                pinHash = obj.optString("pin_hash", ""),
                serverTimeUtcMs = effectiveAnchorUtcMs,
                anchorElapsedRealtimeMs = currentElapsedRealtimeMs,
                schedules = schedules,
                allowedApps = apps
            )
            val usedSec = prefs.getInt(KEY_USED_SECONDS_TODAY, obj.optInt("used_seconds_today", 0))
            val lastDate = prefs.getString(KEY_LAST_LOCAL_DATE, null)
            val pinLockedUntil = prefs.getLong(KEY_PIN_LOCKED_UNTIL_UTC_MS, 0L)
            val failedAttempts = prefs.getInt(KEY_FAILED_PIN_ATTEMPTS, 0)

            RestoredPolicyState(
                snapshot = snapshot,
                usedSecondsToday = usedSec,
                lastEvaluatedLocalDate = lastDate,
                pinLockedUntilUtcMs = pinLockedUntil,
                failedPinAttempts = failedAttempts
            )
        } catch (_: Exception) {
            null
        }
    }

    // -----------------------------------------------------------------------
    // Idempotent Offline Usage Queue (SQLite)
    // -----------------------------------------------------------------------

    fun enqueueUsageSession(session: QueuedUsageSession) {
        val db = writableDatabase
        val values = ContentValues().apply {
            put("client_session_uid", session.clientSessionUid)
            put("family_id", session.familyId)
            put("child_id", session.childId)
            put("device_id", session.deviceId)
            put("package_name", session.packageName)
            put("started_at_iso", session.startedAtIso)
            put("ended_at_iso", session.endedAtIso)
            put("active_seconds", session.activeSeconds)
            put("created_at_ms", System.currentTimeMillis())
        }
        // CONFLICT_IGNORE ensures the same client_session_uid is never duplicated in SQLite
        db.insertWithOnConflict("offline_usage_queue", null, values, SQLiteDatabase.CONFLICT_IGNORE)
    }

    fun getPendingUsageSessions(limit: Int = 50): List<QueuedUsageSession> {
        val db = readableDatabase
        val result = mutableListOf<QueuedUsageSession>()
        val cursor = db.query(
            "offline_usage_queue",
            null,
            null,
            null,
            null,
            null,
            "created_at_ms ASC",
            limit.toString()
        )
        cursor.use { c ->
            while (c.moveToNext()) {
                result.add(
                    QueuedUsageSession(
                        clientSessionUid = c.getString(c.getColumnIndexOrThrow("client_session_uid")),
                        familyId = c.getString(c.getColumnIndexOrThrow("family_id")),
                        childId = c.getString(c.getColumnIndexOrThrow("child_id")),
                        deviceId = c.getString(c.getColumnIndexOrThrow("device_id")),
                        packageName = c.getString(c.getColumnIndexOrThrow("package_name")),
                        startedAtIso = c.getString(c.getColumnIndexOrThrow("started_at_iso")),
                        endedAtIso = c.getString(c.getColumnIndexOrThrow("ended_at_iso")),
                        activeSeconds = c.getInt(c.getColumnIndexOrThrow("active_seconds")),
                        syncedFromOffline = true
                    )
                )
            }
        }
        return result
    }

    fun removeSyncedSession(clientSessionUid: String) {
        writableDatabase.delete(
            "offline_usage_queue",
            "client_session_uid = ?",
            arrayOf(clientSessionUid)
        )
    }

    companion object {
        private const val DB_NAME = "familyscreen_tv_offline.db"
        private const val DB_VERSION = 1
        private const val PREFS_NAME = "familyscreen_tv_secure_prefs"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_FAMILY_ID = "family_id"
        private const val KEY_DEVICE_TOKEN = "device_token"
        private const val KEY_POLICY_SNAPSHOT_JSON = "policy_snapshot_json"
        private const val KEY_USED_SECONDS_TODAY = "used_seconds_today"
        private const val KEY_LAST_TRUSTED_UTC_MS = "last_trusted_utc_ms"
        private const val KEY_LAST_LOCAL_DATE = "last_local_date"
        private const val KEY_PIN_LOCKED_UNTIL_UTC_MS = "pin_locked_until_utc_ms"
        private const val KEY_FAILED_PIN_ATTEMPTS = "failed_pin_attempts"
    }
}