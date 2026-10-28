package com.example.myapplication

import android.app.Application
import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CutCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Cookie
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.vector.rememberVectorPainter
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.Locale
import kotlin.math.abs
import kotlin.math.sqrt

class PoroViewModel(application: Application) : AndroidViewModel(application) {
    private val prefs = application.getSharedPreferences("poro_prefs", Context.MODE_PRIVATE)

    val telemetryFlow = PoroApiClient.telemetryFlow
    val isOnline = PoroApiClient.isOnline

    var ipAddress by mutableStateOf(prefs.getString("saved_ip", "http://192.168.1.50:8000") ?: "http://192.168.1.50:8000")
        private set

    // Riot ID & TFT Monitor State
    var gameName by mutableStateOf(prefs.getString("riot_game_name", "") ?: "")
        private set
    var tagLine by mutableStateOf((prefs.getString("riot_tag_line", "") ?: "").removePrefix("#"))
        private set
    var regionHost by mutableStateOf(prefs.getString("riot_region_host", "europe.api.riotgames.com") ?: "europe.api.riotgames.com")
        private set
    var apiKey by mutableStateOf(prefs.getString("riot_api_key", "RGAPI-12345678-abcd-1234-abcd-1234567890ab") ?: "")
        private set
    var showRiotDialog by mutableStateOf(gameName.isBlank() || tagLine.isBlank() || regionHost.isBlank())
        private set

    // Poro-Snax Inventory Stock (Setat la 0 la prima deschidere)
    var snaxCount by mutableIntStateOf(
        if (!prefs.getBoolean("has_initialized_snax", false)) {
            prefs.edit().putInt("poro_snax_count", 0).putBoolean("has_initialized_snax", true).apply()
            0
        } else {
            prefs.getInt("poro_snax_count", 0)
        }
    )
        private set

    var tftStatusMessage by mutableStateOf("Monitorizare TFT inactivă")
        private set

    var chatMessage by mutableStateOf("")
        private set

    var wifiSsid by mutableStateOf("")
        private set
    var wifiPassword by mutableStateOf("")
        private set

    var gazeX by mutableFloatStateOf(0f)
        private set
    var gazeY by mutableFloatStateOf(0f)
        private set
        
    private var lastGazeTime = 0L

    init {
        PoroApiClient.setBaseUrl(ipAddress)
        viewModelScope.launch {
            PoroApiClient.startTelemetryPolling()
        }
        if (gameName.isNotBlank() && tagLine.isNotBlank() && regionHost.isNotBlank()) {
            startTftMonitoring()
        }
    }

    fun saveRiotCredentials(name: String, tag: String, region: String, key: String) {
        val cleanName = name.trim()
        val cleanTag = tag.trim().removePrefix("#")
        val cleanRegion = region.trim().lowercase().removePrefix("https://").removePrefix("http://").removeSuffix("/")

        if (cleanName != gameName || cleanTag != tagLine || cleanRegion != regionHost) {
            prefs.edit().remove("saved_puuid").remove("last_tft_match_id").apply()
        }

        gameName = cleanName
        tagLine = cleanTag
        regionHost = cleanRegion
        if (key.isNotBlank()) apiKey = key.trim()

        prefs.edit()
            .putString("riot_game_name", gameName)
            .putString("riot_tag_line", tagLine)
            .putString("riot_region_host", regionHost)
            .putString("riot_api_key", apiKey)
            .apply()

        showRiotDialog = false
        startTftMonitoring()
    }

    fun openRiotDialog() {
        showRiotDialog = true
    }

    fun dismissRiotDialog() {
        if (gameName.isNotBlank() && tagLine.isNotBlank() && regionHost.isNotBlank()) {
            showRiotDialog = false
        }
    }

    fun consumeSnax(): Boolean {
        if (snaxCount > 0) {
            snaxCount -= 1
            prefs.edit().putInt("poro_snax_count", snaxCount).apply()
            return true
        }
        return false
    }

    fun addSnax(amount: Int = 1) {
        snaxCount += amount
        prefs.edit().putInt("poro_snax_count", snaxCount).apply()
    }

    private fun startTftMonitoring() {
        viewModelScope.launch {
            var puuid = prefs.getString("saved_puuid", null)

            if (puuid == null) {
                tftStatusMessage = "Se caută contul Riot ($gameName#$tagLine - $regionHost)..."
                val result = RiotTftManager.getPuuidByRiotId(regionHost, gameName, tagLine, apiKey)
                
                when (result) {
                    is RiotResult.Success -> {
                        puuid = result.data
                        prefs.edit().putString("saved_puuid", puuid).apply()
                    }
                    is RiotResult.Error -> {
                        tftStatusMessage = result.message
                        return@launch
                    }
                }
            }

            tftStatusMessage = "Cont conectat ($regionHost)! Monitorizare meciuri TFT..."

            var lastMatchId = prefs.getString("last_tft_match_id", null)

            // La prima rulare, salvăm doar ultimul meci jucat fără recompense retroactive
            if (lastMatchId == null) {
                val initialMatchId = RiotTftManager.getLatestTftMatchId(regionHost, puuid, apiKey)
                if (initialMatchId != null) {
                    lastMatchId = initialMatchId
                    prefs.edit().putString("last_tft_match_id", lastMatchId).apply()
                }
            }

            // Loop de interogare periodică (la fiecare 60s)
            while (isActive) {
                val latestMatchId = RiotTftManager.getLatestTftMatchId(regionHost, puuid, apiKey)
                
                if (latestMatchId != null && latestMatchId != lastMatchId) {
                    // Meci nou găsit! Preluăm detaliile meciului
                    val matchDetails = RiotTftManager.getTftMatchDetails(regionHost, latestMatchId, apiKey)
                    val participant = matchDetails?.info?.participants?.find { it.puuid == puuid }

                    if (participant != null) {
                        val placement = participant.placement
                        if (placement in 1..4) {
                            addSnax(1)
                            tftStatusMessage = "Meci nou! Locul $placement (Top 4) - Recompensă: +1 Poro-Snax!"
                        } else {
                            tftStatusMessage = "Meci nou! Locul $placement - Nicio recompensă."
                        }
                    }

                    lastMatchId = latestMatchId
                    prefs.edit().putString("last_tft_match_id", lastMatchId).apply()
                }

                delay(60_000L)
            }
        }
    }

    fun updateWifiSsid(ssid: String) {
        wifiSsid = ssid
    }

    fun updateWifiPassword(pass: String) {
        wifiPassword = pass
    }

    fun sendWifiViaBluetooth(bluetoothManager: PoroBluetoothManager, device: android.bluetooth.BluetoothDevice) {
        if (wifiSsid.isNotBlank()) {
            viewModelScope.launch {
                bluetoothManager.sendWifiCredentials(device, wifiSsid, wifiPassword)
            }
        }
    }

    fun updateIpAddress(newIp: String) {
        ipAddress = newIp
        PoroApiClient.setBaseUrl(newIp)
        prefs.edit().putString("saved_ip", PoroApiClient.getBaseUrl()).apply()
    }

    fun saveIpAddress() {
        PoroApiClient.setBaseUrl(ipAddress)
        val formattedUrl = PoroApiClient.getBaseUrl()
        ipAddress = formattedUrl
        prefs.edit().putString("saved_ip", formattedUrl).apply()
    }

    fun updateChatMessage(msg: String) {
        chatMessage = msg
    }

    fun sendChatMessage() {
        if (chatMessage.isNotBlank()) {
            val msg = chatMessage
            chatMessage = ""
            viewModelScope.launch {
                PoroApiClient.sendChat(msg)
            }
        }
    }

    fun sendAction(action: String, param: String? = null) {
        viewModelScope.launch {
            PoroApiClient.sendAction(action, param)
        }
    }

    fun updateGaze(x: Float, y: Float) {
        gazeX = x
        gazeY = y
        val currentTime = System.currentTimeMillis()
        if ((currentTime - lastGazeTime) > 100) { // Throttle 100ms
            lastGazeTime = currentTime
            viewModelScope.launch {
                PoroApiClient.sendGaze(x, y)
            }
        }
    }
    
    fun resetGaze() {
        updateGaze(0f, 0f)
    }
}

// Freljord Theme Colors
val FreljordColors = darkColorScheme(
    primary = Color(0xFF00E5FF), // True Ice Cyan
    secondary = Color(0xFF82B1FF), // Frost Blue
    background = Color(0xFF080D14), // Deep Freezing Night
    surface = Color(0xFF1E1512), // Darkwood
    surfaceVariant = Color(0xFF2D1E16), // Lighter Wood
    onPrimary = Color(0xFF003333),
    onSecondary = Color(0xFF001133),
    onBackground = Color(0xFFE0F7FA), // Ice White
    onSurface = Color(0xFFE0F7FA),
    error = Color(0xFFFF5252)
)

// Jagged Ice/Wood Shapes
val FreljordShapes = Shapes(
    small = CutCornerShape(topStart = 8.dp, bottomEnd = 8.dp),
    medium = CutCornerShape(topStart = 16.dp, bottomEnd = 16.dp),
    large = CutCornerShape(topStart = 24.dp, bottomEnd = 24.dp)
)

class MainActivity : ComponentActivity() {
    private lateinit var sensorManager: PoroSensorManager
    private lateinit var bluetoothManager: PoroBluetoothManager
    private lateinit var bleProximityManager: PoroBleProximityManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        val scope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.Default)
        sensorManager = PoroSensorManager(this, scope)
        bluetoothManager = PoroBluetoothManager(this)
        bleProximityManager = PoroBleProximityManager(this)

        setContent {
            MaterialTheme(
                colorScheme = FreljordColors,
                shapes = FreljordShapes
            ) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    PoroApp(sensorManager, bluetoothManager, bleProximityManager)
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        sensorManager.startListening()
        bleProximityManager.startScan()
    }

    override fun onPause() {
        super.onPause()
        sensorManager.stopListening()
        bleProximityManager.stopScan()
    }
}

data class RiotRegionOption(val name: String, val host: String)

val RiotRegions = listOf(
    RiotRegionOption("Europe (EUNE, EUW, TR, RU)", "europe.api.riotgames.com"),
    RiotRegionOption("Americas (NA, BR, LAN, LAS)", "americas.api.riotgames.com"),
    RiotRegionOption("Asia (KR, JP)", "asia.api.riotgames.com"),
    RiotRegionOption("SEA / Oceania (OCE, PH, SG, TW)", "sea.api.riotgames.com")
)

@Composable
fun RiotIdSetupDialog(viewModel: PoroViewModel) {
    if (viewModel.showRiotDialog) {
        var tempName by remember { mutableStateOf(viewModel.gameName) }
        var tempTag by remember { mutableStateOf(viewModel.tagLine.removePrefix("#")) }
        var tempRegionHost by remember { mutableStateOf(viewModel.regionHost) }
        var tempKey by remember { mutableStateOf(viewModel.apiKey) }
        var showKeyInput by remember { mutableStateOf(false) }
        var errorMessage by remember { mutableStateOf("") }

        AlertDialog(
            onDismissRequest = { viewModel.dismissRiotDialog() },
            title = {
                Text("Configurare Riot ID (TFT)", fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
            },
            text = {
                Column {
                    OutlinedTextField(
                        value = tempName,
                        onValueChange = { tempName = it; errorMessage = "" },
                        label = { Text("Nume Jucător (ex: Summoner)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(8.dp))

                    OutlinedTextField(
                        value = tempTag,
                        onValueChange = { tempTag = it.removePrefix("#"); errorMessage = "" },
                        label = { Text("TagLine (ex: EUNE, 1234)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(12.dp))

                    Text("Regiune:", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary)
                    Spacer(modifier = Modifier.height(4.dp))

                    RiotRegions.forEach { option ->
                        val isSelected = tempRegionHost.equals(option.host, ignoreCase = true)
                        OutlinedButton(
                            onClick = { tempRegionHost = option.host },
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 2.dp),
                            colors = ButtonDefaults.outlinedButtonColors(
                                containerColor = if (isSelected) MaterialTheme.colorScheme.primary.copy(alpha = 0.2f) else Color.Transparent,
                                contentColor = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface
                            )
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Text(option.name, fontSize = 11.sp)
                                if (isSelected) Text("✓", fontWeight = FontWeight.Bold)
                            }
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("Opțiuni Avansate:", fontSize = 11.sp, color = Color.Gray)
                        TextButton(onClick = { showKeyInput = !showKeyInput }) {
                            Text(if (showKeyInput) "Ascunde API Key" else "Editează API Key", fontSize = 11.sp, color = MaterialTheme.colorScheme.secondary)
                        }
                    }

                    if (showKeyInput) {
                        OutlinedTextField(
                            value = tempKey,
                            onValueChange = { tempKey = it; errorMessage = "" },
                            label = { Text("Riot API Key (RGAPI-...)") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth()
                        )
                    }

                    if (errorMessage.isNotBlank()) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(errorMessage, color = MaterialTheme.colorScheme.error, fontSize = 12.sp)
                    }
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        val cleanTag = tempTag.trim().removePrefix("#")
                        if (tempName.trim().isBlank() || cleanTag.isBlank() || tempRegionHost.trim().isBlank()) {
                            errorMessage = "Numele, Tag-ul și Regiunea sunt obligatorii!"
                        } else {
                            viewModel.saveRiotCredentials(tempName, cleanTag, tempRegionHost, tempKey)
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary, contentColor = Color.Black)
                ) {
                    Text("Salvează și Monitorizează")
                }
            },
            dismissButton = {
                if (viewModel.gameName.isNotBlank() && viewModel.tagLine.isNotBlank()) {
                    TextButton(onClick = { viewModel.dismissRiotDialog() }) {
                        Text("Anulează")
                    }
                }
            }
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PoroApp(
    sensorManager: PoroSensorManager,
    bluetoothManager: PoroBluetoothManager,
    bleProximityManager: PoroBleProximityManager,
    viewModel: PoroViewModel = viewModel()
) {
    var selectedTab by remember { mutableIntStateOf(0) }
    val tabs = listOf("Poro-Snax", "Control & Console")

    RiotIdSetupDialog(viewModel)

    Box(modifier = Modifier.fillMaxSize()) {
        androidx.compose.foundation.Image(
            painter = androidx.compose.ui.res.painterResource(id = R.drawable.backround),
            contentDescription = "Background",
            contentScale = androidx.compose.ui.layout.ContentScale.Crop,
            modifier = Modifier.fillMaxSize()
        )

        Scaffold(
            containerColor = Color.Transparent,
            bottomBar = {
                NavigationBar(
                    containerColor = MaterialTheme.colorScheme.surface,
                    contentColor = MaterialTheme.colorScheme.primary
                ) {
                    tabs.forEachIndexed { index, title ->
                        NavigationBarItem(
                            selected = selectedTab == index,
                            onClick = { selectedTab = index },
                            icon = {
                                Icon(
                                    if (index == 0) Icons.Filled.Cookie else Icons.Filled.Dashboard,
                                    contentDescription = title
                                )
                            },
                            label = { Text(title) },
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = MaterialTheme.colorScheme.primary,
                                selectedTextColor = MaterialTheme.colorScheme.primary,
                                indicatorColor = MaterialTheme.colorScheme.surfaceVariant,
                                unselectedIconColor = Color.Gray,
                                unselectedTextColor = Color.Gray
                            )
                        )
                    }
                }
            }
        ) { paddingValues ->
            Box(modifier = Modifier.padding(paddingValues).fillMaxSize()) {
                if (selectedTab == 0) {
                    PoroSnaxTab(sensorManager, bleProximityManager, viewModel)
                } else {
                    ControlConsoleTab(sensorManager, bluetoothManager, bleProximityManager, viewModel)
                }
            }
        }
    }
}


class BiscuitState(
    x: Float,
    y: Float,
    val radius: Float = 75f
) {
    var x by mutableFloatStateOf(x)
    var y by mutableFloatStateOf(y)
    var vx = 0f
    var vy = 0f
    var isFlying by mutableStateOf(false)
    var flyingAlpha by mutableFloatStateOf(1f)
}

class StarParticle(
    var x: Float,
    var y: Float,
    var vx: Float,
    var vy: Float,
    var size: Float,
    var alpha: Float = 1f
)

@Composable
fun PoroSnaxTab(
    sensorManager: PoroSensorManager,
    bleProximityManager: PoroBleProximityManager,
    viewModel: PoroViewModel
) {
    val isHardwareNearby by sensorManager.isDeviceNearby.collectAsState()
    val bleState by bleProximityManager.state.collectAsState()
    val isNearby = isHardwareNearby || bleState.isNear

    val accelX by sensorManager.accelX.collectAsState()
    val accelY by sensorManager.accelY.collectAsState()

    val visibleSnaxTarget = viewModel.snaxCount.coerceAtMost(22)
    val biscuits = remember { mutableStateListOf<BiscuitState>() }

    LaunchedEffect(visibleSnaxTarget) {
        if (biscuits.size < visibleSnaxTarget) {
            val needed = visibleSnaxTarget - biscuits.size
            repeat(needed) {
                biscuits.add(
                    BiscuitState(
                        x = (120..380).random().toFloat(),
                        y = (150..300).random().toFloat()
                    )
                )
            }
        } else if (biscuits.size > visibleSnaxTarget) {
            val toRemove = biscuits.size - visibleSnaxTarget
            repeat(toRemove) {
                if (biscuits.isNotEmpty()) {
                    biscuits.removeAt(biscuits.lastIndex)
                }
            }
        }
    }
    
    val starParticles = remember { mutableStateListOf<StarParticle>() }
    var celebrationTimeLeft by remember { mutableFloatStateOf(0f) }
    var lastTossTimestamp by remember { mutableLongStateOf(0L) }

    var boxWidth by remember { mutableFloatStateOf(0f) }
    var boxHeight by remember { mutableFloatStateOf(0f) }
    val damping = 0.6f

    LaunchedEffect(Unit) {
        var lastTime = withFrameNanos { it }
        while (isActive) {
            val currentTime = withFrameNanos { it }
            val dt = (currentTime - lastTime) / 1_000_000_000f
            lastTime = currentTime

            if (dt > 0.1f) continue

            var rattleTriggered = false

            // Cronometru animație de sărbătoare
            if (celebrationTimeLeft > 0f) {
                celebrationTimeLeft = (celebrationTimeLeft - dt).coerceAtLeast(0f)
            }

            // Actualizare particule steluțe (mișcare netedă, durată ~3.2 secunde)
            val particleIterator = starParticles.iterator()
            while (particleIterator.hasNext()) {
                val p = particleIterator.next()
                p.x += p.vx * dt
                p.y += p.vy * dt
                p.vx *= 0.97f // Netezire mișcare (frecare lină cu aerul)
                p.vy *= 0.97f
                p.alpha -= dt * 0.30f // Fade out lin și mai lung
                if (p.alpha <= 0f) {
                    particleIterator.remove()
                }
            }

            biscuits.forEach { b ->
                if (b.isFlying) {
                    b.y += b.vy * dt
                    b.flyingAlpha = (b.flyingAlpha - dt * 1.5f).coerceAtLeast(0f)
                    return@forEach
                }

                b.vx += accelX * 180f * dt
                b.vy += accelY * 180f * dt

                b.x += b.vx * dt
                b.y += b.vy * dt

                // Ajustăm raza de coliziune efectivă la 82% pentru atingere vizuală perfectă
                val collisionRadius = b.radius * 0.82f
                val marginX = boxWidth * 0.12f
                val marginTop = boxHeight * 0.12f
                val marginBottom = boxHeight * 0.21f // Media aritmetică între 10% și 32% = 21%
                
                val minX = marginX + collisionRadius
                val maxX = boxWidth - marginX - collisionRadius
                val minY = marginTop + collisionRadius
                val maxY = boxHeight - marginBottom - collisionRadius

                if (b.x < minX) { 
                    b.x = minX
                    if (abs(b.vx) > 300f) rattleTriggered = true
                    b.vx = -b.vx * damping 
                }
                if (b.x > maxX && maxX > minX) { 
                    b.x = maxX
                    if (abs(b.vx) > 300f) rattleTriggered = true
                    b.vx = -b.vx * damping 
                }
                if (b.y < minY) { 
                    b.y = minY
                    if (abs(b.vy) > 300f) rattleTriggered = true
                    b.vy = -b.vy * damping 
                }
                if (b.y > maxY && maxY > minY) { 
                    b.y = maxY
                    if (abs(b.vy) > 300f) rattleTriggered = true
                    b.vy = -b.vy * damping 
                }
            }

            for (i in biscuits.indices) {
                for (j in i + 1 until biscuits.size) {
                    val b1 = biscuits[i]
                    val b2 = biscuits[j]
                    if (b1.isFlying || b2.isFlying) continue

                    val dx = b2.x - b1.x
                    val dy = b2.y - b1.y
                    val dist = sqrt(dx * dx + dy * dy)
                    val minDist = (b1.radius + b2.radius) * 0.82f

                    if (dist < minDist && dist > 0.01f) {
                        val overlap = minDist - dist
                        val nx = dx / dist
                        val ny = dy / dist

                        b1.x -= nx * overlap / 2
                        b1.y -= ny * overlap / 2
                        b2.x += nx * overlap / 2
                        b2.y += ny * overlap / 2

                        val kx = b1.vx - b2.vx
                        val ky = b1.vy - b2.vy
                        val p = 2f * (nx * kx + ny * ky) / 2f
                        b1.vx -= p * nx * 0.8f
                        b1.vy -= p * ny * 0.8f
                        b2.vx += p * nx * 0.8f
                        b2.vy += p * ny * 0.8f
                    }
                }
            }

            if (rattleTriggered) {
                sensorManager.triggerMicroVibration()
            }
        }
    }

    val coroutineScope = rememberCoroutineScope()

    val context = LocalContext.current

    DisposableEffect(isNearby) {
        sensorManager.onTossDetected = {
            val now = System.currentTimeMillis()
            // ARUNCĂM SNAX DOAR DACĂ TELEFONUL ESTE LÂNGĂ ROBOT (PROXIMITATE <= 1.0m) ȘI EXISTA SNAX-URI ÎN STOC!
            if (isNearby && now - lastTossTimestamp >= 5000L) {
                if (viewModel.snaxCount > 0) {
                    if (viewModel.consumeSnax()) {
                        lastTossTimestamp = now

                        // Asigură că avem un biscuit disponibil pentru aruncat
                        var b = biscuits.find { !it.isFlying }
                        if (b == null) {
                            biscuits.forEach { it.isFlying = false; it.flyingAlpha = 1f }
                            b = biscuits.firstOrNull()
                        }

                        if (b != null) {
                            b.isFlying = true
                            b.vy = -2500f
                            viewModel.sendAction("FEED_SNAX")

                            celebrationTimeLeft = 3.2f // Animație activă 3.2 secunde
                            starParticles.clear()

                            // Steluțele sar abia când Snax-ul este aproape la dimensiunea sa maximă (după 250ms)
                            coroutineScope.launch {
                                delay(250) // Așteaptă pop-ul rapid al Snax-ului
                                
                                val random = java.util.Random()
                                repeat(40) {
                                    val angle = random.nextFloat() * 2 * Math.PI.toFloat()
                                    val speed = (400..1500).random().toFloat()
                                    starParticles.add(
                                        StarParticle(
                                            x = boxWidth / 2f,
                                            y = boxHeight / 2f,
                                            vx = kotlin.math.cos(angle) * speed,
                                            vy = kotlin.math.sin(angle) * speed,
                                            size = (20..60).random().toFloat()
                                        )
                                    )
                                }

                                delay(2250)
                                b.isFlying = false
                                b.flyingAlpha = 1f
                                b.x = boxWidth / 2f
                                b.y = boxHeight / 2f
                                b.vx = 0f
                                b.vy = 0f
                            }
                        }
                    }
                } else {
                    android.widget.Toast.makeText(
                        context,
                        "Nu mai ai Poro-Snax! Joacă TFT și obține Top 4 pentru a câștiga Poro-Snax.",
                        android.widget.Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
        onDispose {
            sensorManager.onTossDetected = null
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .padding(top = 16.dp, start = 16.dp, end = 16.dp, bottom = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        val snaxPainter = androidx.compose.ui.res.painterResource(id = R.drawable.poro_snax)
        val boxPainter = androidx.compose.ui.res.painterResource(id = R.drawable.poro_box)
        val starPainter = androidx.compose.ui.res.painterResource(id = R.drawable.star)

        Card(
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f)),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.4f)),
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 8.dp)
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text("Stoc Poro-Snax: ", fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onSurface)
                Text("${viewModel.snaxCount}", fontWeight = FontWeight.ExtraBold, fontSize = 18.sp, color = MaterialTheme.colorScheme.primary)
                Spacer(modifier = Modifier.weight(1f))
                TextButton(onClick = { viewModel.openRiotDialog() }) {
                    Text("Configurare Riot ID", fontSize = 12.sp, color = MaterialTheme.colorScheme.secondary)
                }
            }
        }

        BoxWithConstraints(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            boxWidth = maxWidth.value * androidx.compose.ui.platform.LocalDensity.current.density
            boxHeight = maxHeight.value * androidx.compose.ui.platform.LocalDensity.current.density

            Canvas(modifier = Modifier.fillMaxSize()) {
                val boxRectSize = Size(size.width, size.height)
                
                // Inset-ăm fundalul interior maro astfel încât să stea strict în spatele cutiei
                val insetX = size.width * 0.05f
                val insetY = size.height * 0.05f
                val interiorSize = Size(size.width - insetX * 2, size.height - insetY * 2)

                // Fundal interior Maro (Darkwood) în spatele biscuiților
                translate(left = insetX, top = insetY) {
                    drawRoundRect(
                        color = Color(0xFF2C1E16), // Maro (Dark Wood)
                        size = interiorSize,
                        cornerRadius = CornerRadius(24f)
                    )
                }

                // Biscuits (Layer Spate / În cutie)
                biscuits.forEach { b ->
                    if (b.y > -300f) {
                        translate(left = b.x - b.radius, top = b.y - b.radius) {
                            with(snaxPainter) {
                                draw(
                                    size = Size(b.radius * 2, b.radius * 2),
                                    alpha = b.flyingAlpha
                                )
                            }
                        }
                    }
                }

                // Cereal Box Frame (Layer Față - imaginea de fundal 'backround.jpg' este vizibilă în jurul cutiei)
                with(boxPainter) {
                    draw(
                        size = boxRectSize
                    )
                }

                // Explozie de Steluțe (imaginea 'star.png') și Poro-Snax Uriaș (Steluțele sunt desenate ÎN SPATELE Snax-ului)
                if (celebrationTimeLeft > 0f) {
                    val elapsedTime = 3.2f - celebrationTimeLeft // de la 0.0s la 3.2s
                    
                    // Creștere foarte rapidă (Pop!): crește de la 120px la 780px în primele 0.30 secunde
                    val growthProgress = (elapsedTime / 0.30f).coerceIn(0f, 1f)
                    val smoothFactor = FastOutSlowInEasing.transform(growthProgress)
                    val giantSnaxSize = 120f + (smoothFactor * 660f) // Crește rapid până la 780px uriaș!

                    // Opacitate: vizibilitate 100% pe parcursul animației, face fade-out lin în ultimele 0.6 secunde
                    val snaxAlpha = if (celebrationTimeLeft > 0.6f) 1.0f else (celebrationTimeLeft / 0.6f)

                    // 1. DESENĂM STELUȚELE MAI ÎNTÂI (Layer Spate - folosind imaginea 'star.png' din drawable)
                    starParticles.forEach { p ->
                        translate(left = p.x - p.size, top = p.y - p.size) {
                            with(starPainter) {
                                draw(
                                    size = Size(p.size * 2, p.size * 2),
                                    alpha = p.alpha.coerceIn(0f, 1f)
                                )
                            }
                        }
                    }

                    // 2. DESENĂM PORO-SNAX-UL URIAȘ DUPĂ (Layer Față - acoperă centrul steluțelor)
                    translate(
                        left = size.width / 2f - giantSnaxSize / 2f,
                        top = size.height / 2f - giantSnaxSize / 2f
                    ) {
                        with(snaxPainter) {
                            draw(
                                size = Size(giantSnaxSize, giantSnaxSize),
                                alpha = snaxAlpha
                            )
                        }
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))
        Text(
            text = "Apropie telefonul și înclină-l brusc pentru a-i arunca un Snax",
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
            fontSize = 15.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(bottom = 16.dp)
        )
    }
}

@android.annotation.SuppressLint("MissingPermission")
fun getNearbyWifiNetworks(context: android.content.Context): List<String> {
    return try {
        val wifiManager = context.applicationContext.getSystemService(android.content.Context.WIFI_SERVICE) as? android.net.wifi.WifiManager
        val connectionInfo = wifiManager?.connectionInfo
        val currentSsid = connectionInfo?.ssid?.replace("\"", "")?.trim() ?: ""

        val scanResults = try { wifiManager?.scanResults ?: emptyList() } catch (e: Exception) { emptyList() }
        val scannedSsids = scanResults
            .map { it.SSID.replace("\"", "").trim() }
            .filter { it.isNotBlank() && !it.contains("<unknown ssid>", ignoreCase = true) }
            .distinct()

        val combined = mutableListOf<String>()
        if (currentSsid.isNotBlank() && !currentSsid.contains("<unknown ssid>", ignoreCase = true)) {
            combined.add(currentSsid)
        }
        scannedSsids.forEach {
            if (!combined.contains(it)) {
                combined.add(it)
            }
        }
        combined
    } catch (e: Exception) {
        emptyList()
    }
}

@android.annotation.SuppressLint("MissingPermission")
@Composable
fun ControlConsoleTab(
    sensorManager: PoroSensorManager,
    bluetoothManager: PoroBluetoothManager,
    bleProximityManager: PoroBleProximityManager,
    viewModel: PoroViewModel
) {
    val isOnline by viewModel.isOnline.collectAsState()
    val telemetry by viewModel.telemetryFlow.collectAsState()
    val isHardwareNearby by sensorManager.isDeviceNearby.collectAsState()
    val bleState by bleProximityManager.state.collectAsState()
    val gForce by sensorManager.lastGForce.collectAsState()
    
    val cardBorder = BorderStroke(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.3f))

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .padding(top = 16.dp, start = 16.dp, end = 16.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item { Spacer(modifier = Modifier.height(8.dp)) }

        // 1. TERMINAL CHAT LLM (Sus de tot)
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                border = cardBorder
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Terminal Chat LLM", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary, fontFamily = FontFamily.Serif)
                    Spacer(modifier = Modifier.height(16.dp))

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        OutlinedTextField(
                            value = viewModel.chatMessage,
                            onValueChange = { viewModel.updateChatMessage(it) },
                            modifier = Modifier.weight(1f),
                            label = { Text("Mesaj către Poro...", color = MaterialTheme.colorScheme.secondary) },
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = MaterialTheme.colorScheme.primary,
                                unfocusedBorderColor = MaterialTheme.colorScheme.secondary
                            )
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        IconButton(
                            onClick = { viewModel.sendChatMessage() },
                            modifier = Modifier
                                .size(48.dp)
                                .clip(CutCornerShape(12.dp))
                                .background(MaterialTheme.colorScheme.primary)
                        ) {
                            Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send", tint = Color.Black)
                        }
                    }
                }
            }
        }

        // MONITORIZARE TFT & RIOT GAMES
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                border = cardBorder
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("Monitorizare TFT (Riot Games)", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary, fontFamily = FontFamily.Serif)
                        IconButton(onClick = { viewModel.openRiotDialog() }) {
                            Icon(Icons.Default.Refresh, contentDescription = "Edit Riot ID", tint = MaterialTheme.colorScheme.primary)
                        }
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    Text("Cont Riot Configurat: ${if (viewModel.gameName.isNotBlank()) "${viewModel.gameName}#${viewModel.tagLine}" else "Neconfigurat"}", fontWeight = FontWeight.Bold)
                    Spacer(modifier = Modifier.height(4.dp))
                    Text("Stoc Poro-Snax: ${viewModel.snaxCount}", fontSize = 16.sp, fontWeight = FontWeight.ExtraBold, color = MaterialTheme.colorScheme.primary)
                    Spacer(modifier = Modifier.height(4.dp))
                    Text("Status TFT: ${viewModel.tftStatusMessage}", fontSize = 12.sp, color = MaterialTheme.colorScheme.secondary)
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    OutlinedButton(
                        onClick = { viewModel.openRiotDialog() },
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("Modifică Riot ID")
                    }
                }
            }
        }

        // 2. ACȚIUNI RAPIDE (cu buton Mute)
        item {
            var isMuted by remember { mutableStateOf(false) }

            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                border = cardBorder
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Acțiuni Rapide", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary, fontFamily = FontFamily.Serif)
                    Spacer(modifier = Modifier.height(16.dp))

                    Row(
                        horizontalArrangement = Arrangement.SpaceEvenly,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        OutlinedButton(
                            onClick = { viewModel.sendAction("BLEP") },
                            modifier = Modifier.padding(2.dp)
                        ) { Text("👅 Blep", fontSize = 12.sp) }
                        
                        OutlinedButton(
                            onClick = { viewModel.sendAction("WAKE") },
                            modifier = Modifier.padding(2.dp)
                        ) { Text("☀️ Wake", fontSize = 12.sp) }

                        OutlinedButton(
                            onClick = { viewModel.sendAction("SLEEP") },
                            modifier = Modifier.padding(2.dp)
                        ) { Text("🌙 Sleep", fontSize = 12.sp) }

                        Button(
                            onClick = {
                                isMuted = !isMuted
                                viewModel.sendAction(if (isMuted) "MUTE" else "UNMUTE")
                            },
                            modifier = Modifier.padding(2.dp),
                            colors = ButtonDefaults.buttonColors(
                                containerColor = if (isMuted) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                                contentColor = if (isMuted) Color.White else Color.Black
                            )
                        ) {
                            Text(if (isMuted) "🔇 Muted" else "🔊 Mute", fontSize = 12.sp)
                        }
                    }
                }
            }
        }

        // 3. CONTROL EMOȚII & PRIVIRE
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                border = cardBorder
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Control Emoții & Privire", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary, fontFamily = FontFamily.Serif)
                    Spacer(modifier = Modifier.height(16.dp))

                    val emotions = listOf("Normal", "Heart", "Star", "Sleepy", "Dead", "Dizzy")
                    emotions.chunked(3).forEach { rowItems ->
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceEvenly
                        ) {
                            rowItems.forEach { emotion ->
                                OutlinedButton(
                                    onClick = { viewModel.sendAction("SET_EMOTION", emotion.lowercase()) },
                                    modifier = Modifier.padding(2.dp),
                                    colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.onSurface)
                                ) {
                                    Text(emotion, fontSize = 12.sp)
                                }
                            }
                        }
                    }

                    Spacer(modifier = Modifier.height(16.dp))
                    
                    Text("Joystick Privire (X: ${String.format(Locale.US, "%.2f", viewModel.gazeX)} | Y: ${String.format(Locale.US, "%.2f", viewModel.gazeY)})", color = MaterialTheme.colorScheme.secondary)
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    Box(
                        modifier = Modifier.fillMaxWidth(),
                        contentAlignment = Alignment.Center
                    ) {
                        Box(
                            modifier = Modifier
                                .size(210.dp)
                                .clip(CircleShape)
                                .background(Color(0xFF0A0F14))
                                .border(
                                    BorderStroke(2.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.6f)),
                                    CircleShape
                                )
                                .pointerInput(Unit) {
                                    detectDragGestures(
                                        onDragEnd = { viewModel.resetGaze() },
                                        onDragCancel = { viewModel.resetGaze() }
                                    ) { change, _ ->
                                        change.consume()
                                        val w = size.width.toFloat()
                                        val h = size.height.toFloat()
                                        val center = Offset(w / 2f, h / 2f)
                                        val pos = change.position
                                        
                                        val rawX = (pos.x - center.x) / (w / 2f)
                                        val rawY = (pos.y - center.y) / (h / 2f)
                                        val dist = sqrt(rawX * rawX + rawY * rawY)
                                        
                                        val nx = if (dist > 1f) rawX / dist else rawX
                                        val ny = if (dist > 1f) rawY / dist else rawY
                                        
                                        viewModel.updateGaze(nx, ny)
                                    }
                                },
                            contentAlignment = Alignment.Center
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(16.dp)
                                    .clip(CircleShape)
                                    .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.2f))
                            )
                            Box(
                                modifier = Modifier
                                    .offset(
                                        x = (viewModel.gazeX * 80).dp,
                                        y = (viewModel.gazeY * 80).dp
                                    )
                                    .size(36.dp)
                                    .clip(CircleShape)
                                    .background(MaterialTheme.colorScheme.primary)
                                    .border(
                                        BorderStroke(1.dp, Color.White.copy(alpha = 0.8f)),
                                        CircleShape
                                    )
                            )
                        }
                    }
                }
            }
        }

        // 4. CONEXIUNE PORO (IP Setup)
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                border = cardBorder
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Conexiune Freljord", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary, fontFamily = FontFamily.Serif)
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            modifier = Modifier
                                .size(12.dp)
                                .clip(CircleShape)
                                .background(if (isOnline) MaterialTheme.colorScheme.primary else Color.Red)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(if (isOnline) "Online" else "Offline", fontWeight = FontWeight.Bold)
                        
                        Spacer(modifier = Modifier.weight(1f))
                        
                        Text("Batt: ${if (telemetry?.battery_ok == true) "OK" else "LOW"}")
                    }
                    
                    Spacer(modifier = Modifier.height(16.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        OutlinedTextField(
                            value = viewModel.ipAddress,
                            onValueChange = { viewModel.updateIpAddress(it) },
                            modifier = Modifier.weight(1f),
                            label = { Text("Adresă IP", color = MaterialTheme.colorScheme.secondary) },
                            singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = MaterialTheme.colorScheme.primary,
                                unfocusedBorderColor = MaterialTheme.colorScheme.secondary
                            )
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Button(
                            onClick = { viewModel.saveIpAddress() },
                            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary, contentColor = Color.Black)
                        ) {
                            Text("Save")
                        }
                    }
                }
            }
        }

        // 5. CONFIGURARE WI-FI (BLUETOOTH)
        item {
            val context = LocalContext.current
            val btStatus by bluetoothManager.status.collectAsState()
            var poroDevices by remember { mutableStateOf(bluetoothManager.getPoroDevices()) }
            val poroDevice = poroDevices.firstOrNull()
            var isPasswordVisible by remember { mutableStateOf(false) }
            var nearbyWifiList by remember { mutableStateOf(getNearbyWifiNetworks(context)) }

            LaunchedEffect(nearbyWifiList) {
                if (viewModel.wifiSsid.isBlank() && nearbyWifiList.isNotEmpty()) {
                    viewModel.updateWifiSsid(nearbyWifiList.first())
                }
            }

            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                border = cardBorder
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Configurare Wi-Fi (Bluetooth)", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary, fontFamily = FontFamily.Serif)
                    Spacer(modifier = Modifier.height(8.dp))
                    Text("Trimite noile date Wi-Fi către robot prin Bluetooth.", fontSize = 12.sp, color = MaterialTheme.colorScheme.secondary)
                    Spacer(modifier = Modifier.height(12.dp))

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            modifier = Modifier
                                .size(10.dp)
                                .clip(CircleShape)
                                .background(if (poroDevice != null) MaterialTheme.colorScheme.primary else Color.Red)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = if (poroDevice != null) "Status Bluetooth: Conectat" else "Status Bluetooth: Deconectat",
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Bold,
                            color = if (poroDevice != null) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error
                        )
                        Spacer(modifier = Modifier.weight(1f))
                        IconButton(onClick = { poroDevices = bluetoothManager.getPoroDevices() }) {
                            Icon(Icons.Default.Refresh, contentDescription = "Refresh BT", tint = MaterialTheme.colorScheme.primary)
                        }
                    }

                    Spacer(modifier = Modifier.height(14.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("Alege Rețeaua Wi-Fi:", fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                        IconButton(onClick = { nearbyWifiList = getNearbyWifiNetworks(context) }) {
                            Icon(Icons.Default.Refresh, contentDescription = "Scanează Wi-Fi", tint = MaterialTheme.colorScheme.primary)
                        }
                    }

                    if (nearbyWifiList.isNotEmpty()) {
                        LazyRow(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier.padding(vertical = 4.dp)
                        ) {
                            items(nearbyWifiList) { ssid ->
                                val isSelected = viewModel.wifiSsid == ssid
                                FilterChip(
                                    selected = isSelected,
                                    onClick = { viewModel.updateWifiSsid(ssid) },
                                    label = { Text(ssid, fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.25f),
                                        selectedLabelColor = MaterialTheme.colorScheme.primary
                                    )
                                )
                            }
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                    }

                    OutlinedTextField(
                        value = viewModel.wifiSsid,
                        onValueChange = { viewModel.updateWifiSsid(it) },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Nume Rețea Selectată (SSID)", color = MaterialTheme.colorScheme.secondary) },
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = MaterialTheme.colorScheme.primary,
                            unfocusedBorderColor = MaterialTheme.colorScheme.secondary
                        )
                    )

                    Spacer(modifier = Modifier.height(8.dp))

                    OutlinedTextField(
                        value = viewModel.wifiPassword,
                        onValueChange = { viewModel.updateWifiPassword(it) },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Parolă Wi-Fi", color = MaterialTheme.colorScheme.secondary) },
                        singleLine = true,
                        visualTransformation = if (isPasswordVisible) VisualTransformation.None else PasswordVisualTransformation(),
                        trailingIcon = {
                            IconButton(onClick = { isPasswordVisible = !isPasswordVisible }) {
                                Icon(
                                    imageVector = if (isPasswordVisible) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                    contentDescription = "Toggle Password"
                                )
                            }
                        },
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = MaterialTheme.colorScheme.primary,
                            unfocusedBorderColor = MaterialTheme.colorScheme.secondary
                        )
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    Button(
                        onClick = {
                            poroDevice?.let { dev ->
                                viewModel.sendWifiViaBluetooth(bluetoothManager, dev)
                            }
                        },
                        enabled = poroDevice != null && viewModel.wifiSsid.isNotBlank(),
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary, contentColor = Color.Black)
                    ) {
                        Text("Trimite Configurația Wi-Fi")
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    Text("Status Trimitere: $btStatus", fontSize = 12.sp, color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
                }
            }
        }

        // 6. TELEMETRIE PORO (Jos de tot)
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                border = cardBorder
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Telemetrie Poro", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary, fontFamily = FontFamily.Serif)
                    Spacer(modifier = Modifier.height(16.dp))

                    Text("Status AI: ${telemetry?.status ?: "NECUNOSCUT"}")
                    Spacer(modifier = Modifier.height(4.dp))
                    Text("Ultimul text: ${telemetry?.last_text ?: "..."}")
                    Spacer(modifier = Modifier.height(4.dp))
                    Text("BNO Roll: ${telemetry?.bno?.roll ?: 0f}")
                    Text("BNO Pitch: ${telemetry?.bno?.pitch ?: 0f}")
                    Text("Alertă Scuturare: ${telemetry?.bno?.shaken ?: false}", color = if (telemetry?.bno?.shaken == true) MaterialTheme.colorScheme.error else Color.Unspecified)
                    Spacer(modifier = Modifier.height(8.dp))
                    HorizontalDivider(color = MaterialTheme.colorScheme.primary.copy(alpha = 0.3f))
                    Spacer(modifier = Modifier.height(8.dp))
                    Text("Senzori Telefon & BLE Proximitate", fontWeight = FontWeight.Bold)
                    Text("Proximitate HW (Senzor): $isHardwareNearby")
                    Text("BLE Proximitate Status: ${bleState.status}", fontWeight = FontWeight.SemiBold, color = if (bleState.isNear) MaterialTheme.colorScheme.primary else Color.Gray)
                    Text("BLE Distanță Estimată: ${if (bleState.distanceMeters >= 0) String.format(Locale.US, "%.2f m", bleState.distanceMeters) else "Incertă / Necunoscută"}")
                    Text("BLE RSSI Netezit: ${String.format(Locale.US, "%.1f dBm", bleState.smoothedRssi)} (Raw: ${bleState.rssi} dBm)")
                    Text("Forță-G Curentă: ${String.format(Locale.US, "%.2f", gForce)}g")
                }
            }
        }

        item { Spacer(modifier = Modifier.height(32.dp)) }
    }
}
