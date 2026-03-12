package de.myfrya.app.ui

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Scanner
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.navigation.compose.currentBackStackEntryAsState
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
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val showBottomBar = currentRoute == Routes.Queue.route ||
        currentRoute == Routes.Capture.route ||
        currentRoute == Routes.BuildPlan.route

    Scaffold(
        topBar = {
            TopAppBar(title = { Text("Frya") })
        },
        bottomBar = {
            if (showBottomBar) {
                NavigationBar {
                    NavigationBarItem(
                        selected = currentRoute == Routes.Queue.route,
                        onClick = {
                            navController.navigate(Routes.Queue.route) {
                                launchSingleTop = true
                            }
                        },
                        icon = { Icon(Icons.Default.List, contentDescription = "Queue") },
                        label = { Text("Queue") }
                    )
                    NavigationBarItem(
                        selected = currentRoute == Routes.Capture.route,
                        onClick = {
                            navController.navigate(Routes.Capture.route) {
                                launchSingleTop = true
                            }
                        },
                        icon = { Icon(Icons.Default.Scanner, contentDescription = "Capture") },
                        label = { Text("Capture") }
                    )
                    NavigationBarItem(
                        selected = currentRoute == Routes.BuildPlan.route,
                        onClick = {
                            navController.navigate(Routes.BuildPlan.route) {
                                launchSingleTop = true
                            }
                        },
                        icon = { Icon(Icons.Default.Description, contentDescription = "Buildplan") },
                        label = { Text("Buildplan") }
                    )
                }
            }
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
