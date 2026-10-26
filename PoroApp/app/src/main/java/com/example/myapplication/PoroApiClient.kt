package com.example.myapplication

import com.google.gson.Gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.coroutineContext

data class ActionRequest(val action: String, val parameter: String? = null)
data class GazeRequest(val x: Float, val y: Float)
data class ChatRequest(val message: String)

data class BnoData(val roll: Float, val pitch: Float, val shaken: Boolean)
data class TelemetryResponse(
    val status: String,
    val battery_ok: Boolean,
    val last_text: String,
    val bno: BnoData
)

object PoroApiClient {
    private var baseUrl = "http://192.168.1.50:8000"
    
    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()
        
    private val gson = Gson()
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    private val _telemetryFlow = MutableStateFlow<TelemetryResponse?>(null)
    val telemetryFlow: StateFlow<TelemetryResponse?> = _telemetryFlow.asStateFlow()

    private val _isOnline = MutableStateFlow(false)
    val isOnline: StateFlow<Boolean> = _isOnline.asStateFlow()

    fun setBaseUrl(url: String) {
        baseUrl = if (!url.startsWith("http://") && !url.startsWith("https://")) {
            "http://$url"
        } else {
            url
        }
    }
    
    fun getBaseUrl(): String = baseUrl

    suspend fun sendAction(action: String, parameter: String? = null): Boolean = withContext(Dispatchers.IO) {
        val requestBody = gson.toJson(ActionRequest(action, parameter)).toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url("$baseUrl/api/action")
            .post(requestBody)
            .build()
            
        try {
            client.newCall(request).execute().use { response ->
                response.isSuccessful
            }
        } catch (e: IOException) {
            false
        }
    }

    suspend fun sendGaze(x: Float, y: Float): Boolean = withContext(Dispatchers.IO) {
        val requestBody = gson.toJson(GazeRequest(x, y)).toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url("$baseUrl/api/gaze")
            .post(requestBody)
            .build()

        try {
            client.newCall(request).execute().use { response ->
                response.isSuccessful
            }
        } catch (e: IOException) {
            false
        }
    }

    suspend fun sendChat(message: String): Boolean = withContext(Dispatchers.IO) {
        val requestBody = gson.toJson(ChatRequest(message)).toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url("$baseUrl/api/chat")
            .post(requestBody)
            .build()

        try {
            client.newCall(request).execute().use { response ->
                response.isSuccessful
            }
        } catch (e: IOException) {
            false
        }
    }

    suspend fun startTelemetryPolling() = withContext(Dispatchers.IO) {
        while (coroutineContext.isActive) {
            val request = Request.Builder()
                .url("$baseUrl/api/telemetry")
                .get()
                .build()

            try {
                client.newCall(request).execute().use { response ->
                    if (response.isSuccessful) {
                        val body = response.body?.string()
                        if (body != null) {
                            val telemetry = gson.fromJson(body, TelemetryResponse::class.java)
                            _telemetryFlow.value = telemetry
                            _isOnline.value = true
                        } else {
                            _isOnline.value = false
                        }
                    } else {
                        _isOnline.value = false
                    }
                }
            } catch (e: IOException) {
                _isOnline.value = false
            }
            delay(1500)
        }
    }
}
