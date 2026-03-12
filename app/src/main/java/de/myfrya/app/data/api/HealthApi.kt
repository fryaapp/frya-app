package de.myfrya.app.data.api

import retrofit2.http.GET

interface HealthApi {

    @GET("health")
    suspend fun health(): HealthResponse

    @GET("v1/ping")
    suspend fun ping(): PingResponse
}
