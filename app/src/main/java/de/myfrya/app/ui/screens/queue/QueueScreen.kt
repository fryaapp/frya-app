package de.myfrya.app.ui.screens.queue

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import de.myfrya.app.data.api.HealthRepository
import de.myfrya.app.data.queue.AppDatabase
import de.myfrya.app.data.queue.QueueItemEntity
import de.myfrya.app.data.queue.QueueRepository
import kotlinx.coroutines.launch

@Composable
fun QueueScreen(
    onNavigateToLogin: () -> Unit,
    onNavigateToCapture: () -> Unit,
    onLogout: () -> Unit
) {
    val context = LocalContext.current
    val appContext = context.applicationContext
    val db = remember { AppDatabase.getInstance(appContext) }
    val repository = remember(db, appContext) { QueueRepository(db.queueDao(), appContext) }
    val healthRepository = remember { HealthRepository() }
    val viewModel = remember(repository, healthRepository, appContext) {
        QueueViewModel(repository, healthRepository, appContext)
    }
    val scope = rememberCoroutineScope()

    val items by produceState(initialValue = emptyList<QueueItemEntity>(), viewModel) {
        viewModel.queueItems.collect { value = it }
    }
    val lastWorkState by viewModel.lastWorkState.collectAsState(initial = "—")
    val lastWorkId by viewModel.lastWorkId.collectAsState(initial = null)
    val lastWorkError by viewModel.lastWorkError.collectAsState(initial = null)
    val apiStatus by viewModel.apiStatus.collectAsState(initial = null)
    val workIdShort = lastWorkId?.toString()?.take(8) ?: "—"

    val countPending = items.count { it.status == "PENDING" }
    val countRunning = items.count { it.status == "RUNNING" }
    val countFailed = items.count { it.status == "FAILED" }
    val countSuccess = items.count { it.status == "SUCCESS" }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text("Queue")
            Button(onClick = onNavigateToCapture) {
                Text("Capture")
            }
        }
        Text("Last Work: $lastWorkState ($workIdShort)")
        lastWorkError?.let { err -> Text("Work Error: $err") }
        Text("Items: ${items.size} | PENDING: $countPending | RUNNING: $countRunning | FAILED: $countFailed | SUCCESS: $countSuccess")
        Spacer(modifier = Modifier.height(8.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Button(onClick = {
                scope.launch { viewModel.enqueueFakeItem() }
            }) {
                Text("Add Dummy Item")
            }
            Button(onClick = {
                scope.launch { viewModel.addFailingItem() }
            }) {
                Text("Add FAIL Item")
            }
            Button(onClick = {
                scope.launch { viewModel.retryFailed() }
            }) {
                Text("Retry Failed")
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Button(onClick = {
                scope.launch { viewModel.startUploadNowDebug() }
            }) {
                Text("Start Upload Now (Debug)")
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Button(onClick = {
                scope.launch { viewModel.checkApi() }
            }) {
                Text("API prüfen")
            }
            Text("Staging: ${apiStatus ?: "—"}")
        }
        Spacer(modifier = Modifier.height(16.dp))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(items) { item ->
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors()
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text("ID: ${item.id}")
                        Text("Status: ${item.status}")
                        Text("Pages: ${item.pageCount}")
                        item.errorMessage?.let { Text("Error: $it") }
                    }
                }
            }
        }
        Spacer(modifier = Modifier.height(16.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Button(onClick = onNavigateToLogin) { Text("Zu Login") }
            Button(onClick = onNavigateToCapture) { Text("Zu Capture") }
            Button(onClick = onLogout) { Text("Logout") }
        }
    }
}
