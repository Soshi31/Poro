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

    suspend fun getPuuidByRiotId(macroHost: String, gameName: String, tagLine: String, apiKey: String): RiotResult<String> = withContext(Dispatchers.IO) {
        try {
            val encodedName = URLEncoder.encode(gameName.trim(), "UTF-8")
            val cleanTag = tagLine.trim().removePrefix("#")
            val encodedTag = URLEncoder.encode(cleanTag, "UTF-8")
            val host = formatHost(macroHost)
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
                            "Cheia Riot API este neconfigurată sau expirată."
                        )
                    }
                    404 -> {
                        return@withContext RiotResult.Error(
                            404,
                            "Contul $gameName#$cleanTag nu a fost găsit."
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

    suspend fun getSummonerProfileIconId(platformHost: String, puuid: String, apiKey: String): Int? = withContext(Dispatchers.IO) {
        try {
            val host = formatHost(platformHost)
            val url = "$host/lol/summoner/v4/summoners/by-puuid/$puuid"

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

    suspend fun fetchPublicProfileIconId(regionCode: String, gameName: String, tagLine: String): Int? = withContext(Dispatchers.IO) {
        try {
            val opGgRegion = when (regionCode.trim().uppercase()) {
                "EUW" -> "euw"
                "EUNE" -> "eune"
                "NA" -> "na"
                "KR" -> "kr"
                "TR" -> "tr"
                "RU" -> "ru"
                "OCE" -> "oce"
                "BR" -> "br"
                "LAN" -> "lan"
                "LAS" -> "las"
                else -> "eune"
            }
            val cleanName = URLEncoder.encode(gameName.trim(), "UTF-8")
            val cleanTag = URLEncoder.encode(tagLine.trim().removePrefix("#"), "UTF-8")
            val url = "https://www.op.gg/summoners/$opGgRegion/$cleanName-$cleanTag"

            val request = Request.Builder()
                .url(url)
                .addHeader("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
                .addHeader("Accept-Language", "en-US,en;q=0.9")
                .get()
                .build()

            client.newCall(request).execute().use { response ->
                if (response.isSuccessful) {
                    val html = response.body?.string()
                    if (html != null) {
                        val regex1 = Regex("""profile_icons/profileIcon(\d+)\.jpg""")
                        val regex2 = Regex("""profileicon/(\d+)\.png""")
                        val regex3 = Regex(""""profile_icon_id":\s*(\d+)""")

                        val match1 = regex1.find(html)?.groupValues?.get(1)?.toIntOrNull()
                        val match2 = regex2.find(html)?.groupValues?.get(1)?.toIntOrNull()
                        val match3 = regex3.find(html)?.groupValues?.get(1)?.toIntOrNull()

                        return@withContext match1 ?: match2 ?: match3
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        return@withContext null
    }

    suspend fun getLatestTftMatchId(macroHost: String, puuid: String, apiKey: String): String? = withContext(Dispatchers.IO) {
        try {
            val host = formatHost(macroHost)
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

    suspend fun getTftMatchDetails(macroHost: String, matchId: String, apiKey: String): TftMatchResponse? = withContext(Dispatchers.IO) {
        try {
            val host = formatHost(macroHost)
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
