package mn.familyscreen.tv.engine

import java.security.MessageDigest
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

/**
 * FamilyScreen Local Time Engine (Android TV & FamilyScreen Box).
 *
 * Anti-Tamper Monotonic Clock Design:
 * - Anchors `serverTimeUtcMs` to `anchorElapsedRealtimeMs` (`SystemClock.elapsedRealtime()`)
 *   at the moment of sync.
 * - Computes `trustedNowUtcMs = serverTimeUtcMs + (currentElapsedRealtimeMs - anchorElapsedRealtimeMs)`.
 * - Even if a child changes the Android TV system date/time in Settings while offline,
 *   `LocalTimeEngine` evaluates schedules and daily quotas against `trustedNowUtcMs`!
 * - Automatic Midnight Rollover: resets daily usage and overrides when local calendar day flips.
 * - Offline Grace Period: Enforces safety BLOCK if offline without sync for > 72 hours.
 * - Persistent Lockout: Protects against reboot brute-force bypass.
 */
enum class ScreenTimeState {
    ALLOW,
    WARNING,
    BLOCK
}

data class AllowedAppEntry(
    val packageName: String,
    val label: String,
    val category: String,
    val isAllowed: Boolean = true
)

data class ScheduleRuleEntry(
    val dayOfWeek: Int, // 0=Monday .. 6=Sunday
    val isSchoolDay: Boolean,
    val startTime: String, // "HH:MM" or "HH:MM:SS"
    val endTime: String,   // "HH:MM" or "HH:MM:SS"
    val isEnabled: Boolean
)

data class LocalPolicySnapshot(
    val familyId: String,
    val deviceId: String,
    val childId: String,
    val childNickname: String,
    val familyTimezone: String = "Asia/Ulaanbaatar",
    val policyVersion: Int,
    val dailyLimitSeconds: Int,
    val weekendBonusSeconds: Int = 0,
    val overrideSecondsToday: Int,
    val warningThresholdsMinutes: List<Int> = listOf(15, 5, 1),
    val enforceWhitelist: Boolean = true,
    val isInstantLocked: Boolean = false,
    val pinHash: String,
    val serverTimeUtcMs: Long = System.currentTimeMillis(),
    val anchorElapsedRealtimeMs: Long = 0L,
    val schedules: List<ScheduleRuleEntry> = emptyList(),
    val allowedApps: List<AllowedAppEntry> = emptyList()
)

data class LocalTimeEvaluation(
    val state: ScreenTimeState,
    val reason: String,
    val trustedLocalDate: String,
    val trustedLocalTime: String,
    val allowedSecondsToday: Int,
    val usedSecondsToday: Int,
    val remainingSeconds: Int,
    val activeWarningMinutes: Int?
)

class LocalTimeEngine(
    private var snapshot: LocalPolicySnapshot,
    private var accumulatedActiveSeconds: Int = 0,
    private var initialLocalDate: String? = null,
    private var persistentPinLockedUntilUtcMs: Long = 0L,
    private var initialFailedPinAttempts: Int = 0
) {
    private var lastEvaluatedLocalDate: String? = initialLocalDate
    private var failedPinAttempts: Int = initialFailedPinAttempts
    private var pinLockedUntilUtcMs: Long = persistentPinLockedUntilUtcMs

    fun currentSnapshot(): LocalPolicySnapshot = snapshot

    fun currentUsedSeconds(): Int = accumulatedActiveSeconds

    fun getLastEvaluatedLocalDate(): String? = lastEvaluatedLocalDate

    fun getPinLockedUntilUtcMs(): Long = pinLockedUntilUtcMs

    fun getFailedPinAttempts(): Int = failedPinAttempts

    fun updateSnapshot(newSnapshot: LocalPolicySnapshot, syncedUsedSeconds: Int) {
        // Only accept equal or newer policy version (or child profile switch)
        if (newSnapshot.childId != snapshot.childId || newSnapshot.policyVersion >= snapshot.policyVersion) {
            this.snapshot = newSnapshot
            this.accumulatedActiveSeconds = maxOf(this.accumulatedActiveSeconds, syncedUsedSeconds)
        }
    }

    /**
     * Record active viewing ticks ONLY when a whitelisted content app is in the foreground
     * and the TV screen is interactive (not paused/standby/Launcher idle).
     */
    fun tickActiveViewingSeconds(
        deltaSeconds: Int,
        currentElapsedRealtimeMs: Long,
        foregroundPackage: String?,
        isScreenInteractive: Boolean = true
    ): LocalTimeEvaluation {
        // First evaluate to handle any midnight rollover before ticking
        evaluate(currentElapsedRealtimeMs)

        val isCountableContentApp = isScreenInteractive &&
            foregroundPackage != null &&
            foregroundPackage != "mn.familyscreen.tv" &&
            isPackageAllowed(foregroundPackage)

        if (isCountableContentApp && deltaSeconds > 0) {
            accumulatedActiveSeconds += deltaSeconds
        }
        return evaluate(currentElapsedRealtimeMs)
    }

    /**
     * Compute trusted UTC timestamp immune to system clock tampering.
     */
    fun computeTrustedUtcMs(currentElapsedRealtimeMs: Long): Long {
        val deltaMs = (currentElapsedRealtimeMs - snapshot.anchorElapsedRealtimeMs).coerceAtLeast(0L)
        return snapshot.serverTimeUtcMs + deltaMs
    }

    fun evaluate(currentElapsedRealtimeMs: Long = 0L): LocalTimeEvaluation {
        val trustedUtcMs = computeTrustedUtcMs(currentElapsedRealtimeMs)
        val zoneId = try {
            ZoneId.of(snapshot.familyTimezone)
        } catch (_: Exception) {
            ZoneId.of("Asia/Ulaanbaatar")
        }
        val localZdt: ZonedDateTime = Instant.ofEpochMilli(trustedUtcMs).atZone(zoneId)
        val weekdayZeroBased = localZdt.dayOfWeek.value - 1 // 0=Monday .. 6=Sunday
        val isWeekend = weekdayZeroBased == 5 || weekdayZeroBased == 6
        val localDateStr = localZdt.toLocalDate().toString()
        val localTimeStr = "%02d:%02d:%02d".format(localZdt.hour, localZdt.minute, localZdt.second)

        // Midnight Rollover Detection:
        // When local calendar date transitions, reset daily active seconds and daily overrides
        if (lastEvaluatedLocalDate != null && lastEvaluatedLocalDate != localDateStr) {
            accumulatedActiveSeconds = 0
            snapshot = snapshot.copy(overrideSecondsToday = 0)
        }
        lastEvaluatedLocalDate = localDateStr

        val baseAllowed = snapshot.dailyLimitSeconds + (if (isWeekend) snapshot.weekendBonusSeconds else 0)
        val totalAllowed = (baseAllowed + snapshot.overrideSecondsToday).coerceAtLeast(0)
        val remainingQuota = (totalAllowed - accumulatedActiveSeconds).coerceAtLeast(0)

        // 1. Check Parent Instant Lock
        if (snapshot.isInstantLocked) {
            return LocalTimeEvaluation(
                state = ScreenTimeState.BLOCK,
                reason = "PARENT_INSTANT_LOCK",
                trustedLocalDate = localDateStr,
                trustedLocalTime = localTimeStr,
                allowedSecondsToday = totalAllowed,
                usedSecondsToday = accumulatedActiveSeconds,
                remainingSeconds = 0,
                activeWarningMinutes = null
            )
        }

        // 2. Check Offline Grace Period (Policy Expiry: 72 hours offline ceiling)
        val offlineDurationMs = (trustedUtcMs - snapshot.serverTimeUtcMs).coerceAtLeast(0L)
        if (offlineDurationMs > MAX_OFFLINE_GRACE_MS) {
            return LocalTimeEvaluation(
                state = ScreenTimeState.BLOCK,
                reason = "OFFLINE_POLICY_EXPIRED",
                trustedLocalDate = localDateStr,
                trustedLocalTime = localTimeStr,
                allowedSecondsToday = totalAllowed,
                usedSecondsToday = accumulatedActiveSeconds,
                remainingSeconds = 0,
                activeWarningMinutes = null
            )
        }

        // 3. Check Schedule Window for current weekday using trusted clock
        val dayRule = snapshot.schedules.firstOrNull { it.dayOfWeek == weekdayZeroBased }
        var scheduleRemainingSec: Int? = null
        var outsideSchedule = false

        if (dayRule != null) {
            if (!dayRule.isEnabled) {
                outsideSchedule = true
                scheduleRemainingSec = 0
            } else {
                val nowSecOfDay = localZdt.hour * 3600 + localZdt.minute * 60 + localZdt.second
                val startSec = parseTimeSeconds(dayRule.startTime, 8 * 3600)
                val endSec = parseTimeSeconds(dayRule.endTime, 21 * 3600)
                if (nowSecOfDay < startSec || nowSecOfDay >= endSec) {
                    outsideSchedule = true
                    scheduleRemainingSec = 0
                } else {
                    scheduleRemainingSec = (endSec - nowSecOfDay).coerceAtLeast(0)
                }
            }
        }

        if (outsideSchedule && snapshot.overrideSecondsToday == 0) {
            return LocalTimeEvaluation(
                state = ScreenTimeState.BLOCK,
                reason = "OUTSIDE_SCHEDULE_WINDOW",
                trustedLocalDate = localDateStr,
                trustedLocalTime = localTimeStr,
                allowedSecondsToday = totalAllowed,
                usedSecondsToday = accumulatedActiveSeconds,
                remainingSeconds = 0,
                activeWarningMinutes = null
            )
        }

        val effectiveRemaining = if (!outsideSchedule && scheduleRemainingSec != null) {
            minOf(remainingQuota, scheduleRemainingSec)
        } else {
            remainingQuota
        }

        // 4. Check Daily Quota Exhausted
        if (effectiveRemaining <= 0) {
            return LocalTimeEvaluation(
                state = ScreenTimeState.BLOCK,
                reason = "DAILY_LIMIT_REACHED",
                trustedLocalDate = localDateStr,
                trustedLocalTime = localTimeStr,
                allowedSecondsToday = totalAllowed,
                usedSecondsToday = accumulatedActiveSeconds,
                remainingSeconds = 0,
                activeWarningMinutes = null
            )
        }

        // 5. Evaluate Warning Thresholds (15, 5, 1 min)
        val sortedThresholds = snapshot.warningThresholdsMinutes.filter { it > 0 }.sortedDescending()
        var triggeredWarning: Int? = null
        for (thresholdMin in sortedThresholds) {
            if (effectiveRemaining <= thresholdMin * 60) {
                triggeredWarning = thresholdMin
            }
        }

        if (triggeredWarning != null) {
            return LocalTimeEvaluation(
                state = ScreenTimeState.WARNING,
                reason = "WARNING_${triggeredWarning}_MIN_REMAINING",
                trustedLocalDate = localDateStr,
                trustedLocalTime = localTimeStr,
                allowedSecondsToday = totalAllowed,
                usedSecondsToday = accumulatedActiveSeconds,
                remainingSeconds = effectiveRemaining,
                activeWarningMinutes = triggeredWarning
            )
        }

        return LocalTimeEvaluation(
            state = ScreenTimeState.ALLOW,
            reason = "WITHIN_LIMIT_AND_SCHEDULE",
            trustedLocalDate = localDateStr,
            trustedLocalTime = localTimeStr,
            allowedSecondsToday = totalAllowed,
            usedSecondsToday = accumulatedActiveSeconds,
            remainingSeconds = effectiveRemaining,
            activeWarningMinutes = null
        )
    }

    fun isPackageAllowed(packageName: String): Boolean {
        if (!snapshot.enforceWhitelist) return true
        if (packageName == "mn.familyscreen.tv") return true
        return snapshot.allowedApps.any { it.packageName == packageName && it.isAllowed }
    }

    /**
     * Offline-capable PIN override supporting both PBKDF2-HMAC-SHA256 (`pbkdf2_sha256$...`)
     * from FastAPI and plain SHA-256 hex, with persistent 5-attempt lockout (FR-07 & NFR-03).
     */
    fun verifyPinAndGrantOverride(
        enteredPin: String,
        addedMinutes: Int,
        currentElapsedRealtimeMs: Long
    ): Boolean {
        if (addedMinutes !in listOf(5, 10, 15, 30, 60)) return false
        val trustedNowUtcMs = computeTrustedUtcMs(currentElapsedRealtimeMs)
        if (trustedNowUtcMs < pinLockedUntilUtcMs) {
            return false
        }

        if (!verifyPinHash(enteredPin, snapshot.pinHash)) {
            failedPinAttempts += 1
            if (failedPinAttempts >= 5) {
                pinLockedUntilUtcMs = trustedNowUtcMs + (15 * 60 * 1000L)
            }
            return false
        }

        failedPinAttempts = 0
        pinLockedUntilUtcMs = 0L
        snapshot = snapshot.copy(
            overrideSecondsToday = snapshot.overrideSecondsToday + (addedMinutes * 60),
            isInstantLocked = false
        )
        return true
    }

    private fun parseTimeSeconds(raw: String, fallbackSec: Int): Int {
        val parts = raw.trim().split(":")
        if (parts.size < 2) return fallbackSec
        val h = parts[0].toIntOrNull() ?: return fallbackSec
        val m = parts[1].toIntOrNull() ?: return fallbackSec
        val s = if (parts.size >= 3) (parts[2].toIntOrNull() ?: 0) else 0
        return h * 3600 + m * 60 + s
    }

    companion object {
        const val MAX_OFFLINE_GRACE_MS = 72 * 3600 * 1000L // 72 hours offline maximum

        fun sha256Hex(input: String): String {
            val digest = MessageDigest.getInstance("SHA-256").digest(input.toByteArray(Charsets.UTF_8))
            return digest.joinToString("") { "%02x".format(it) }
        }

        fun verifyPinHash(plainPin: String, storedHash: String): Boolean {
            if (storedHash.isBlank() || plainPin.isBlank()) return false
            if (storedHash.startsWith("pbkdf2_sha256$")) {
                val parts = storedHash.split("$")
                if (parts.size != 4) return false
                val iterations = parts[1].toIntOrNull() ?: return false
                val saltBytes = parts[2].toByteArray(Charsets.UTF_8)
                val expectedHex = parts[3]
                val spec = PBEKeySpec(plainPin.toCharArray(), saltBytes, iterations, 256)
                val factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
                val derivedHex = factory.generateSecret(spec).encoded.joinToString("") { "%02x".format(it) }
                return MessageDigest.isEqual(
                    derivedHex.toByteArray(Charsets.UTF_8),
                    expectedHex.toByteArray(Charsets.UTF_8)
                )
            }
            val candidateHex = sha256Hex(plainPin)
            return MessageDigest.isEqual(
                candidateHex.toByteArray(Charsets.UTF_8),
                storedHash.toByteArray(Charsets.UTF_8)
            )
        }
    }
}