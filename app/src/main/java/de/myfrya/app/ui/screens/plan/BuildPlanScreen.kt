package de.myfrya.app.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.produceState
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp

@Composable
fun BuildPlanScreen(
    onNavigateToQueue: () -> Unit,
    onNavigateToCapture: () -> Unit
) {
    val context = LocalContext.current
    val planText = produceState(initialValue = "Buildplan wird geladen...", context) {
        value = runCatching {
            context.assets.open("frya-stage1-buildplan.jsx").bufferedReader().use { it.readText() }
        }.getOrElse { err ->
            "Buildplan konnte nicht geladen werden: ${err.message}"
        }
    }.value

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text("Buildplan (Stage 1)")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onNavigateToQueue) { Text("Queue") }
                Button(onClick = onNavigateToCapture) { Text("Capture") }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        Card(modifier = Modifier.fillMaxSize()) {
            SelectionContainer {
                Text(
                    text = planText,
                    fontFamily = FontFamily.Monospace,
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(12.dp)
                )
            }
        }
    }
}
