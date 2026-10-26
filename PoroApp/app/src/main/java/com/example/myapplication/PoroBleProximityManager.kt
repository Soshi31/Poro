package com.example.myapplication

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.ParcelUuid
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.ArrayDeque
import java.util.UUID
import kotlin.math.pow

data class BleProximityState(
    val isScanning: Boolean = false,
    val rssi: Int = 0,
    val smoothedRssi: Float = 0f,
    val distanceMeters: Float = -1f,
    val isNear: Boolean = false, // true daca distanta <= 1.0 m
    val status: String = "FAR",  // "NEAR" sau "FAR"
    val deviceName: String = "Raspberry Pi"
)

class PoroBleProximityManager(private val context: Context) {

    private val bluetoothAdapter: BluetoothAdapter? by lazy {
        val manager = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        manager?.adapter
    }

    private val bluetoothLeScanner: BluetoothLeScanner?
        get() = bluetoothAdapter?.bluetoothLeScanner

    private val _state = MutableStateFlow(BleProximityState())
    val state: StateFlow<BleProximityState> = _state.asStateFlow()

    // Fereastră pentru algoritmul Moving Average (Ultimele 5 citiri RSSI)
    private val rssiBuffer = ArrayDeque<Int>(5)

    // Parametrii de calibrare pentru log-distance path loss
    private val txPower = -59 // RSSI măsurat la 1 metru
    private val pathLossExponent = 2.0 // Exponent de propagare n (2.0 pentru mediu deschis)

    // Timestamp al ultimei recepții BLE de la Poro
    private var lastSeenTimestamp = 0L

    private val scanCallback = object : ScanCallback() {
        @SuppressLint("MissingPermission")
        override fun onScanResult(callbackType: Int, result: ScanResult?) {
            if (result == null) return

            val device = result.device
            val scanRecordName = result.scanRecord?.deviceName
            val deviceName = try { device.name ?: scanRecordName ?: "" } catch (e: Exception) { "" }

            // Filtrare strictă: Procesăm RSSI DOAR pentru dispozitivul robotului Poro / Raspberry Pi
            val isPoroDevice = deviceName.contains("Poro", ignoreCase = true) || 
                               deviceName.contains("Raspberry", ignoreCase = true) || 
                               deviceName.contains("Pi", ignoreCase = true) ||
                               scanRecordName?.contains("Poro", ignoreCase = true) == true

            if (isPoroDevice) {
                lastSeenTimestamp = System.currentTimeMillis()
                val rawRssi = result.rssi
                val smoothedRssi = calculateMovingAverageRssi(rawRssi)
                val distance = calculateDistanceMeters(smoothedRssi)

                // Prag de proximitate: 1.0m
                val isNear = distance in 0.0f..1.0f
                val statusStr = if (isNear) "NEAR" else "FAR"

                _state.value = BleProximityState(
                    isScanning = true,
                    rssi = rawRssi,
                    smoothedRssi = smoothedRssi,
                    distanceMeters = distance,
                    isNear = isNear,
                    status = statusStr,
                    deviceName = if (deviceName.isNotBlank()) deviceName else "Poro Robot"
                )
            }
        }

        override fun onScanFailed(errorCode: Int) {
            _state.value = _state.value.copy(isScanning = false)
        }
    }

    @SuppressLint("MissingPermission")
    fun startScan() {
        val scanner = bluetoothLeScanner ?: return
        if (_state.value.isScanning) return

        try {
            val settings = ScanSettings.Builder()
                .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                .build()

            // Putem adăuga un filtru pentru UUID-ul Poro sau prefixe MAC Raspberry Pi ("B8:27:EB", "DC:A6:32", "E4:5F:01")
            val filters = mutableListOf<ScanFilter>()
            
            // Exemplu de filtru pe Service UUID (dacă Pi transmite BLE advertisement)
            // val serviceUuid = ParcelUuid(UUID.fromString("0000180a-0000-1000-8000-00805f9b34fb"))
            // filters.add(ScanFilter.Builder().setServiceUuid(serviceUuid).build())

            scanner.startScan(filters, settings, scanCallback)
            _state.value = _state.value.copy(isScanning = true)
        } catch (e: Exception) {
            _state.value = _state.value.copy(isScanning = false)
        }
    }

    @SuppressLint("MissingPermission")
    fun stopScan() {
        val scanner = bluetoothLeScanner ?: return
        if (!_state.value.isScanning) return

        try {
            scanner.stopScan(scanCallback)
        } catch (e: Exception) { }
        _state.value = _state.value.copy(isScanning = false)
    }

    private fun calculateMovingAverageRssi(newRssi: Int): Float {
        if (rssiBuffer.size >= 5) {
            rssiBuffer.removeFirst()
        }
        rssiBuffer.addLast(newRssi)
        return rssiBuffer.average().toFloat()
    }

    private fun calculateDistanceMeters(rssi: Float): Float {
        if (rssi == 0f) return -1f
        // Formula: d = 10 ^ ((txPower - RSSI) / (10 * n))
        val exponent = (txPower - rssi) / (10f * pathLossExponent)
        return Math.pow(10.0, exponent.toDouble()).toFloat()
    }
}
