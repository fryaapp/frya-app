package de.myfrya.app.data.queue

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface QueueDao {

    @Insert
    suspend fun insert(item: QueueItemEntity): Long

    @Query("SELECT * FROM queue_items ORDER BY createdAt ASC")
    fun observeAll(): Flow<List<QueueItemEntity>>

    @Query("SELECT * FROM queue_items WHERE status = 'PENDING' ORDER BY createdAt ASC LIMIT 1")
    suspend fun getOldestPending(): QueueItemEntity?

    @Query("UPDATE queue_items SET status = :status, errorMessage = :errorMessage WHERE id = :id")
    suspend fun updateStatus(id: Long, status: String, errorMessage: String? = null)

    @Query("UPDATE queue_items SET status = 'PENDING', errorMessage = null WHERE status = 'FAILED'")
    suspend fun retryFailed()
}
