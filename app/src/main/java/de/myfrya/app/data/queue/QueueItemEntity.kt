package de.myfrya.app.data.queue

import androidx.room.Entity
import androidx.room.PrimaryKey
import androidx.room.TypeConverter
import androidx.room.TypeConverters

@Entity(tableName = "queue_items")
@TypeConverters(QueueStatusConverter::class)
data class QueueItemEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val createdAt: Long,
    val filePath: String,
    val pageCount: Int,
    val status: QueueStatus,
    val errorMessage: String? = null
)

class QueueStatusConverter {
    @TypeConverter
    fun fromStatus(status: QueueStatus): String = status.name

    @TypeConverter
    fun toStatus(value: String): QueueStatus = QueueStatus.valueOf(value)
}
