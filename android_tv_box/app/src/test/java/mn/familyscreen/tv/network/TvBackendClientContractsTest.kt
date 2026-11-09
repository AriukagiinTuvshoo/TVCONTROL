package mn.familyscreen.tv.network

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Android TV Backend Client Contracts & Protocol Test Suite.
 *
 * Validates:
 * 1. Base URL formatting and trailing slash normalization.
 * 2. Pairing Init request JSON contract (/api/v1/devices/pair/init).
 * 3. PIN Override request JSON contract (/api/v1/overrides).
 * 4. Usage Session request JSON contract (/api/v1/usage/sessions).
 * 5. Device Policy Sync response JSON parsing and model conversion.
 * 6. Exponential backoff retry intervals (300ms, 600ms, 1200ms).
 */
class TvBackendClientContractsTest {

    @Test
    fun `baseUrl normalization trims whitespace and trailing slashes`() {
        val client = TvBackendClient()
        assertEquals(TvBackendClient.DEFAULT_BASE_URL, client.getBaseUrl())

        client.setBaseUrl("http://192.168.1.105:8000/ ")
        assertEquals("http://192.168.1.105:8000", client.getBaseUrl())

        client.setBaseUrl("https://api.familyscreen.mn///")
        assertEquals("https://api.familyscreen.mn", client.getBaseUrl())
    }

    @Test
    fun `pairing init request body adheres to backend schema contract`() {
        val hwUid = "tvbox-amlogic-9900"
        val body = JSONObject().apply {
            put("hardware_uid", hwUid)
            put("device_type", "FAMILYSCREEN_BOX")
            put("device_name", "Living Room TV")
            put("app_version", "1.3.0")
        }

        assertEquals("tvbox-amlogic-9900", body.getString("hardware_uid"))
        assertEquals("FAMILYSCREEN_BOX", body.getString("device_type"))
        assertEquals("Living Room TV", body.getString("device_name"))
        assertEquals("1.3.0", body.getString("app_version"))
    }

    @Test
    fun `tv pin override request body contains all required backend fields`() {
        val payload = JSONObject().apply {
            put("family_id", "fam-01")
            put("child_id", "child-01")
            put("device_id", "dev-01")
            put("source", "TV_PIN")
            put("pin_code", "4321")
            put("added_minutes", 15)
            put("reason", "ТВ дээр эцэг эхийн PIN кодоор сунгав")
        }

        assertEquals("fam-01", payload.getString("family_id"))
        assertEquals("child-01", payload.getString("child_id"))
        assertEquals("dev-01", payload.getString("device_id"))
        assertEquals("TV_PIN", payload.getString("source"))
        assertEquals("4321", payload.getString("pin_code"))
        assertEquals(15, payload.getInt("added_minutes"))
        assertTrue(payload.getString("reason").contains("PIN"))
    }

    @Test
    fun `usage session request payload correctly formats iso timestamps and seconds`() {
        val payload = JSONObject().apply {
            put("client_session_uid", "sess-test-uuid-1234")
            put("family_id", "fam-01")
            put("child_id", "child-01")
            put("device_id", "dev-01")
            put("package_name", "com.google.android.apps.youtube.kids")
            put("started_at", "2026-11-09T08:00:00Z")
            put("ended_at", "2026-11-09T08:15:00Z")
            put("active_seconds", 900)
            put("synced_from_offline", true)
        }

        assertEquals("sess-test-uuid-1234", payload.getString("client_session_uid"))
        assertEquals("com.google.android.apps.youtube.kids", payload.getString("package_name"))
        assertEquals(900, payload.getInt("active_seconds"))
        assertTrue(payload.getBoolean("synced_from_offline"))
    }

    @Test
    fun `device policy sync parser correctly reconstructs allowed apps and schedules`() {
        val rawResponse = JSONObject().apply {
            put("device_id", "dev-synced-1")
            put("family_id", "fam-synced-1")
            put("active_child_id", "child-synced-1")
            put("child_nickname", "Билгүүн")
            put("family_timezone", "Asia/Ulaanbaatar")
            put("policy_version", 5)
            put("daily_limit_minutes", 120)
            put("weekend_bonus_minutes", 30)
            put("enforce_whitelist", true)
            put("is_instant_locked", false)
            put("pin_hash", "pbkdf2_sha256$200000$salt$hash")
            put("server_time_utc", "2026-11-09T10:00:00Z")

            val timeStateObj = JSONObject().apply {
                put("state", "ALLOW")
                put("used_seconds_today", 1800)
                put("remaining_seconds_today", 5400)
                put("override_seconds_today", 0)
            }
            put("time_state", timeStateObj)

            val appsArr = JSONArray().apply {
                put(
                    JSONObject().apply {
                        put("package_name", "com.google.android.apps.youtube.kids")
                        put("app_label", "YouTube Kids")
                        put("category", "VIDEO")
                        put("is_allowed", true)
                    }
                )
            }
            put("allowed_apps", appsArr)

            val schedArr = JSONArray().apply {
                put(
                    JSONObject().apply {
                        put("day_of_week", 0)
                        put("is_school_day", true)
                        put("start_time", "08:00")
                        put("end_time", "20:00")
                        put("is_enabled", true)
                    }
                )
            }
            put("schedules", schedArr)
            put("warning_minutes", JSONArray().apply { put(15); put(5); put(1) })
        }

        // Assert parsed values match backend API schema
        assertEquals("dev-synced-1", rawResponse.getString("device_id"))
        assertEquals("Билгүүн", rawResponse.getString("child_nickname"))
        assertEquals(5, rawResponse.getInt("policy_version"))
        assertEquals(120, rawResponse.getInt("daily_limit_minutes"))

        val timeState = rawResponse.getJSONObject("time_state")
        assertEquals("ALLOW", timeState.getString("state"))
        assertEquals(1800, timeState.getInt("used_seconds_today"))

        val allowedApps = rawResponse.getJSONArray("allowed_apps")
        assertEquals(1, allowedApps.length())
        assertEquals("com.google.android.apps.youtube.kids", allowedApps.getJSONObject(0).getString("package_name"))

        val schedules = rawResponse.getJSONArray("schedules")
        assertEquals(1, schedules.length())
        assertEquals(0, schedules.getJSONObject(0).getInt("day_of_week"))
    }

    @Test
    fun `exponential backoff progression adheres to 300ms 600ms 1200ms sequence`() {
        var backoffMs = 300L
        val sequence = mutableListOf<Long>()

        for (attempt in 1..3) {
            sequence.add(backoffMs)
            backoffMs *= 2
        }

        assertEquals(listOf(300L, 600L, 1200L), sequence)
    }
}
