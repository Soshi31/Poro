package com.example.myapplication

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.Context
import com.google.gson.Gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import java.io.IOException
import java.util.UUID

data class WifiCredentials(val ssid: String, val pass: String)

data class WifiProvisionResult(
    val success: Boolean,
    val ipAddress: String? = null,
    val message: String
)

class PoroBluetoothManager(private val context: Context) {

    private val bluetoothAdapter: BluetoothAdapter? by lazy {
        val manager = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        manager?.adapter
    }

    // Standard Serial Port Profile (SPP) UUID
    private val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")

    private val _status = MutableStateFlow("Deconectat")
    val status: StateFlow<String> = _status.asStateFlow()

    private val gson = Gson()

    @SuppressLint("MissingPermission")
    fun getPoroDevices(): List<BluetoothDevice> {
        return try {
            val allDevices = bluetoothAdapter?.bondedDevices?.toList() ?: emptyList()
            // Filtrare strictă: afișează DOAR dispozitivul robotului Poro / Raspberry Pi
            allDevices.filter { dev ->
                val name = try { dev.name ?: "" } catch (e: Exception) { "" }
                name.contains("Poro", ignoreCase = true) ||
                name.contains("Raspberry", ignoreCase = true) ||
                name.contains("Pi", ignoreCase = true)
            }
        } catch (e: Exception) {
            emptyList()
        }
    }

    @SuppressLint("MissingPermission")
    suspend fun sendWifiCredentials(
        device: BluetoothDevice,
        ssid: String,
        pass: String
    ): WifiProvisionResult = withContext(Dispatchers.IO) {
        val deviceName = try { device.name ?: "Dispozitiv BT" } catch (e: Exception) { "Dispozitiv BT" }
        _status.value = "Se conectează la $deviceName..."
        var socket: BluetoothSocket? = null
        try {
            bluetoothAdapter?.cancelDiscovery()

            // Încercare 1: Conectare prin SPP UUID standard
            try {
                socket = device.createRfcommSocketToServiceRecord(SPP_UUID)
                socket.connect()
            } catch (e1: Exception) {
                // Încercare 2 (Fallback RFCOMM Canal 1): Soluție dedicată pentru Raspberry Pi BlueZ
                val method = device.javaClass.getMethod("createRfcommSocket", Int::class.javaPrimitiveType)
                socket = method.invoke(device, 1) as BluetoothSocket
                socket.connect()
            }

            _status.value = "Se trimit datele Wi-Fi..."
            val jsonPayload = gson.toJson(WifiCredentials(ssid, pass)) + "\n"
            socket.outputStream.write(jsonPayload.toByteArray(Charsets.UTF_8))
            socket.outputStream.flush()

            _status.value = "Se așteaptă adresa IP de la Poro..."
            
            val reader = socket.inputStream.bufferedReader(Charsets.UTF_8)
            var receivedIp: String? = null

            // Așteptăm până la 15 secunde răspunsul cu IP-ul de la Poro (timp necesar conectării la rețeaua Wi-Fi)
            val startTime = System.currentTimeMillis()
            while (System.currentTimeMillis() - startTime < 15000) {
                if (reader.ready()) {
                    val line = reader.readLine()
                    if (!line.isNullOrBlank()) {
                        // Regex pentru extragerea adresei IP (ex: 192.168.1.50)
                        val ipRegex = Regex("""\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b""")
                        val match = ipRegex.find(line)
                        if (match != null) {
                            receivedIp = match.value
                            break
                        }
                    }
                }
                delay(200)
            }

            return@withContext if (receivedIp != null) {
                _status.value = "Conectat! IP preluat: $receivedIp"
                try { socket.close() } catch (ignored: Exception) {}
                WifiProvisionResult(true, receivedIp, "IP preluat automat: $receivedIp")
            } else {
                _status.value = "Wi-Fi Trimis (IP netransmis în 15s)"
                try { socket.close() } catch (ignored: Exception) {}
                WifiProvisionResult(true, null, "Date trimise cu succes, dar IP-ul nu a fost returnat.")
            }
        } catch (e: Exception) {
            val errorMsg = "Eroare Conectare: ${e.localizedMessage ?: "Eșuat"}"
            _status.value = errorMsg
            try { socket?.close() } catch (ignored: IOException) {}
            return@withContext WifiProvisionResult(false, null, errorMsg)
        }
    }
}
