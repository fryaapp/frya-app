package de.myfrya.app.data.capture

import android.content.Context
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.InputStream
import java.util.UUID

data class PersistedScan(
    val docDirPath: String,
    val pageCount: Int,
    val pagePaths: List<String>
)

object ScanStorage {

    private const val SCANS_DIR = "scans"
    private const val PAGE_PREFIX = "page_"
    private const val PAGE_EXT = ".jpg"

    suspend fun persistScanResult(context: Context, pageUris: List<Uri>): PersistedScan? = withContext(Dispatchers.IO) {
        if (pageUris.isEmpty()) return@withContext null
        val docId = UUID.randomUUID().toString().take(8)
        val scansDir = File(context.filesDir, SCANS_DIR)
        val docDir = File(scansDir, docId)
        if (!docDir.exists()) docDir.mkdirs()
        val pagePaths = mutableListOf<String>()
        pageUris.forEachIndexed { index, uri ->
            val pageFile = File(docDir, "$PAGE_PREFIX${"%03d".format(index + 1)}$PAGE_EXT")
            context.contentResolver.openInputStream(uri)?.use { input: InputStream ->
                pageFile.outputStream().use { output ->
                    input.copyTo(output)
                }
            }
            pagePaths.add(pageFile.absolutePath)
        }
        PersistedScan(
            docDirPath = docDir.absolutePath,
            pageCount = pagePaths.size,
            pagePaths = pagePaths
        )
    }
}
