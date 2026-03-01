package de.myfrya.app.ui.navigation

sealed class Routes(val route: String) {
    object Login : Routes("login")
    object Capture : Routes("capture")
    object Queue : Routes("queue")
}
