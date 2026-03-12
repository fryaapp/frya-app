package de.myfrya.app.ui.screens.capture

import android.app.Activity
import android.content.IntentSender
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import de.myfrya.app.data.queue.AppDatabase
import de.myfrya.app.data.queue.QueueRepository
import kotlinx.coroutines.launch

@Composable
fun CaptureScreen(
    onNavigateToLogin: () -> Unit,
    onNavigateToQueue: () -> Unit
) {
    val context = LocalContext.current
    val activity = context as? Activity
    val appContext = context.applicationContext
    val scope = rememberCoroutineScope()
    val db = remember { AppDatabase.getInstance(appContext) }
    val repository = remember(db, appContext) { QueueRepository(db.queueDao(), appContext) }
    val viewModel = remember(repository, appContext) { CaptureViewModel(repository, appContext) }

    val options = remember {
        GmsDocumentScannerOptions.Builder()
            .setGalleryImportAllowed(true)
            .setPageLimit(20)
            .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_JPEG)
            .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL)
            .build()
    }
    val scanner = remember(options) { GmsDocumentScanning.getClient(options) }

    val scannerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartIntentSenderForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val data = result.data
            val scanResult = data?.let { GmsDocumentScanningResult.fromActivityResultIntent(it) }
            val pages = scanResult?.pages ?: emptyList()
            val uris = pages.mapNotNull { it.imageUri }
            if (uris.isNotEmpty()) {
                scope.launch {
                    viewModel.onScanCompleted(uris)
                }
            }
        }
    }

    val pagesCount by viewModel.pagesCount.collectAsState(initial = 0)
    val lastScanDirPath by viewModel.lastScanDirPath.collectAsState(initial = null)
    val isSaving by viewModel.isSaving.collectAsState(initial = false)
    val error by viewModel.error.collectAsState(initial = null)
    val canFinish = lastScanDirPath != null && pagesCount > 0

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("Capture")
        Spacer(modifier = Modifier.height(16.dp))
        Button(
            onClick = {
                activity?.let { act ->
                    scanner.getStartScanIntent(act)
                        .addOnSuccessListener { intentSender: IntentSender ->
                            scannerLauncher.launch(IntentSenderRequest.Builder(intentSender).build())
                        }
                        .addOnFailureListener {
                            scope.launch {
                                viewModel.onScanCompleted(emptyList())
                            }
                        }
                }
            },
            enabled = !isSaving
        ) {
            Text("Scan starten")
        }
        Spacer(modifier = Modifier.height(8.dp))
        Text("Seiten: $pagesCount")
        if (lastScanDirPath != null) {
            Text("Gespeichert ✓")
        }
        if (isSaving) {
            Text("Speichere…", style = MaterialTheme.typography.bodySmall)
        }
        error?.let { msg ->
            Text(text = msg, color = MaterialTheme.colorScheme.error)
        }
        Spacer(modifier = Modifier.height(16.dp))
        Button(
            onClick = { viewModel.onClear() },
            enabled = !isSaving
        ) {
            Text("Leeren")
        }
        Spacer(modifier = Modifier.height(8.dp))
        Button(
            onClick = {
                scope.launch {
                    if (viewModel.onFinishCreateQueueItem()) {
                        onNavigateToQueue()
                    }
                }
            },
            enabled = canFinish && !isSaving
        ) {
            Text("Fertig")
        }
        Spacer(modifier = Modifier.height(16.dp))
        Button(onClick = onNavigateToLogin) {
            Text("Zu Login")
        }
        Button(onClick = onNavigateToQueue) {
            Text("Zu Queue")
        }
    }
}
