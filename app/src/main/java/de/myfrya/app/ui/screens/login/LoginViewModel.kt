package de.myfrya.app.ui.screens.login

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import de.myfrya.app.data.api.ApiClient
import de.myfrya.app.data.api.LoginRequest
import de.myfrya.app.data.auth.AuthTokenStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.HttpException

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

    suspend fun login(onLoginSuccess: () -> Unit) {
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
        val result = runCatching {
            withContext(Dispatchers.IO) {
                ApiClient.authApi.login(LoginRequest(email = email.trim(), password = password))
            }
        }
        isLoading = false
        result.fold(
            onSuccess = { response ->
                tokenStore.saveToken(response.accessToken)
                onLoginSuccess()
            },
            onFailure = { e ->
                error = when (e) {
                    is HttpException -> if (e.code() == 401) "E-Mail oder Passwort falsch" else "Anmeldung fehlgeschlagen"
                    else -> "Anmeldung fehlgeschlagen"
                }
            }
        )
    }
}
