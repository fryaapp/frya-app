package de.myfrya.app.ui.screens.queue

import android.content.Context
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import de.myfrya.app.data.queue.QueueItemEntity
import de.myfrya.app.data.queue.QueueRepository
import de.myfrya.app.worker.UploadWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.Flow
import java.util.UUID

class QueueViewModel(
    private val repository: QueueRepository,
    private val context: Context
) {

    private val workManager = WorkManager.getInstance(context)
    private val scope = CoroutineScope(Dispatchers.Main.immediate + SupervisorJob())

    private val _lastWorkId = MutableStateFlow<UUID?>(null)
    val lastWorkId: StateFlow<UUID?> = _lastWorkId.asStateFlow()

    val lastWorkState: StateFlow<String> = _lastWorkId
        .flatMapLatest { id ->
            if (id != null) {
                workManager.getWorkInfoByIdFlow(id).map { it.state.name }
            } else {
                flowOf("—")
            }
        }
        .stateIn(scope, SharingStarted.WhileSubscribed(5000), "—")

    val queueItems: Flow<List<QueueItemEntity>> = repository.observeQueue()

    suspend fun enqueueFakeItem() {
        repository.enqueueFakeItem()
    }

    suspend fun addFailingItem() {
        repository.enqueueFailingDummyItem()
    }

    suspend fun retryFailed() {
        repository.retryFailed()
    }

    fun startUpload() {
        val request = OneTimeWorkRequestBuilder<UploadWorker>().build()
        workManager.enqueueUniqueWork(
            "upload-queue",
            ExistingWorkPolicy.REPLACE,
            request
        )
        _lastWorkId.value = request.id
    }
}
