package de.myfrya.app.data.queue

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "queue_items")
data class QueueItemEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val createdAt: Long,
    val filePath: String,
    val pageCount: Int,
    val status: String,
    val errorMessage: String? = null
)
