package com.miracle.footmarks.data.remote

import com.google.gson.annotations.SerializedName
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.DELETE
import retrofit2.http.Multipart
import retrofit2.http.Part
import retrofit2.http.Path
import okhttp3.MultipartBody

data class TripRequest(
    @SerializedName("province_code") val provinceCode: String,
    @SerializedName("city_code") val cityCode: String,
    @SerializedName("city_name") val cityName: String,
    @SerializedName("start_date") val startDate: String,
    @SerializedName("end_date") val endDate: String
)

data class RecordRequest(
    val type: String,
    val name: String,
    val date: String,
    val rating: String?,
    val cost: String?,
    val notes: String?,
    val trip: TripRequest? = null
)

data class RemoteTripSummary(
    val id: Long,
    @SerializedName("province_code") val provinceCode: String,
    @SerializedName("city_code") val cityCode: String,
    @SerializedName("city_name") val cityName: String,
    @SerializedName("start_date") val startDate: String,
    @SerializedName("end_date") val endDate: String
)

data class LoginRequest(val username: String, val password: String)

data class Tokens(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("refresh_token") val refreshToken: String
)

data class RemoteRecord(
    val id: Long,
    @SerializedName("trip_id") val tripId: Long,
    val type: String,
    val name: String,
    val date: String,
    val rating: String?,
    val cost: String?,
    val notes: String?,
    val images: List<RemoteImage>? = emptyList()
)

data class RemoteImage(
    val id: Long,
    @SerializedName("record_id") val recordId: Long,
    @SerializedName("object_key") val objectKey: String,
    @SerializedName("original_filename") val originalFilename: String,
    @SerializedName("content_type") val contentType: String?,
    @SerializedName("size_bytes") val sizeBytes: Long?,
    val url: String
)

data class RemoteTrip(
    val id: Long,
    @SerializedName("province_code") val provinceCode: String,
    @SerializedName("city_code") val cityCode: String,
    @SerializedName("city_name") val cityName: String,
    @SerializedName("start_date") val startDate: String,
    @SerializedName("end_date") val endDate: String,
    val records: List<RemoteRecord>
)

interface FootmarksApi {
    @POST("api/v1/auth/login")
    suspend fun login(@Body request: LoginRequest): Tokens

    @GET("api/v1/trips")
    suspend fun getTrips(@Header("Authorization") authorization: String): List<RemoteTrip>

    @POST("api/v1/trips")
    suspend fun createTrip(
        @Header("Authorization") authorization: String,
        @Body trip: TripRequest
    ): RemoteTripSummary

    @PATCH("api/v1/trips/{tripId}")
    suspend fun updateTrip(
        @Header("Authorization") authorization: String,
        @Path("tripId") tripId: Long,
        @Body trip: TripRequest
    ): RemoteTrip

    @POST("api/v1/trips/{tripId}/records")
    suspend fun createRecord(
        @Header("Authorization") authorization: String,
        @Path("tripId") tripId: Long,
        @Body record: RecordRequest
    ): RemoteRecord

    @PATCH("api/v1/records/{recordId}")
    suspend fun updateRecord(
        @Header("Authorization") authorization: String,
        @Path("recordId") recordId: Long,
        @Body record: RecordRequest
    ): RemoteRecord

    @DELETE("api/v1/records/{recordId}")
    suspend fun deleteRecord(
        @Header("Authorization") authorization: String,
        @Path("recordId") recordId: Long
    )

    @DELETE("api/v1/trips/{tripId}")
    suspend fun deleteTrip(
        @Header("Authorization") authorization: String,
        @Path("tripId") tripId: Long
    )

    @Multipart
    @POST("api/v1/records/{recordId}/images")
    suspend fun uploadImage(
        @Header("Authorization") authorization: String,
        @Path("recordId") recordId: Long,
        @Part file: MultipartBody.Part
    ): RemoteImage

    @GET("api/v1/records/{recordId}/images")
    suspend fun getImages(
        @Header("Authorization") authorization: String,
        @Path("recordId") recordId: Long
    ): List<RemoteImage>

    @DELETE("api/v1/images/{imageId}")
    suspend fun deleteImage(
        @Header("Authorization") authorization: String,
        @Path("imageId") imageId: Long
    )

    @POST("api/v1/auth/refresh")
    suspend fun refresh(@Body request: RefreshRequest): Tokens

    companion object {
        fun create(baseUrl: String): FootmarksApi = Retrofit.Builder()
            .baseUrl(baseUrl)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(FootmarksApi::class.java)
    }
}

data class RefreshRequest(@SerializedName("refresh_token") val refreshToken: String)
