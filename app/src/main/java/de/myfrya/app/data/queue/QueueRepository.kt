package de.myfrya.app.data.queue

import kotlinx.coroutines.flow.Flow

class QueueRepository(private val dao: QueueDao) {

    fun observeQueue(): Flow<List<QueueItemEntity>> = dao.observeAll()

    suspend fun enqueueFakeItem() {
        dao.insert(
            QueueItemEntity(
                createdAt = System.currentTimeMillis(),
                filePath = "local://dummy",
                pageCount = 1,
                status = QueueStatus.PENDING
            )
        )
    }

    suspend fun enqueueFailingDummyItem() {
        dao.insert(
            QueueItemEntity(
                createdAt = System.currentTimeMillis(),
                filePath = "local://fail",
                pageCount = 1,
                status = QueueStatus.PENDING
            )
        )
    }

    suspend fun retryFailed() {
        dao.retryFailed()
    }
}
