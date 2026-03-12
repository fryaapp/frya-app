package de.myfrya.app.data.work

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import de.myfrya.app.worker.UploadWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.guava.await
import kotlinx.coroutines.withContext
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * Encapsulates WorkManager enqueue logic for upload work.
 * Single responsibility: start unique upload work if idle, with minimal constraints.
 * @param appContext Use ApplicationContext (e.g. context.applicationContext).
 */
class WorkEnqueuer(
    private val appContext: Context
) {

    private val workManager: WorkManager by lazy {
        WorkManager.getInstance(appContext)
    }

    /**
     * Enqueues unique upload work (KEEP) only if no run is RUNNING/ENQUEUED.
     * Uses suspend await instead of blocking .get().
     * @return request id when work was enqueued, null when already running.
     */
    suspend fun startUploadWorkIfIdle(): UUID? = withContext(Dispatchers.IO) {
        val infos = workManager.getWorkInfosForUniqueWork(UploadWorker.UNIQUE_WORK_NAME).await()
        val alreadyRunning = infos.any { it.state == WorkInfo.State.RUNNING || it.state == WorkInfo.State.ENQUEUED }
        if (!alreadyRunning) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val request = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(constraints)
                .setBackoffCriteria(
                    androidx.work.BackoffPolicy.EXPONENTIAL,
                    10,
                    TimeUnit.SECONDS
                )
                .build()
            workManager.enqueueUniqueWork(
                UploadWorker.UNIQUE_WORK_NAME,
                ExistingWorkPolicy.KEEP,
                request
            )
            request.id
        } else {
            null
        }
    }
}
