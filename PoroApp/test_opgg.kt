import java.net.URL
import java.net.HttpURLConnection

fun main() {
    try {
        val url = URL("https://www.op.gg/summoners/eune/Soshi-2609")
        val connection = url.openConnection() as HttpURLConnection
        connection.setRequestProperty("User-Agent", "Mozilla/5.0")
        val html = connection.inputStream.bufferedReader().use { it.readText() }
        
        val regex = Regex("""<img[^>]+src="[^"]+profileIcon(\d+)\.(jpg|png)"""", setOf(RegexOption.IGNORE_CASE))
        val match = regex.find(html)
        if (match != null) {
            println("Found: " + match.groupValues[1])
        } else {
            println("Not found by main regex")
            val regex2 = Regex("""profile[a-zA-Z_]*icon[s]?/?(\d+)\.""", setOf(RegexOption.IGNORE_CASE))
            val m2 = regex2.find(html)
            if (m2 != null) println("Found 2: " + m2.groupValues[1]) else println("Not found at all")
        }
    } catch (e: Exception) {
        println(e.message)
    }
}
