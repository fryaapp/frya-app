package de.myfrya.app.ui.screens.queue

import android.content.Context
import androidx.work.WorkInfo
import androidx.work.WorkManager
import de.myfrya.app.data.api.HealthRepository
import de.myfrya.app.data.queue.QueueItemEntity
import de.myfrya.app.data.queue.QueueRepository
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
import retrofit2.HttpException
import java.io.IOException
import java.util.UUID

class QueueViewModel(
    private val repository: QueueRepository,
    private val healthRepository: HealthRepository,
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

    val lastWorkError: StateFlow<String?> = _lastWorkId
        .flatMapLatest { id ->
            if (id != null) {
                workManager.getWorkInfoByIdFlow(id).map { info ->
                    if (info.state == WorkInfo.State.FAILED) {
                        info.outputData.getString("error") ?: "Work failed"
                    } else null
                }
            } else {
                flowOf(null)
            }
        }
        .stateIn(scope, SharingStarted.WhileSubscribed(5000), null)

    val queueItems: Flow<List<QueueItemEntity>> = repository.observeQueue()

    suspend fun enqueueFakeItem() {
        val id = repository.enqueueFakeItem()
        if (id != null) _lastWorkId.value = id
    }

    suspend fun addFailingItem() {
        val id = repository.enqueueFailingDummyItem()
        if (id != null) _lastWorkId.value = id
    }

    suspend fun retryFailed() {
        repository.retryFailed()
    }

    suspend fun startUploadNowDebug() {
        val id = repository.startUploadWorkIfIdle()
        if (id != null) _lastWorkId.value = id
    }

    private val _apiStatus = MutableStateFlow<String?>(null)
    val apiStatus: StateFlow<String?> = _apiStatus.asStateFlow()

    suspend fun checkApi() {
        _apiStatus.value = null
        val healthResult = healthRepository.fetchHealth()
        val pingResult = healthRepository.fetchPing()
        _apiStatus.value = when {
            healthResult.isSuccess && pingResult.isSuccess -> "OK"
            else -> {
                val e = healthResult.exceptionOrNull() ?: pingResult.exceptionOrNull()
                when (e) {
                    is HttpException -> "Fehler: ${e.code()}"
                    is IOException -> "Fehler: Netzwerk"
                    else -> "Fehler"
                }
            }
        }
    }
}
