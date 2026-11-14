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
            // Filtrare extinsă: returnează toate dispozitivele dacă nu e găsit niciunul clar
            val poroDevices = allDevices.filter { dev ->
                val name = try { dev.name ?: "" } catch (e: Exception) { "" }
                name.contains("Poro", ignoreCase = true) ||
                name.contains("Raspberry", ignoreCase = true) ||
                name.contains("Pi", ignoreCase = true) ||
                name.contains("ubuntu", ignoreCase = true) ||
                name.contains("debian", ignoreCase = true)
            }
            // Dacă filtrul este prea restrictiv, arată toate dispozitivele BT împerecheate pentru a permite utilizatorului să selecteze manual
            if (poroDevices.isEmpty()) allDevices else poroDevices
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
        android.util.Log.d("PoroBT", "Încercare conectare la: $deviceName (${device.address})")
        var socket: BluetoothSocket? = null
        try {
            bluetoothAdapter?.cancelDiscovery()

            // Încercare 1: Conectare prin SPP UUID standard
            try {
                android.util.Log.d("PoroBT", "Metodă 1: Conectare SPP standard...")
                socket = device.createRfcommSocketToServiceRecord(SPP_UUID)
                socket.connect()
                android.util.Log.d("PoroBT", "Conectat prin SPP standard.")
            } catch (e1: Exception) {
                android.util.Log.w("PoroBT", "Metodă 1 eșuată: ${e1.message}. Încercare fallback RFCOMM canal 1...")
                // Încercare 2 (Fallback RFCOMM Canal 1): Soluție dedicată pentru Raspberry Pi BlueZ
                val method = device.javaClass.getMethod("createRfcommSocket", Int::class.javaPrimitiveType)
                socket = method.invoke(device, 1) as BluetoothSocket
                socket.connect()
                android.util.Log.d("PoroBT", "Conectat prin fallback RFCOMM canal 1.")
            }

            _status.value = "Se trimit datele Wi-Fi..."
            val jsonPayload = gson.toJson(WifiCredentials(ssid, pass)) + "\n"
            android.util.Log.d("PoroBT", "Trimit payload: $jsonPayload")
            socket.outputStream.write(jsonPayload.toByteArray(Charsets.UTF_8))
            socket.outputStream.flush()

            _status.value = "Se așteaptă adresa IP de la Poro..."
            android.util.Log.d("PoroBT", "Date trimise. Aștept răspuns de la Poro (timeout 45 secunde)...")
            
            val reader = socket.inputStream.bufferedReader(Charsets.UTF_8)
            var receivedIp: String? = null
            var receivedError = false

            // Așteptăm până la 45 secunde răspunsul cu IP-ul de la Poro
            val startTime = System.currentTimeMillis()
            while (System.currentTimeMillis() - startTime < 45000) {
                try {
                    if (reader.ready()) {
                        val line = reader.readLine()
                        if (!line.isNullOrBlank()) {
                            android.util.Log.d("PoroBT", "Linie primită: $line")
                            
                            if (line.contains("ERROR_NO_IP")) {
                                receivedError = true
                                android.util.Log.w("PoroBT", "Robotul a returnat ERROR_NO_IP.")
                                break
                            }

                            // Regex pentru extragerea adresei IP (ex: 192.168.1.50)
                            val ipRegex = Regex("""\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b""")
                            val match = ipRegex.find(line)
                            if (match != null) {
                                receivedIp = match.value
                                android.util.Log.d("PoroBT", "IP extras cu succes: $receivedIp")
                                break
                            }
                        }
                    }
                } catch (e: Exception) {
                    android.util.Log.w("PoroBT", "Excepție în timpul citirii (poate reset by peer): ${e.message}")
                    // Nu ieșim direct cu eroare totală dacă am apucat să citim IP-ul în iterații anterioare
                    break
                }
                delay(200)
            }

            return@withContext if (receivedIp != null) {
                _status.value = "Conectat! IP preluat: $receivedIp"
                try { socket.close() } catch (ignored: Exception) {}
                android.util.Log.d("PoroBT", "Flux încheiat cu succes. IP: $receivedIp")
                WifiProvisionResult(true, receivedIp, "IP preluat automat: $receivedIp")
            } else if (receivedError) {
                _status.value = "Eroare: Robotul nu s-a putut conecta (parolă incorectă sau rețea indisponibilă)."
                try { socket.close() } catch (ignored: Exception) {}
                android.util.Log.e("PoroBT", "Eroare Wi-Fi raportată de robot (ERROR_NO_IP).")
                WifiProvisionResult(false, null, "Eroare: Robotul nu a primit IP de la router.")
            } else {
                _status.value = "Eroare: Timeout 45s fără răspuns."
                try { socket.close() } catch (ignored: Exception) {}
                android.util.Log.e("PoroBT", "Timeout la așteptarea IP-ului de la robot.")
                WifiProvisionResult(false, null, "Timeout: Nu s-a primit IP-ul în 45 de secunde.")
            }
        } catch (e: Exception) {
            val errorMsg = "Eroare Conectare: ${e.localizedMessage ?: "Eșuat"}\nDacă socketul refuză să se deschidă, te rugăm să uiți (unpair) dispozitivul Bluetooth din setările Android și să-l re-împerechezi."
            _status.value = "Eroare Conectare BT. Re-împerechează dispozitivul."
            android.util.Log.e("PoroBT", "Eroare fatală BT: $errorMsg", e)
            try { socket?.close() } catch (ignored: IOException) {}
            return@withContext WifiProvisionResult(false, null, errorMsg)
        }
    }
}
