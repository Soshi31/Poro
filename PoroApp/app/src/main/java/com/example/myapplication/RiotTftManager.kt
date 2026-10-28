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

    suspend fun getSummonerProfileIconId(regionHost: String, puuid: String, apiKey: String): Int? = withContext(Dispatchers.IO) {
        try {
            val platformHost = when {
                regionHost.contains("europe", ignoreCase = true) -> "https://eun1.api.riotgames.com"
                regionHost.contains("americas", ignoreCase = true) -> "https://na1.api.riotgames.com"
                regionHost.contains("asia", ignoreCase = true) -> "https://kr.api.riotgames.com"
                regionHost.contains("sea", ignoreCase = true) -> "https://oc1.api.riotgames.com"
                else -> "https://eun1.api.riotgames.com"
            }
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
            e.printStackTrace()
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
