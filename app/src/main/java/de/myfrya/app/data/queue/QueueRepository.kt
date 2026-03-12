package de.myfrya.app.data.queue

import android.content.Context
import de.myfrya.app.data.work.WorkEnqueuer
import kotlinx.coroutines.flow.Flow
import java.util.UUID

class QueueRepository(
    private val dao: QueueDao,
    private val context: Context
) {

    private val workEnqueuer = WorkEnqueuer(context.applicationContext)

    fun observeQueue(): Flow<List<QueueItemEntity>> = dao.observeAll()

    suspend fun enqueueFakeItem(): UUID? {
        dao.insert(
            QueueItemEntity(
                createdAt = System.currentTimeMillis(),
                filePath = "local://dummy",
                pageCount = 1,
                status = "PENDING"
            )
        )
        return workEnqueuer.startUploadWorkIfIdle()
    }

    suspend fun enqueueFailingDummyItem(): UUID? {
        dao.insert(
            QueueItemEntity(
                createdAt = System.currentTimeMillis(),
                filePath = "local://fail",
                pageCount = 1,
                status = "PENDING"
            )
        )
        return workEnqueuer.startUploadWorkIfIdle()
    }

    suspend fun retryFailed() {
        dao.retryFailed()
    }

    suspend fun enqueueCaptureItem(filePath: String, pageCount: Int): UUID? {
        dao.insert(
            QueueItemEntity(
                createdAt = System.currentTimeMillis(),
                filePath = filePath,
                pageCount = pageCount,
                status = "PENDING"
            )
        )
        return workEnqueuer.startUploadWorkIfIdle()
    }

    /** Starts upload work if idle (e.g. for debug "Run Upload Worker" with existing PENDING items). */
    suspend fun startUploadWorkIfIdle(): UUID? = workEnqueuer.startUploadWorkIfIdle()
}
