package de.myfrya.app.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import de.myfrya.app.data.auth.AuthTokenStore
import de.myfrya.app.ui.screens.capture.CaptureScreen
import de.myfrya.app.ui.screens.login.LoginScreen
import de.myfrya.app.ui.screens.plan.BuildPlanScreen
import de.myfrya.app.ui.screens.queue.QueueScreen

@Composable
fun AppNavHost(
    navController: NavHostController,
    startDestination: String,
    tokenStore: AuthTokenStore,
    modifier: Modifier = Modifier
) {
    NavHost(
        navController = navController,
        startDestination = startDestination,
        modifier = modifier
    ) {
        composable(Routes.Login.route) {
            LoginScreen(
                onLoginSuccess = {
                    navController.navigate(Routes.Queue.route) {
                        popUpTo(Routes.Login.route) { inclusive = true }
                    }
                }
            )
        }
        composable(Routes.Capture.route) {
            CaptureScreen(
                onNavigateToLogin = { navController.navigate(Routes.Login.route) },
                onNavigateToQueue = { navController.navigate(Routes.Queue.route) }
            )
        }
        composable(Routes.Queue.route) {
            QueueScreen(
                onNavigateToLogin = { navController.navigate(Routes.Login.route) },
                onNavigateToCapture = { navController.navigate(Routes.Capture.route) },
                onLogout = {
                    tokenStore.clear()
                    navController.navigate(Routes.Login.route) {
                        popUpTo(Routes.Queue.route) { inclusive = true }
                    }
                }
            )
        }
        composable(Routes.BuildPlan.route) {
            BuildPlanScreen(
                onNavigateToQueue = { navController.navigate(Routes.Queue.route) },
                onNavigateToCapture = { navController.navigate(Routes.Capture.route) }
            )
        }
    }
}
