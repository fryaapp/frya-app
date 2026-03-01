package de.myfrya.app.worker

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import de.myfrya.app.data.queue.AppDatabase
import de.myfrya.app.data.queue.QueueStatus
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers

class UploadWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        Log.d(TAG, "start")
        val dao = AppDatabase.getInstance(applicationContext).queueDao()
        val item = dao.getOldestPending() ?: run {
            Log.d(TAG, "done no item")
            return@withContext Result.success()
        }
        Log.d(TAG, "picked item id=${item.id} status->RUNNING")
        dao.updateStatus(item.id, QueueStatus.RUNNING, null)
        if (item.filePath == "local://fail") {
            dao.updateStatus(item.id, QueueStatus.FAILED, "Simulated failure")
            Log.d(TAG, "done status->FAILED")
            return@withContext Result.success()
        }
        delay(2000)
        dao.updateStatus(item.id, QueueStatus.SUCCESS, null)
        Log.d(TAG, "done status->SUCCESS")
        Result.success()
    }

    companion object {
        private const val TAG = "UploadWorker"
    }
}
