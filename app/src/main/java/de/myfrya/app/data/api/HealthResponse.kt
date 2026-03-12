package de.myfrya.app.data.api

import com.google.gson.annotations.SerializedName

data class HealthResponse(
    @SerializedName("status") val status: String
)
