package mn.familyscreen.tv.network

import mn.familyscreen.tv.engine.AllowedAppEntry
import mn.familyscreen.tv.engine.LocalPolicySnapshot
import mn.familyscreen.tv.engine.ScheduleRuleEntry
import mn.familyscreen.tv.storage.QueuedUsageSession
import mn.familyscreen.tv.storage.TvOfflineDatabase
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant

data class PairingInitResult(
    val deviceId: String,
    val pairingCode: String,
    val qrPayload: String,
    val expiresAtIso: String
)

data class PairingStatusResult(
    val status: String, // PENDING | CLAIMED | EXPIRED
    val deviceId: String,
    val familyId: String?,
    val activeChildId: String?,
    val deviceToken: String?
)

data class SyncResult(
    val snapshot: LocalPolicySnapshot,
    val usedSecondsToday: Int,
    val remainingSecondsToday: Int,
    val serverState: String
)

/**
 * Android TV / FamilyScreen Box Backend REST Client.
 *
 * Uses Android's built-in `HttpURLConnection` + `org.json` so zero external third-party
 * HTTP dependencies are required.
 *
 * Features:
 * - Device Pairing (`init` and `status` polling with one-time `device_token` issuance)
 * - Hardware Authentication via `X-Device-Token` header
 * - Full Policy, Schedule, Allowed Apps, Instant Lock, and Remote Override Sync
 * - Idempotent Usage Session Sync + Offline Queue Drain
 * - Exponential Backoff Retry on transient network/5xx errors
 */
class TvBackendClient(
    private val baseUrl: String = DEFAULT_BASE_URL,
    private val offlineDb: TvOfflineDatabase? = null
) {

    /**
     * 1. Initiate TV Box Pairing (`POST /api/v1/devices/pair/init`).
     */
    fun initDevicePairing(
        hardwareUid: String,
        deviceName: String = "FamilyScreen TV Box",
        deviceType: String = "FAMILYSCREEN_BOX"
    ): PairingInitResult {
        val body = JSONObject().apply {
            put("hardware_uid", hardwareUid)
            put("device_type", deviceType)
            put("device_name", deviceName)
            put("app_version", "1.3.0")
        }
        val responseJson = executeWithRetry("POST", "/api/v1/devices/pair/init", body, deviceToken = null)
        return PairingInitResult(
            deviceId = responseJson.getString("device_id"),
            pairingCode = responseJson.getString("pairing_code"),
            qrPayload = responseJson.getString("qr_payload"),
            expiresAtIso = responseJson.getString("expires_at")
        )
    }

    /**
     * 2. Poll Pairing Status (`GET /api/v1/devices/pair/status/{code}?hardware_uid=...`).
     * Automatically saves `device_token` to [offlineDb] once status == "CLAIMED".
     */
    fun checkPairingStatus(pairingCode: String, hardwareUid: String): PairingStatusResult {
        val path = "/api/v1/devices/pair/status/${pairingCode.trim()}?hardware_uid=$hardwareUid"
        val res = executeWithRetry("GET", path, null, deviceToken = null)
        val status = res.getString("status")
        val deviceId = res.getString("device_id")
        val familyId = if (res.isNull("family_id")) null else res.optString("family_id")
        val childId = if (res.isNull("active_child_id")) null else res.optString("active_child_id")
        val token = if (res.isNull("device_token")) null else res.optString("device_token")

        if (status == "CLAIMED" && !familyId.isNullOrBlank() && !token.isNullOrBlank()) {
            offlineDb?.saveDeviceCredentials(deviceId, familyId, token)
        }

        return PairingStatusResult(
            status = status,
            deviceId = deviceId,
            familyId = familyId,
            activeChildId = childId,
            deviceToken = token
        )
    }

    /**
     * 3. Pull Authoritative Policy, Allowed Apps, Schedules, Remote Overrides & Instant Lock
     * (`GET /api/v1/devices/{device_id}/sync`).
     */
    fun syncDevicePolicy(
        deviceId: String,
        deviceToken: String?,
        currentElapsedRealtimeMs: Long
    ): SyncResult {
        val res = executeWithRetry("GET", "/api/v1/devices/$deviceId/sync", null, deviceToken)
        val timeState = res.getJSONObject("time_state")

        val warnings = mutableListOf<Int>()
        val warnArr = res.optJSONArray("warning_minutes") ?: JSONArray()
        for (i in 0 until warnArr.length()) {
            warnings.add(warnArr.getInt(i))
        }

        val schedules = mutableListOf<ScheduleRuleEntry>()
        val schedArr = res.optJSONArray("schedules") ?: JSONArray()
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

        val allowedApps = mutableListOf<AllowedAppEntry>()
        val appsArr = res.optJSONArray("allowed_apps") ?: JSONArray()
        for (i in 0 until appsArr.length()) {
            val a = appsArr.getJSONObject(i)
            allowedApps.add(
                AllowedAppEntry(
                    packageName = a.getString("package_name"),
                    label = a.getString("app_label"),
                    category = a.optString("category", "EDUCATION"),
                    isAllowed = a.optBoolean("is_allowed", true)
                )
            )
        }

        val serverTimeIso = res.getString("server_time_utc")
        val serverUtcMs = try {
            Instant.parse(serverTimeIso).toEpochMilli()
        } catch (_: Exception) {
            System.currentTimeMillis()
        }

        val snapshot = LocalPolicySnapshot(
            familyId = res.getString("family_id"),
            deviceId = res.getString("device_id"),
            childId = res.getString("active_child_id"),
            childNickname = res.getString("child_nickname"),
            familyTimezone = res.optString("family_timezone", "Asia/Ulaanbaatar"),
            policyVersion = res.getInt("policy_version"),
            dailyLimitSeconds = res.getInt("daily_limit_minutes") * 60,
            weekendBonusSeconds = res.optInt("weekend_bonus_minutes", 0) * 60,
            overrideSecondsToday = timeState.optInt("override_seconds_today", 0),
            warningThresholdsMinutes = if (warnings.isEmpty()) listOf(15, 5, 1) else warnings,
            enforceWhitelist = res.optBoolean("enforce_whitelist", true),
            isInstantLocked = res.optBoolean("is_instant_locked", false),
            pinHash = res.optString("pin_hash", ""),
            serverTimeUtcMs = serverUtcMs,
            anchorElapsedRealtimeMs = currentElapsedRealtimeMs,
            schedules = schedules,
            allowedApps = allowedApps
        )

        val usedSecondsToday = timeState.getInt("used_seconds_today")
        val remainingSecondsToday = timeState.getInt("remaining_seconds_today")
        offlineDb?.savePolicySnapshot(snapshot, usedSecondsToday)

        return SyncResult(
            snapshot = snapshot,
            usedSecondsToday = usedSecondsToday,
            remainingSecondsToday = remainingSecondsToday,
            serverState = timeState.getString("state")
        )
    }

    /**
     * 4. Submit Usage Session (`POST /api/v1/usage/sessions`).
     * If network fails, queues the session into [offlineDb] with `client_session_uid` for later idempotent sync.
     */
    fun submitOrQueueUsageSession(
        session: QueuedUsageSession,
        deviceToken: String?
    ): Boolean {
        val payload = JSONObject().apply {
            put("client_session_uid", session.clientSessionUid)
            put("family_id", session.familyId)
            put("child_id", session.childId)
            put("device_id", session.deviceId)
            put("package_name", session.packageName)
            put("started_at", session.startedAtIso)
            put("ended_at", session.endedAtIso)
            put("active_seconds", session.activeSeconds)
            put("synced_from_offline", session.syncedFromOffline)
        }
        return try {
            executeWithRetry("POST", "/api/v1/usage/sessions", payload, deviceToken)
            offlineDb?.removeSyncedSession(session.clientSessionUid)
            true
        } catch (_: Exception) {
            offlineDb?.enqueueUsageSession(session)
            false
        }
    }

    /**
     * 5. Drain Offline Usage Queue (`Offline -> Online` synchronization).
     */
    fun flushOfflineUsageQueue(deviceToken: String?): Int {
        val db = offlineDb ?: return 0
        val pending = db.getPendingUsageSessions()
        var syncedCount = 0
        for (item in pending) {
            if (submitOrQueueUsageSession(item, deviceToken)) {
                syncedCount += 1
            } else {
                break // Stop draining if network is still unreachable
            }
        }
        return syncedCount
    }

    /**
     * 6. Submit TV PIN Override (`POST /api/v1/overrides` with `source="TV_PIN"`).
     */
    fun submitTvPinOverride(
        familyId: String,
        childId: String,
        deviceId: String,
        pinCode: String,
        addedMinutes: Int,
        deviceToken: String?
    ): Boolean {
        val payload = JSONObject().apply {
            put("family_id", familyId)
            put("child_id", childId)
            put("device_id", deviceId)
            put("source", "TV_PIN")
            put("pin_code", pinCode)
            put("added_minutes", addedMinutes)
            put("reason", "ТВ дээр эцэг эхийн PIN кодоор сунгав")
        }
        return try {
            executeWithRetry("POST", "/api/v1/overrides", payload, deviceToken)
            true
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Execute HTTP request with Exponential Backoff (3 attempts: 300ms, 600ms, 1200ms).
     */
    private fun executeWithRetry(
        method: String,
        path: String,
        body: JSONObject?,
        deviceToken: String?,
        maxAttempts: Int = 3
    ): JSONObject {
        var lastException: Exception? = null
        var backoffMs = 300L

        for (attempt in 1..maxAttempts) {
            var conn: HttpURLConnection? = null
            try {
                val url = URL(baseUrl.trimEnd('/') + path)
                conn = (url.openConnection() as HttpURLConnection).apply {
                    requestMethod = method
                    connectTimeout = 5000
                    readTimeout = 5000
                    setRequestProperty("Accept", "application/json")
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    if (!deviceToken.isNullOrBlank()) {
                        setRequestProperty("X-Device-Token", deviceToken)
                    }
                    if (body != null) {
                        doOutput = true
                        OutputStreamWriter(outputStream, Charsets.UTF_8).use { writer ->
                            writer.write(body.toString())
                        }
                    }
                }

                val code = conn.responseCode
                val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                val responseText = stream?.let {
                    BufferedReader(InputStreamReader(it, Charsets.UTF_8)).use { r -> r.readText() }
                } ?: "{}"

                if (code in 200..299) {
                    return if (responseText.isBlank()) JSONObject() else JSONObject(responseText)
                }

                // Do not retry 4xx client/auth errors
                if (code in 400..499) {
                    throw IllegalStateException("HTTP $code: $responseText")
                }

                throw RuntimeException("Transient HTTP $code: $responseText")
            } catch (e: IllegalStateException) {
                throw e
            } catch (e: Exception) {
                lastException = e
                if (attempt < maxAttempts) {
                    try {
                        Thread.sleep(backoffMs)
                    } catch (_: InterruptedException) {
                        Thread.currentThread().interrupt()
                        throw e
                    }
                    backoffMs *= 2
                }
            } finally {
                conn?.disconnect()
            }
        }
        throw lastException ?: RuntimeException("Network request failed after $maxAttempts attempts")
    }

    companion object {
        // 10.0.2.2 points to host machine's 127.0.0.1 in Android Emulator
        const val DEFAULT_BASE_URL = "http://10.0.2.2:8000"
    }
}
