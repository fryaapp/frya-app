package de.myfrya.app.ui

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.navigation.compose.rememberNavController
import de.myfrya.app.data.auth.AuthTokenStore
import de.myfrya.app.ui.navigation.AppNavHost
import de.myfrya.app.ui.navigation.Routes

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppRoot() {
    val context = LocalContext.current
    val tokenStore = remember { AuthTokenStore(context.applicationContext) }
    val startDestination = if (tokenStore.hasToken()) Routes.Queue.route else Routes.Login.route
    val navController = rememberNavController()

    Scaffold(
        topBar = {
            TopAppBar(title = { Text("Frya") })
        },
        modifier = Modifier.fillMaxSize()
    ) { innerPadding ->
        AppNavHost(
            navController = navController,
            startDestination = startDestination,
            tokenStore = tokenStore,
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        )
    }
}
