package de.myfrya.app.worker

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import de.myfrya.app.data.queue.AppDatabase
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers

class UploadWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val dao = AppDatabase.getInstance(applicationContext).queueDao()
        while (true) {
            val item = dao.getOldestPending() ?: break
            Log.d(TAG, "itemId=${item.id} status->RUNNING")
            dao.updateStatus(item.id, "RUNNING", null)
            delay(800)
            if (item.filePath == "local://fail") {
                dao.updateStatus(item.id, "FAILED", "Simulated failure")
                Log.d(TAG, "itemId=${item.id} status->FAILED")
            } else {
                dao.updateStatus(item.id, "SUCCESS", null)
                Log.d(TAG, "itemId=${item.id} status->SUCCESS")
            }
        }
        Result.success()
    }

    companion object {
        private const val TAG = "UploadWorker"
        const val UNIQUE_WORK_NAME = "upload-queue"
    }
}
