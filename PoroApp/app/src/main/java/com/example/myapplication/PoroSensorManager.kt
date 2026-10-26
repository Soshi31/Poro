package com.example.myapplication

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Build
import android.os.CombinedVibration
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlin.math.sqrt

class PoroSensorManager(
    private val context: Context,
    private val coroutineScope: CoroutineScope
) : SensorEventListener {

    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val proximitySensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_PROXIMITY)
    private val accelerometerSensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)

    private var lastProximityTime = 0L
    private val PROXIMITY_COOLDOWN_MS = 2500L

    private var lastShakeTime = 0L
    private val SHAKE_COOLDOWN_MS = 4800L // 4.8 secunde cooldown pe senzor
    private val SHAKE_THRESHOLD_G = 2.8f
    
    private var lastRattleTime = 0L

    private val _isDeviceNearby = MutableStateFlow(false)
    val isDeviceNearby: StateFlow<Boolean> = _isDeviceNearby.asStateFlow()

    private val _lastGForce = MutableStateFlow(0f)
    val lastGForce: StateFlow<Float> = _lastGForce.asStateFlow()

    // Expunem accelerația pentru fizica 2D din UI
    private val _accelX = MutableStateFlow(0f)
    val accelX: StateFlow<Float> = _accelX.asStateFlow()
    
    private val _accelY = MutableStateFlow(0f)
    val accelY: StateFlow<Float> = _accelY.asStateFlow()

    var onTossDetected: (() -> Unit)? = null

    fun startListening() {
        proximitySensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_UI)
        }
        accelerometerSensor?.let {
            // Folosim DELAY_GAME (20ms) pentru o animație fizică fluidă (aprox 50-60 FPS)
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }
    }

    fun stopListening() {
        sensorManager.unregisterListener(this)
    }

    override fun onSensorChanged(event: SensorEvent?) {
        if (event == null) return

        val currentTime = System.currentTimeMillis()

        when (event.sensor.type) {
            Sensor.TYPE_PROXIMITY -> {
                val distance = event.values[0]
                // Senzorul hardware de proximitate de pe telefon raportează 0.0 cm când este acoperit/lipit fizic
                val isNearby = distance == 0.0f

                _isDeviceNearby.value = isNearby

                if (isNearby && (currentTime - lastProximityTime > PROXIMITY_COOLDOWN_MS)) {
                    lastProximityTime = currentTime
                    coroutineScope.launch(Dispatchers.IO) {
                        PoroApiClient.sendAction("DEVICE_NEARBY")
                    }
                }
            }
            Sensor.TYPE_ACCELEROMETER -> {
                val x = event.values[0]
                val y = event.values[1]
                val z = event.values[2]
                
                // Mapează direcția de accelerație pe planul Canvas-ului (2D)
                // Când telefonul e ținut drept: Y e ~9.8 (gravitația trage în jos pe ecran)
                // Când e înclinat stânga: X e ~9.8 (gravitația trage la stânga, Canvas are -X)
                _accelX.value = -x
                _accelY.value = y

                val gX = x / SensorManager.GRAVITY_EARTH
                val gY = y / SensorManager.GRAVITY_EARTH
                val gZ = z / SensorManager.GRAVITY_EARTH

                val gForce = sqrt(gX * gX + gY * gY + gZ * gZ)
                _lastGForce.value = gForce
                
                // Rattle effect (1.8g) - microvibrații când se agită ușor biscuiții
                if (gForce > 1.8f && (currentTime - lastRattleTime > 150)) {
                    lastRattleTime = currentTime
                    triggerMicroVibration()
                }

                // Toss effect (2.8g) - Aruncarea snax-ului
                if (gForce > SHAKE_THRESHOLD_G && (currentTime - lastShakeTime > SHAKE_COOLDOWN_MS)) {
                    lastShakeTime = currentTime
                    triggerFirmVibration()
                    onTossDetected?.invoke()
                }
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) { }

    fun triggerMicroVibration() {
        triggerVibration(15L, 50) // Scurtă, intensitate medie-scăzută
    }

    private fun triggerFirmVibration() {
        triggerVibration(150L, VibrationEffect.DEFAULT_AMPLITUDE) // Lungă și fermă
    }

    private fun triggerVibration(duration: Long, amplitude: Int) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val vibratorManager = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager
            val effect = VibrationEffect.createOneShot(duration, amplitude)
            val combined = CombinedVibration.createParallel(effect)
            vibratorManager.vibrate(combined)
        } else {
            @Suppress("DEPRECATION")
            val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(VibrationEffect.createOneShot(duration, amplitude))
            } else {
                @Suppress("DEPRECATION")
                vibrator.vibrate(duration)
            }
        }
    }
}
