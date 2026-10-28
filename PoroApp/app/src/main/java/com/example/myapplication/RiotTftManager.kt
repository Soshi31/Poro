package com.example.myapplication

import com.google.gson.Gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

data class RiotAccountResponse(
    val puuid: String,
    val gameName: String,
    val tagLine: String
)

data class SummonerResponse(
    val profileIconId: Int,
    val summonerLevel: Int
)

data class TftParticipant(
    val puuid: String,
    val placement: Int
)

data class TftMatchInfo(
    val participants: List<TftParticipant>
)

data class TftMatchResponse(
    val info: TftMatchInfo?
)

sealed class RiotResult<out T> {
    data class Success<out T>(val data: T) : RiotResult<T>()
    data class Error(val code: Int, val message: String) : RiotResult<Nothing>()
}

object RiotTftManager {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    private val gson = Gson()

    private fun formatHost(rawHost: String): String {
        val cleanHost = rawHost.trim().lowercase()
            .removePrefix("https://")
            .removePrefix("http://")
            .removeSuffix("/")
        return "https://$cleanHost"
    }

    suspend fun getPuuidByRiotId(regionHost: String, gameName: String, tagLine: String, apiKey: String): RiotResult<String> = withContext(Dispatchers.IO) {
        try {
            val encodedName = URLEncoder.encode(gameName.trim(), "UTF-8")
            val cleanTag = tagLine.trim().removePrefix("#")
            val encodedTag = URLEncoder.encode(cleanTag, "UTF-8")
            val host = formatHost(regionHost)
            val url = "$host/riot/account/v1/accounts/by-riot-id/$encodedName/$encodedTag"

            val request = Request.Builder()
                .url(url)
                .addHeader("X-Riot-Token", apiKey.trim())
                .get()
                .build()

            client.newCall(request).execute().use { response ->
                when (response.code) {
                    200 -> {
                        val body = response.body?.string()
                        if (body != null) {
                            val account = gson.fromJson(body, RiotAccountResponse::class.java)
                            return@withContext RiotResult.Success(account.puuid)
                        } else {
                            return@withContext RiotResult.Error(500, "Răspuns gol de la Riot API.")
                        }
                    }
                    401, 403 -> {
                        return@withContext RiotResult.Error(
                            response.code,
                            "API Key Riot invalid/expirat (HTTP ${response.code}). Obține o cheie nouă de pe developer.riotgames.com."
                        )
                    }
                    404 -> {
                        return@withContext RiotResult.Error(
                            404,
                            "Contul $gameName#$cleanTag nu a fost găsit pe $regionHost."
                        )
                    }
                    429 -> {
                        return@withContext RiotResult.Error(
                            429,
                            "Riot API Rate Limit depășit. Reîncearcă în câteva minute."
                        )
                    }
                    else -> {
                        return@withContext RiotResult.Error(
                            response.code,
                            "Eroare Riot API (HTTP ${response.code})."
                        )
                    }
                }
            }
        } catch (e: Exception) {
            return@withContext RiotResult.Error(0, "Eroare rețea/conexiune: ${e.localizedMessage ?: "Necunoscută"}")
        }
    }

    suspend fun getSummonerProfileIconId(regionHost: String, puuid: String, apiKey: String, tagLine: String = ""): Int? = withContext(Dispatchers.IO) {
        val platforms = mutableListOf<String>()
        val tag = tagLine.trim().uppercase().removePrefix("#")

        // Interogare prioritară pe baza TagLine-ului (ex: EUW, EUNE, NA, KR, TR, RU etc.)
        when {
            tag.contains("EUW") -> platforms.add("https://euw1.api.riotgames.com")
            tag.contains("EUN") || tag.contains("EUNE") -> platforms.add("https://eun1.api.riotgames.com")
            tag.contains("NA") -> platforms.add("https://na1.api.riotgames.com")
            tag.contains("KR") -> platforms.add("https://kr.api.riotgames.com")
            tag.contains("JP") -> platforms.add("https://jp1.api.riotgames.com")
            tag.contains("TR") -> platforms.add("https://tr1.api.riotgames.com")
            tag.contains("RU") -> platforms.add("https://ru.api.riotgames.com")
            tag.contains("OCE") || tag.contains("OC") -> platforms.add("https://oc1.api.riotgames.com")
            tag.contains("BR") -> platforms.add("https://br1.api.riotgames.com")
            tag.contains("LAS") -> platforms.add("https://la2.api.riotgames.com")
            tag.contains("LAN") -> platforms.add("https://la1.api.riotgames.com")
        }

        // Adăugăm serverele din regiunea macro ca fallback în caz că TagLine-ul este un număr/alt text
        if (regionHost.contains("europe", ignoreCase = true)) {
            if (!platforms.contains("https://eun1.api.riotgames.com")) platforms.add("https://eun1.api.riotgames.com")
            if (!platforms.contains("https://euw1.api.riotgames.com")) platforms.add("https://euw1.api.riotgames.com")
            if (!platforms.contains("https://tr1.api.riotgames.com")) platforms.add("https://tr1.api.riotgames.com")
            if (!platforms.contains("https://ru.api.riotgames.com")) platforms.add("https://ru.api.riotgames.com")
        } else if (regionHost.contains("americas", ignoreCase = true)) {
            if (!platforms.contains("https://na1.api.riotgames.com")) platforms.add("https://na1.api.riotgames.com")
            if (!platforms.contains("https://br1.api.riotgames.com")) platforms.add("https://br1.api.riotgames.com")
            if (!platforms.contains("https://la1.api.riotgames.com")) platforms.add("https://la1.api.riotgames.com")
            if (!platforms.contains("https://la2.api.riotgames.com")) platforms.add("https://la2.api.riotgames.com")
        } else if (regionHost.contains("asia", ignoreCase = true)) {
            if (!platforms.contains("https://kr.api.riotgames.com")) platforms.add("https://kr.api.riotgames.com")
            if (!platforms.contains("https://jp1.api.riotgames.com")) platforms.add("https://jp1.api.riotgames.com")
        } else if (regionHost.contains("sea", ignoreCase = true)) {
            if (!platforms.contains("https://oc1.api.riotgames.com")) platforms.add("https://oc1.api.riotgames.com")
            if (!platforms.contains("https://ph2.api.riotgames.com")) platforms.add("https://ph2.api.riotgames.com")
            if (!platforms.contains("https://sg2.api.riotgames.com")) platforms.add("https://sg2.api.riotgames.com")
        }

        // Verificăm fiecare server regional până găsim pictograma reală de profil a contului
        for (platformHost in platforms) {
            try {
                val url = "$platformHost/lol/summoner/v4/summoners/by-puuid/$puuid"
                val request = Request.Builder()
                    .url(url)
                    .addHeader("X-Riot-Token", apiKey.trim())
                    .get()
                    .build()

                client.newCall(request).execute().use { response ->
                    if (response.isSuccessful) {
                        val body = response.body?.string()
                        if (body != null) {
                            val summoner = gson.fromJson(body, SummonerResponse::class.java)
                            return@withContext summoner.profileIconId
                        }
                    }
                }
            } catch (e: Exception) {
                // Încearcă următorul server de platformă
            }
        }
        return@withContext null
    }

    suspend fun getLatestTftMatchId(regionHost: String, puuid: String, apiKey: String): String? = withContext(Dispatchers.IO) {
        try {
            val host = formatHost(regionHost)
            val url = "$host/tft/match/v1/matches/by-puuid/$puuid/ids?count=1"

            val request = Request.Builder()
                .url(url)
                .addHeader("X-Riot-Token", apiKey.trim())
                .get()
                .build()

            client.newCall(request).execute().use { response ->
                if (response.isSuccessful) {
                    val body = response.body?.string()
                    if (body != null) {
                        val matchIds = gson.fromJson(body, Array<String>::class.java)
                        return@withContext matchIds.firstOrNull()
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        return@withContext null
    }

    suspend fun getTftMatchDetails(regionHost: String, matchId: String, apiKey: String): TftMatchResponse? = withContext(Dispatchers.IO) {
        try {
            val host = formatHost(regionHost)
            val url = "$host/tft/match/v1/matches/$matchId"

            val request = Request.Builder()
                .url(url)
                .addHeader("X-Riot-Token", apiKey.trim())
                .get()
                .build()

            client.newCall(request).execute().use { response ->
                if (response.isSuccessful) {
                    val body = response.body?.string()
                    if (body != null) {
                        return@withContext gson.fromJson(body, TftMatchResponse::class.java)
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        return@withContext null
    }
}
