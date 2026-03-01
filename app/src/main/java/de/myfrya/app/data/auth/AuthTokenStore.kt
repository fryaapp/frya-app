package de.myfrya.app.data.auth

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class AuthTokenStore(context: Context) {

    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val prefs = EncryptedSharedPreferences.create(
        context,
        "auth_prefs",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )

    private val keyAccessToken = "access_token"

    fun saveToken(token: String) {
        prefs.edit().putString(keyAccessToken, token).apply()
    }

    fun getToken(): String? = prefs.getString(keyAccessToken, null)

    fun hasToken(): Boolean = (getToken() ?: "").isNotBlank()

    fun clear() {
        prefs.edit().remove(keyAccessToken).apply()
    }
}
