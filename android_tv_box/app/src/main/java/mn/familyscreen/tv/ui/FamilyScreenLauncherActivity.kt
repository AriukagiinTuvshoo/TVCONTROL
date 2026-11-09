package mn.familyscreen.tv.ui

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import mn.familyscreen.tv.engine.LocalTimeEngine
import mn.familyscreen.tv.engine.LocalTimeEvaluation
import mn.familyscreen.tv.engine.ScreenTimeState
import mn.familyscreen.tv.network.TvBackendClient
import mn.familyscreen.tv.service.UsageMonitoringService
import mn.familyscreen.tv.storage.TvOfflineDatabase
import java.util.concurrent.Executors

/**
 * FamilyScreen Box Launcher & Android TV Enforcement Activity.
 *
 * Implements:
 * - Device Pairing HUD (6-digit pairing code + QR URI + auto-claim polling)
 * - Leanback D-Pad Remote Control Navigation (`isFocusable = true`, `isFocusableInTouchMode = true`)
 * - Whitelisted Apps Launcher Grid (FR-10)
 * - 15 / 5 / 1 Minute Warning Banner (FR-06)
 * - Full-screen Block Overlay when quota expires, outside schedule, or parent triggers Instant Lock (FR-04 / FR-05)
 * - Parent PIN Override (+5, +15, +30 min) with Online + Offline verification (FR-07)
 * - Correct usage counting via [UsageMonitoringService] (does NOT falsely pause when launching a child app!)
 */
class FamilyScreenLauncherActivity : Activity() {

    private lateinit var offlineDb: TvOfflineDatabase
    private lateinit var backendClient: TvBackendClient
    private lateinit var timeEngine: LocalTimeEngine

    private lateinit var statusHeaderText: TextView
    private lateinit var pairingBannerText: TextView
    private lateinit var warningBannerText: TextView
    private lateinit var blockReasonText: TextView
    private lateinit var appsContainer: LinearLayout
    private lateinit var pinInput: EditText

    private val mainHandler = Handler(Looper.getMainLooper())
    private val ioExecutor = Executors.newSingleThreadExecutor()
    private var activePairingCode: String? = null

    private val uiRefreshRunnable = object : Runnable {
        override fun run() {
            val nowElapsed = SystemClock.elapsedRealtime()
            val restored = offlineDb.loadPolicySnapshot(nowElapsed)
            if (restored != null) {
                timeEngine.updateSnapshot(restored.snapshot, restored.usedSecondsToday)
            }
            val eval = timeEngine.evaluate(nowElapsed)
            renderTimeEvaluation(eval)
            mainHandler.postDelayed(this, 1000L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        offlineDb = TvOfflineDatabase(this)
        intent?.getStringExtra("EXTRA_BACKEND_URL")?.let { customUrl ->
            if (customUrl.isNotBlank()) {
                offlineDb.saveBackendBaseUrl(customUrl)
            }
        }
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
            LocalTimeEngine(UsageMonitoringService.defaultBootstrapSnapshot(nowElapsed), 0)
        }

        // Start persistent UsageMonitoringService via Foreground Service
        val svcIntent = Intent(this, UsageMonitoringService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(svcIntent)
        } else {
            startService(svcIntent)
        }

        buildLeanbackUi()
        ensurePairedOrSync()
    }

    private fun buildLeanbackUi() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setBackgroundColor(Color.parseColor("#0F172A"))
            setPadding(64, 48, 64, 48)
        }

        statusHeaderText = TextView(this).apply {
            textSize = 26f
            setTextColor(Color.WHITE)
            text = "FamilyScreen Box • Ачаалж байна..."
        }

        pairingBannerText = TextView(this).apply {
            textSize = 18f
            setTextColor(Color.parseColor("#38BDF8"))
            visibility = View.GONE
        }

        warningBannerText = TextView(this).apply {
            textSize = 20f
            setTextColor(Color.parseColor("#FACC15"))
            setPadding(0, 12, 0, 12)
        }

        blockReasonText = TextView(this).apply {
            textSize = 22f
            setTextColor(Color.parseColor("#F87171"))
            visibility = View.GONE
        }

        appsContainer = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, 24, 0, 24)
        }

        root.addView(statusHeaderText)
        root.addView(pairingBannerText)
        root.addView(warningBannerText)
        root.addView(blockReasonText)
        root.addView(appsContainer)

        // Parent PIN Override section (D-Pad friendly)
        pinInput = EditText(this).apply {
            hint = "Эцэг эхийн 4-6 оронтой PIN код"
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
            isFocusable = true
            isFocusableInTouchMode = true
        }
        root.addView(pinInput)

        val overrideRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        listOf(5, 15, 30).forEach { mins ->
            val btn = Button(this).apply {
                text = "+$mins мин (PIN)"
                isFocusable = true
                isFocusableInTouchMode = true
                setOnClickListener { handlePinOverride(mins) }
            }
            overrideRow.addView(btn)
        }
        root.addView(overrideRow)

        setContentView(root)
        rebuildAllowedAppButtons()
    }

    private fun rebuildAllowedAppButtons() {
        appsContainer.removeAllViews()
        val snap = timeEngine.currentSnapshot()
        snap.allowedApps.filter { it.isAllowed }.forEachIndexed { idx, appEntry ->
            val btn = Button(this).apply {
                text = appEntry.label
                isFocusable = true
                isFocusableInTouchMode = true
                setOnClickListener {
                    launchWhitelistedApp(appEntry.packageName)
                }
            }
            appsContainer.addView(btn)
            if (idx == 0) {
                btn.requestFocus()
            }
        }
    }

    private fun ensurePairedOrSync() {
        val hwUid = resolveHardwareUid()
        if (!offlineDb.isDevicePaired()) {
            ioExecutor.execute {
                try {
                    val initRes = backendClient.initDevicePairing(hardwareUid = hwUid)
                    activePairingCode = initRes.pairingCode
                    mainHandler.post {
                        pairingBannerText.visibility = View.VISIBLE
                        pairingBannerText.text =
                            "ТВ Холбох Код: ${initRes.pairingCode} (Гар утасны FamilyScreen апп дээр оруулна уу)"
                    }
                    pollPairingClaimStatus(initRes.pairingCode, hwUid)
                } catch (_: Exception) {
                    mainHandler.post {
                        pairingBannerText.visibility = View.VISIBLE
                        pairingBannerText.text = "Оффлайн горим: Хадгалсан локал дүрмээр ажиллаж байна."
                    }
                }
            }
        } else {
            syncPolicyNow()
        }
    }

    private fun pollPairingClaimStatus(code: String, hwUid: String) {
        ioExecutor.execute {
            for (attempt in 1..60) {
                try {
                    val statusRes = backendClient.checkPairingStatus(code, hwUid)
                    if (statusRes.status == "CLAIMED" && !statusRes.deviceToken.isNullOrBlank()) {
                        mainHandler.post {
                            pairingBannerText.visibility = View.GONE
                            Toast.makeText(
                                this,
                                "Гэр бүлийн бүртгэлтэй амжилттай холбогдлоо!",
                                Toast.LENGTH_LONG
                            ).show()
                        }
                        syncPolicyNow()
                        return@execute
                    }
                    Thread.sleep(3000L)
                } catch (_: Exception) {
                    Thread.sleep(3000L)
                }
            }
        }
    }

    private fun syncPolicyNow() {
        val deviceId = offlineDb.getDeviceId() ?: return
        val token = offlineDb.getDeviceToken()
        ioExecutor.execute {
            try {
                backendClient.flushOfflineUsageQueue(token)
                val nowElapsed = SystemClock.elapsedRealtime()
                val syncRes = backendClient.syncDevicePolicy(deviceId, token, nowElapsed)
                mainHandler.post {
                    timeEngine.updateSnapshot(syncRes.snapshot, syncRes.usedSecondsToday)
                    rebuildAllowedAppButtons()
                    renderTimeEvaluation(timeEngine.evaluate(nowElapsed))
                }
            } catch (_: Exception) {
                // Offline fallback remains active
            }
        }
    }

    private fun handlePinOverride(addedMinutes: Int) {
        val enteredPin = pinInput.text.toString().trim()
        if (enteredPin.startsWith("http://") || enteredPin.startsWith("https://")) {
            offlineDb.saveBackendBaseUrl(enteredPin)
            backendClient.setBaseUrl(enteredPin)
            pinInput.setText("")
            Toast.makeText(this, "Серверийн хаяг тохируулагдлаа: $enteredPin", Toast.LENGTH_LONG).show()
            syncPolicyNow()
            return
        }
        val nowElapsed = SystemClock.elapsedRealtime()
        val localOk = timeEngine.verifyPinAndGrantOverride(enteredPin, addedMinutes, nowElapsed)
        if (!localOk) {
            Toast.makeText(this, "PIN код буруу эсвэл 15 минут түр түгжигдсэн байна.", Toast.LENGTH_SHORT).show()
            return
        }

        pinInput.setText("")
        val eval = timeEngine.evaluate(nowElapsed)
        offlineDb.savePolicySnapshot(
            snapshot = timeEngine.currentSnapshot(),
            usedSecondsToday = timeEngine.currentUsedSeconds(),
            lastTrustedUtcMs = timeEngine.computeTrustedUtcMs(nowElapsed),
            lastLocalDate = eval.trustedLocalDate,
            pinLockedUntilUtcMs = timeEngine.getPinLockedUntilUtcMs(),
            failedPinAttempts = timeEngine.getFailedPinAttempts()
        )
        renderTimeEvaluation(eval)
        Toast.makeText(this, "+$addedMinutes минут нэмэлт хугацаа нээгдлээ!", Toast.LENGTH_SHORT).show()

        // Also synchronize the PIN override to Cloud Backend if online
        val snap = timeEngine.currentSnapshot()
        val token = offlineDb.getDeviceToken()
        if (snap.familyId.isNotBlank() && snap.deviceId.isNotBlank()) {
            ioExecutor.execute {
                backendClient.submitTvPinOverride(
                    familyId = snap.familyId,
                    childId = snap.childId,
                    deviceId = snap.deviceId,
                    pinCode = enteredPin,
                    addedMinutes = addedMinutes,
                    deviceToken = token
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent?.getStringExtra("EXTRA_BACKEND_URL")?.let { customUrl ->
            if (customUrl.isNotBlank()) {
                offlineDb.saveBackendBaseUrl(customUrl)
                backendClient.setBaseUrl(customUrl)
                Toast.makeText(this, "Серверийн хаяг: $customUrl", Toast.LENGTH_SHORT).show()
                syncPolicyNow()
            }
        }
    }

    override fun onResume() {
        super.onResume()
        mainHandler.post(uiRefreshRunnable)
        syncPolicyNow()
    }

    override fun onPause() {
        super.onPause()
        // Stop UI-only text refresh when Launcher is in background;
        // actual active content usage counting continues in UsageMonitoringService!
        mainHandler.removeCallbacks(uiRefreshRunnable)
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        // Prevent child from exiting FamilyScreen Box Launcher via BACK button when in BLOCK state
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            val eval = timeEngine.evaluate(SystemClock.elapsedRealtime())
            if (eval.state == ScreenTimeState.BLOCK) {
                return true
            }
        }
        return super.onKeyDown(keyCode, event)
    }

    private fun renderTimeEvaluation(eval: LocalTimeEvaluation) {
        val snap = timeEngine.currentSnapshot()
        val remMin = eval.remainingSeconds / 60
        val remSec = eval.remainingSeconds % 60
        statusHeaderText.text = String.format(
            "FamilyScreen • %s • Үлдсэн: %02d:%02d",
            snap.childNickname,
            remMin,
            remSec
        )

        when (eval.state) {
            ScreenTimeState.ALLOW -> {
                warningBannerText.text = "Төлөв: ALLOW — Зөвшөөрөгдсөн аппуудыг үзэх боломжтой."
                blockReasonText.visibility = View.GONE
                appsContainer.visibility = View.VISIBLE
            }
            ScreenTimeState.WARNING -> {
                warningBannerText.text =
                    "АНХААРУУЛГА: Хугацаа дуусахад ${eval.activeWarningMinutes} минут үлдлээ!"
                blockReasonText.visibility = View.GONE
                appsContainer.visibility = View.VISIBLE
            }
            ScreenTimeState.BLOCK -> {
                warningBannerText.text = "Төлөв: BLOCK — Үзэх хугацаа дууссан эсвэл түгжигдсэн."
                blockReasonText.visibility = View.VISIBLE
                blockReasonText.text = when (eval.reason) {
                    "PARENT_INSTANT_LOCK" -> "Эцэг эх гар утаснаасаа ТВ-ийг түр түгжсэн байна."
                    "OUTSIDE_SCHEDULE_WINDOW" -> "Цагийн хуваарийн гадуур байна. Эцэг эхийн зөвшөөрөл шаардлагатай."
                    "OFFLINE_POLICY_EXPIRED" -> "ТВ 72 цаг сервертэй холбогдоогүй тул аюулгүй байдлын үүднээс түр түгжигдлээ."
                    else -> "Өнөөдрийн зөвшөөрөгдсөн хугацаа дууслаа. PIN эсвэл гар утаснаас сунгана уу."
                }
                appsContainer.visibility = View.GONE
            }
        }
    }

    private fun launchWhitelistedApp(packageName: String) {
        val eval = timeEngine.evaluate(SystemClock.elapsedRealtime())
        if (eval.state == ScreenTimeState.BLOCK) {
            Toast.makeText(this, "Үзэх хугацаа дууссан тул апп нээх боломжгүй.", Toast.LENGTH_LONG).show()
            return
        }
        if (!timeEngine.isPackageAllowed(packageName)) {
            Toast.makeText(this, "Энэ апп зөвшөөрөгдсөн жагсаалтад (Whitelist) байхгүй байна.", Toast.LENGTH_LONG).show()
            return
        }
        val launchIntent: Intent? = packageManager.getLaunchIntentForPackage(packageName)
        if (launchIntent != null) {
            startActivity(launchIntent)
        } else {
            Toast.makeText(this, "$packageName суугаагүй байна.", Toast.LENGTH_SHORT).show()
        }
    }

    private fun resolveHardwareUid(): String {
        val androidId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
        return if (!androidId.isNullOrBlank()) "tvbox-$androidId" else "tvbox-default-001"
    }

    override fun onDestroy() {
        mainHandler.removeCallbacks(uiRefreshRunnable)
        ioExecutor.shutdownNow()
        super.onDestroy()
    }
}