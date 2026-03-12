package de.myfrya.app.ui.screens.capture

import android.content.Context
import android.net.Uri
import de.myfrya.app.data.capture.ScanStorage
import de.myfrya.app.data.queue.QueueRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class CaptureViewModel(
    private val repository: QueueRepository,
    private val context: Context
) {

    private val _pagesCount = MutableStateFlow(0)
    val pagesCount: StateFlow<Int> = _pagesCount.asStateFlow()

    private val _lastScanDirPath = MutableStateFlow<String?>(null)
    val lastScanDirPath: StateFlow<String?> = _lastScanDirPath.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private val _isSaving = MutableStateFlow(false)
    val isSaving: StateFlow<Boolean> = _isSaving.asStateFlow()

    suspend fun onScanCompleted(pageUris: List<Uri>) {
        _error.value = null
        _isSaving.value = true
        try {
            val persisted = ScanStorage.persistScanResult(context, pageUris)
            if (persisted != null) {
                _pagesCount.value = persisted.pageCount
                _lastScanDirPath.value = persisted.docDirPath
            } else {
                _error.value = "Keine Seiten gespeichert"
            }
        } finally {
            _isSaving.value = false
        }
    }

    fun onClear() {
        _pagesCount.value = 0
        _lastScanDirPath.value = null
        _error.value = null
    }

    suspend fun onFinishCreateQueueItem(): Boolean {
        val path = _lastScanDirPath.value ?: return false
        val count = _pagesCount.value
        if (count <= 0) return false
        repository.enqueueCaptureItem(path, count)
        return true
    }
}
