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

object RiotTftManager {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    private val gson = Gson()

    suspend fun getPuuidByRiotId(gameName: String, tagLine: String, apiKey: String): String? = withContext(Dispatchers.IO) {
        try {
            val encodedName = URLEncoder.encode(gameName.trim(), "UTF-8")
            val encodedTag = URLEncoder.encode(tagLine.trim(), "UTF-8")
            val url = "https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/$encodedName/$encodedTag"

            val request = Request.Builder()
                .url(url)
                .addHeader("X-Riot-Token", apiKey.trim())
                .get()
                .build()

            client.newCall(request).execute().use { response ->
                if (response.isSuccessful) {
                    val body = response.body?.string()
                    if (body != null) {
                        val account = gson.fromJson(body, RiotAccountResponse::class.java)
                        return@withContext account.puuid
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        return@withContext null
    }

    suspend fun getLatestTftMatchId(puuid: String, apiKey: String): String? = withContext(Dispatchers.IO) {
        try {
            val url = "https://europe.api.riotgames.com/tft/match/v1/matches/by-puuid/$puuid/ids?count=1"

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

    suspend fun getTftMatchDetails(matchId: String, apiKey: String): TftMatchResponse? = withContext(Dispatchers.IO) {
        try {
            val url = "https://europe.api.riotgames.com/tft/match/v1/matches/$matchId"

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
