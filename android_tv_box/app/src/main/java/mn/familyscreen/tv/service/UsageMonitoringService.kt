package mn.familyscreen.tv.service

import android.app.AppOpsManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import mn.familyscreen.tv.engine.AllowedAppEntry
import mn.familyscreen.tv.engine.EnforcementDecision
import mn.familyscreen.tv.engine.ForegroundDetectionState
import mn.familyscreen.tv.engine.LocalPolicySnapshot
import mn.familyscreen.tv.engine.LocalTimeEngine
import mn.familyscreen.tv.engine.ScreenTimeState
import mn.familyscreen.tv.engine.UsageEventRecord
import mn.familyscreen.tv.engine.UsageEventStateMachine
import mn.familyscreen.tv.network.TvBackendClient
import mn.familyscreen.tv.storage.QueuedUsageSession
import mn.familyscreen.tv.storage.TvOfflineDatabase
import mn.familyscreen.tv.ui.FamilyScreenLauncherActivity
import java.time.Instant
import java.util.UUID
import java.util.concurrent.Executors

/**
 * Background / Foreground Enforcement Service for FamilyScreen Box.
 *
 * Implements Chronological UsageEvents State Machine Monitoring:
 * - Runs as a foreground service with `FOREGROUND_SERVICE_TYPE_SPECIAL_USE` on API 34.
 * - Ingests `UsageEvents` (ACTIVITY_RESUMED/MOVE_TO_FOREGROUND and ACTIVITY_PAUSED/MOVE_TO_BACKGROUND).
 * - Tracks multi-activity packages without false background dropouts.
 * - Exempts System UI (volume panel, input methods, Katniss) from unauthorized blocks.
 * - Rate-limits enforcement requests to eliminate infinite intent loops.
 * - Counts active viewing seconds ONLY when a whitelisted content app is active in foreground and screen is on.
 * - Enforces midnight rollover, persistent offline clock continuity, and 72-hour offline policy expiration.
 */
class UsageMonitoringService : Service() {

    private lateinit var offlineDb: TvOfflineDatabase
    private lateinit var backendClient: TvBackendClient
    private lateinit var timeEngine: LocalTimeEngine
    private lateinit var stateMachine: UsageEventStateMachine

    private val mainHandler = Handler(Looper.getMainLooper())
    private val ioExecutor = Executors.newSingleThreadExecutor()

    private var activeSessionPackage: String? = null
    private var activeSessionStartIso: String? = null
    private var activeSessionSeconds: Int = 0
    private var ticksSinceLastServerSync: Int = 0
    private var lastQueryTimestamp: Long = 0L
    private var lastEnforcedPackage: String? = null
    private var lastEnforcedTimestampMs: Long = 0L
    private var unknownSinceElapsedMs: Long? = null
    private var lastHoldingLaunchedMs: Long = 0L
    private var isHoldingActive: Boolean = false

    private val monitorRunnable = object : Runnable {
        override fun run() {
            val nowElapsed = SystemClock.elapsedRealtime()
            val nowWall = System.currentTimeMillis()
            val isInteractive = isScreenInteractive()
            stateMachine.setScreenInteractive(isInteractive)

            // 1. Verify Usage Access Permission (PACKAGE_USAGE_STATS via AppOps)
            val hasUsagePermission = checkUsageStatsPermission()
            val detectionState = if (!hasUsagePermission) {
                ForegroundDetectionState.PermissionMissing
            } else {
                pollUsageEvents(nowWall)
                stateMachine.evaluateCurrentState()
            }

            // Track Unknown state duration and clear holding when recovered
            if (detectionState is ForegroundDetectionState.Unknown) {
                if (unknownSinceElapsedMs == null) {
                    unknownSinceElapsedMs = nowElapsed
                }
            } else {
                unknownSinceElapsedMs = null
                if (isHoldingActive && detectionState is ForegroundDetectionState.KnownForeground) {
                    isHoldingActive = false
                    lastHoldingLaunchedMs = 0L
                    bringLauncherToFront("CLEAR_HOLDING", null)
                }
            }

            // 2. Evaluate Enforcement Decision via State Machine
            val (decision, activeContentPackage) = stateMachine.evaluateEnforcement(
                detectionState = detectionState,
                isPackageAllowed = { timeEngine.isPackageAllowed(it) },
                isTimeLimitBlocked = {
                    val currentEval = timeEngine.evaluate(nowElapsed)
                    currentEval.state == ScreenTimeState.BLOCK
                },
                timeLimitBlockReason = {
                    val currentEval = timeEngine.evaluate(nowElapsed)
                    currentEval.reason
                },
                nowElapsedMs = nowElapsed,
                lastEnforcedPackage = lastEnforcedPackage,
                lastEnforcedTimestampMs = lastEnforcedTimestampMs,
                throttleWindowMs = 2000L,
                unknownSinceElapsedMs = unknownSinceElapsedMs,
                lastHoldingLaunchedMs = lastHoldingLaunchedMs,
                unknownGracePeriodMs = 5000L,
                holdingThrottleWindowMs = 5000L
            )

            // 3. Act on Decision (Takeover launcher, enforce holding, or prompt permission)
            when (decision) {
                is EnforcementDecision.EnforceBlock -> {
                    if (decision.shouldTriggerLaunch) {
                        lastEnforcedPackage = decision.blockedPackage
                        lastEnforcedTimestampMs = nowElapsed
                        bringLauncherToFront(decision.reason, decision.blockedPackage)
                    }
                }
                is EnforcementDecision.EnforceHoldingScreen -> {
                    if (decision.shouldTriggerLaunch) {
                        isHoldingActive = true
                        lastHoldingLaunchedMs = nowElapsed
                        bringLauncherToFront(decision.reason, null)
                    }
                }
                is EnforcementDecision.RequestPermission -> {
                    // Prompt parent to grant permission, throttle to once every 10 seconds
                    if ((nowElapsed - lastEnforcedTimestampMs) > 10_000L) {
                        lastEnforcedTimestampMs = nowElapsed
                        bringLauncherToFront("PERMISSION_MISSING", null)
                    }
                }
                else -> {
                    // Clear last enforced package after leaving the blocked app
                    if (lastEnforcedPackage != null && (nowElapsed - lastEnforcedTimestampMs) > 5000L) {
                        lastEnforcedPackage = null
                    }
                }
            }

            // 4. Tick Active Viewing Seconds in LocalTimeEngine
            val eval = timeEngine.tickActiveViewingSeconds(
                deltaSeconds = 1,
                currentElapsedRealtimeMs = nowElapsed,
                foregroundPackage = activeContentPackage,
                isScreenInteractive = isInteractive
            )

            // 5. Persist updated usage and trusted clock anchor locally every 5 seconds
            if (eval.usedSecondsToday % 5 == 0) {
                offlineDb.savePolicySnapshot(
                    snapshot = timeEngine.currentSnapshot(),
                    usedSecondsToday = eval.usedSecondsToday,
                    lastTrustedUtcMs = timeEngine.computeTrustedUtcMs(nowElapsed),
                    lastLocalDate = eval.trustedLocalDate,
                    pinLockedUntilUtcMs = timeEngine.getPinLockedUntilUtcMs(),
                    failedPinAttempts = timeEngine.getFailedPinAttempts()
                )
            }

            // 6. Track active content session for batch backend sync
            if (isInteractive && activeContentPackage != null && timeEngine.isPackageAllowed(activeContentPackage)) {
                if (activeSessionPackage != activeContentPackage) {
                    flushActiveSessionSegment()
                    activeSessionPackage = activeContentPackage
                    activeSessionStartIso = Instant.ofEpochMilli(
                        timeEngine.computeTrustedUtcMs(nowElapsed)
                    ).toString()
                    activeSessionSeconds = 0
                }
                activeSessionSeconds += 1
                if (activeSessionSeconds >= 60) {
                    flushActiveSessionSegment()
                }
            } else {
                flushActiveSessionSegment()
            }

            // 7. Periodic server sync & offline queue drain every 30 seconds
            ticksSinceLastServerSync += 1
            if (ticksSinceLastServerSync >= 30) {
                ticksSinceLastServerSync = 0
                syncWithBackendAsync()
            }

            mainHandler.postDelayed(this, 1000L)
        }
    }

    override fun onCreate() {
        super.onCreate()
        startForegroundServiceInternal()

        offlineDb = TvOfflineDatabase(this)
        backendClient = TvBackendClient(offlineDb = offlineDb)
        stateMachine = UsageEventStateMachine(ownPackageName = packageName)
        lastQueryTimestamp = System.currentTimeMillis() - 300_000L // 5-minute historical lookback on startup

        val nowElapsed = SystemClock.elapsedRealtime()
        val restored = offlineDb.loadPolicySnapshot(nowElapsed)
        timeEngine = if (restored != null) {
            LocalTimeEngine(
                snapshot = restored.snapshot,
                accumulatedActiveSeconds = restored.usedSecondsToday,
                initialLocalDate = restored.lastEvaluatedLocalDate,
                persistentPinLockedUntilUtcMs = restored.pinLockedUntilUtcMs,
                initialFailedPinAttempts = restored.failedPinAttempts
            )
        } else {
            LocalTimeEngine(defaultBootstrapSnapshot(nowElapsed), 0)
        }

        mainHandler.post(monitorRunnable)
        syncWithBackendAsync()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundServiceInternal()
        return START_STICKY
    }

    private fun startForegroundServiceInternal() {
        createNotificationChannelIfNeeded()

        val notificationBuilder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, NOTIFICATION_CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }

        val notification = notificationBuilder
            .setContentTitle("FamilyScreen TV Хяналт")
            .setContentText("Дэлгэцийн цаг болон зөвшөөрөгдсөн аппын хамгаалалт идэвхтэй байна.")
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setOngoing(true)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun createNotificationChannelIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager
            if (nm != null && nm.getNotificationChannel(NOTIFICATION_CHANNEL_ID) == null) {
                val channel = NotificationChannel(
                    NOTIFICATION_CHANNEL_ID,
                    "FamilyScreen TV Background Protection",
                    NotificationManager.IMPORTANCE_LOW
                ).apply {
                    description = "FamilyScreen дэлгэцийн хэрэглээг хянах foreground үйлчилгээ"
                }
                nm.createNotificationChannel(channel)
            }
        }
    }

    override fun onDestroy() {
        mainHandler.removeCallbacks(monitorRunnable)
        flushActiveSessionSegment()
        ioExecutor.shutdownNow()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun flushActiveSessionSegment() {
        val pkg = activeSessionPackage ?: return
        val seconds = activeSessionSeconds
        val startIso = activeSessionStartIso ?: Instant.now().toString()
        activeSessionPackage = null
        activeSessionStartIso = null
        activeSessionSeconds = 0

        if (seconds <= 0) return
        val snap = timeEngine.currentSnapshot()
        if (snap.familyId.isBlank() || snap.deviceId.isBlank() || snap.childId.isBlank()) return

        val endIso = Instant.ofEpochMilli(
            timeEngine.computeTrustedUtcMs(SystemClock.elapsedRealtime())
        ).toString()

        val queued = QueuedUsageSession(
            clientSessionUid = "tv-sess-${UUID.randomUUID()}",
            familyId = snap.familyId,
            childId = snap.childId,
            deviceId = snap.deviceId,
            packageName = pkg,
            startedAtIso = startIso,
            endedAtIso = endIso,
            activeSeconds = seconds,
            syncedFromOffline = false
        )

        val token = offlineDb.getDeviceToken()
        ioExecutor.execute {
            backendClient.submitOrQueueUsageSession(queued, token)
        }
    }

    private fun syncWithBackendAsync() {
        val deviceId = offlineDb.getDeviceId() ?: return
        val token = offlineDb.getDeviceToken()
        ioExecutor.execute {
            try {
                backendClient.flushOfflineUsageQueue(token)
                val nowElapsed = SystemClock.elapsedRealtime()
                val syncRes = backendClient.syncDevicePolicy(deviceId, token, nowElapsed)
                mainHandler.post {
                    timeEngine.updateSnapshot(syncRes.snapshot, syncRes.usedSecondsToday)
                }
            } catch (_: Exception) {
                // Remain in offline mode using cached policy snapshot
            }
        }
    }

    private fun isScreenInteractive(): Boolean {
        val pm = getSystemService(Context.POWER_SERVICE) as? PowerManager
        return pm?.isInteractive ?: true
    }

    /**
     * Checks if PACKAGE_USAGE_STATS permission is granted in AppOps.
     */
    private fun checkUsageStatsPermission(): Boolean {
        val appOps = getSystemService(Context.APP_OPS_SERVICE) as? AppOpsManager ?: return false
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            appOps.unsafeCheckOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                android.os.Process.myUid(),
                packageName
            )
        } else {
            @Suppress("DEPRECATION")
            appOps.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                android.os.Process.myUid(),
                packageName
            )
        }
        return mode == AppOpsManager.MODE_ALLOWED
    }

    /**
     * Incremental query of Android UsageEvents using a bounded sliding window with safety overlap.
     */
    private fun pollUsageEvents(nowWall: Long) {
        val usm = getSystemService(Context.USAGE_STATS_SERVICE) as? UsageStatsManager ?: return
        val start = (lastQueryTimestamp - 2000L).coerceAtLeast(nowWall - 300_000L)
        val end = nowWall
        lastQueryTimestamp = nowWall

        val usageEvents = try {
            usm.queryEvents(start, end)
        } catch (_: Exception) {
            null
        } ?: return

        val eventList = mutableListOf<UsageEventRecord>()
        val ev = UsageEvents.Event()
        while (usageEvents.hasNextEvent()) {
            usageEvents.getNextEvent(ev)
            val pkg = ev.packageName
            if (!pkg.isNullOrBlank()) {
                eventList.add(
                    UsageEventRecord(
                        packageName = pkg,
                        className = ev.className,
                        eventType = ev.eventType,
                        timestamp = ev.timeStamp
                    )
                )
            }
        }
        stateMachine.processEvents(eventList)
    }

    private fun bringLauncherToFront(blockReason: String, blockedPackage: String? = null) {
        val launchIntent = Intent(this, FamilyScreenLauncherActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            putExtra("EXTRA_BLOCK_REASON", blockReason)
            if (!blockedPackage.isNullOrBlank()) {
                putExtra("EXTRA_BLOCKED_PACKAGE", blockedPackage)
            }
        }
        startActivity(launchIntent)
    }

    companion object {
        const val NOTIFICATION_CHANNEL_ID = "familyscreen_tv_monitoring"
        const val NOTIFICATION_ID = 1001

        fun defaultBootstrapSnapshot(nowElapsed: Long): LocalPolicySnapshot {
            return LocalPolicySnapshot(
                familyId = "",
                deviceId = "",
                childId = "c-bootstrap",
                childNickname = "Тэмүүлэн",
                policyVersion = 1,
                dailyLimitSeconds = 90 * 60,
                overrideSecondsToday = 0,
                pinHash = "",
                anchorElapsedRealtimeMs = nowElapsed,
                allowedApps = listOf(
                    AllowedAppEntry("com.google.android.apps.youtube.kids", "YouTube Kids", "VIDEO"),
                    AllowedAppEntry("org.khanacademy.android", "Khan Academy", "EDUCATION"),
                    AllowedAppEntry("com.duolingo", "Duolingo", "EDUCATION")
                )
            )
        }
    }
}

/**
 * Restores policy enforcement immediately when the Android TV Box boots up (`RECEIVE_BOOT_COMPLETED`).
 * Uses `startForegroundService` on Android 8.0+ to prevent BackgroundServiceStartNotAllowedException crashes.
 */
class BootPolicyRestoreReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        if (action == Intent.ACTION_BOOT_COMPLETED || action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            val svcIntent = Intent(context, UsageMonitoringService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(svcIntent)
            } else {
                context.startService(svcIntent)
            }
        }
    }
}
