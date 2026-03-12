package de.myfrya.app.data.api

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class HealthRepository(
    private val api: HealthApi = ApiClient.healthApi
) {

    suspend fun fetchHealth(): Result<HealthResponse> = withContext(Dispatchers.IO) {
        runCatching { api.health() }
    }

    suspend fun fetchPing(): Result<PingResponse> = withContext(Dispatchers.IO) {
        runCatching { api.ping() }
    }
}
