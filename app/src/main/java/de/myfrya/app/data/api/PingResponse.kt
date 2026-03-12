package de.myfrya.app.data.api

import com.google.gson.annotations.SerializedName

data class PingResponse(
    @SerializedName("message") val message: String
)
