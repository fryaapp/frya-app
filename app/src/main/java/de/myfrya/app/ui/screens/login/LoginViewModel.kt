package de.myfrya.app.ui.screens.login

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import de.myfrya.app.data.auth.AuthTokenStore

class LoginViewModel(private val tokenStore: AuthTokenStore) {

    var email by mutableStateOf("")
        private set
    var password by mutableStateOf("")
        private set
    var isLoading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    fun onEmailChange(value: String) {
        email = value
        error = null
    }

    fun onPasswordChange(value: String) {
        password = value
        error = null
    }

    fun onLoginClicked(onLoginSuccess: () -> Unit) {
        error = null
        if (!email.contains("@")) {
            error = "Ungültige E-Mail"
            return
        }
        if (password.isBlank()) {
            error = "Passwort darf nicht leer sein"
            return
        }
        isLoading = true
        tokenStore.saveToken("dev-token")
        isLoading = false
        onLoginSuccess()
    }
}
