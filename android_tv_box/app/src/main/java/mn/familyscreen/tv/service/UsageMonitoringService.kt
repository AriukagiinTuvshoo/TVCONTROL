package mn.familyscreen.tv.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
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
import mn.familyscreen.tv.engine.LocalPolicySnapshot
import mn.familyscreen.tv.engine.LocalTimeEngine
import mn.familyscreen.tv.engine.ScreenTimeState
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
 * Solves the Activity `onPause()` pitfall & adheres to Android 14 (API 34) Foreground Service Rules:
 * - Runs as a foreground service with `FOREGROUND_SERVICE_TYPE_SPECIAL_USE` on API 34.
 * - Continues monitoring when the child leaves Launcher to watch whitelisted apps (e.g. YouTube Kids).
 * - Checks `PowerManager.isInteractive` and foreground package via `UsageStatsManager`.
 * - Counts active viewing seconds ONLY when a whitelisted content app is in the foreground and screen is on.
 * - Enforces midnight rollover, persistent offline clock continuity, and offline policy expiration.
 * - Immediately brings [FamilyScreenLauncherActivity] to the front with BLOCK / WARNING state if
 *   an unauthorized app is opened or screen time expires.
 */
class UsageMonitoringService : Service() {

    private lateinit var offlineDb: TvOfflineDatabase
    private lateinit var backendClient: TvBackendClient
    private lateinit var timeEngine: LocalTimeEngine

    private val mainHandler = Handler(Looper.getMainLooper())
    private val ioExecutor = Executors.newSingleThreadExecutor()

    private var activeSessionPackage: String? = null
    private var activeSessionStartIso: String? = null
    private var activeSessionSeconds: Int = 0
    private var ticksSinceLastServerSync: Int = 0

    private val monitorRunnable = object : Runnable {
        override fun run() {
            val nowElapsed = SystemClock.elapsedRealtime()
            val isInteractive = isScreenInteractive()
            val fgPackage = resolveForegroundPackage() ?: activeSessionPackage

            val eval = timeEngine.tickActiveViewingSeconds(
                deltaSeconds = 1,
                currentElapsedRealtimeMs = nowElapsed,
                foregroundPackage = fgPackage,
                isScreenInteractive = isInteractive
            )

            // Persist updated usage and trusted clock anchor locally every 5 seconds
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

            // Track active content session for batch sync
            if (isInteractive && fgPackage != null && fgPackage != packageName && timeEngine.isPackageAllowed(fgPackage)) {
                if (activeSessionPackage != fgPackage) {
                    flushActiveSessionSegment()
                    activeSessionPackage = fgPackage
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

            // Enforce Whitelist or Screen Time Block by bringing Launcher to foreground
            val unauthorizedAppOpen = isInteractive &&
                fgPackage != null &&
                fgPackage != packageName &&
                !timeEngine.isPackageAllowed(fgPackage)

            if (unauthorizedAppOpen || (isInteractive && eval.state == ScreenTimeState.BLOCK && fgPackage != packageName)) {
                bringLauncherToFront(eval.reason)
            }

            // Periodic server sync & offline queue drain every 30 seconds
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

    private fun resolveForegroundPackage(): String? {
        val usm = getSystemService(Context.USAGE_STATS_SERVICE) as? UsageStatsManager ?: return null
        val end = System.currentTimeMillis()
        val start = end - 10_000L
        val stats = usm.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, start, end)
        if (stats.isNullOrEmpty()) return null
        return stats.maxByOrNull { it.lastTimeUsed }?.packageName
    }

    private fun bringLauncherToFront(blockReason: String) {
        val launchIntent = Intent(this, FamilyScreenLauncherActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            putExtra("EXTRA_BLOCK_REASON", blockReason)
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