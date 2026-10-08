package com.miracle.footmarks.data.remote

import com.google.gson.annotations.SerializedName
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.DELETE
import retrofit2.http.HTTP
import retrofit2.http.Multipart
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.Streaming
import retrofit2.Response
import okhttp3.ResponseBody
import okhttp3.MultipartBody
import java.util.concurrent.TimeUnit

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

data class AgentChatRequest(
    val message: String,
    @SerializedName("conversation_id") val conversationId: String? = null,
    @SerializedName("client_message_id") val clientMessageId: String? = null
)

data class AgentChatResponse(
    @SerializedName("request_id") val requestId: String,
    val answer: String,
    @SerializedName("conversation_id") val conversationId: String? = null
)

data class RemoteConversation(
    val id: String,
    val title: String,
    @SerializedName("created_at") val createdAt: String,
    @SerializedName("updated_at") val updatedAt: String,
    @SerializedName("message_count") val messageCount: Int
)

data class RemoteConversationMessage(
    val id: Long,
    val role: String,
    val content: String,
    val status: String,
    @SerializedName("created_at") val createdAt: String
)

data class PreferenceRequest(val content: String)

data class RemotePreference(
    val id: Long,
    val category: String,
    val content: String,
    @SerializedName("created_at") val createdAt: String,
    @SerializedName("updated_at") val updatedAt: String
)

data class KnowledgeRequest(
    val category: String,
    val title: String,
    val body: String,
    @SerializedName("city_code") val cityCode: String,
    @SerializedName("city_name") val cityName: String,
    val tags: List<String>,
    val source: String?
)

data class RemoteKnowledge(
    val id: Long,
    val category: String,
    val title: String,
    val body: String,
    @SerializedName("city_code") val cityCode: String,
    @SerializedName("city_name") val cityName: String,
    val tags: List<String>,
    val source: String?,
    @SerializedName("created_at") val createdAt: String,
    @SerializedName("updated_at") val updatedAt: String
)

data class Tokens(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("refresh_token") val refreshToken: String,
    @SerializedName("user_id") val userId: Long? = null,
    val role: String? = null,
    @SerializedName("requires_password_change") val requiresPasswordChange: Boolean = false,
    val username: String? = null
)

data class AccountInfo(val id: Long, val username: String)

data class TripSyncPage(
    val upserts: List<RemoteTrip>,
    @SerializedName("deleted_ids") val deletedIds: List<Long>,
    @SerializedName("next_cursor") val nextCursor: String,
    @SerializedName("has_more") val hasMore: Boolean
)

data class AdminUser(
    val id: Long,
    val username: String,
    val role: String,
    val status: String,
    @SerializedName("requires_password_change") val requiresPasswordChange: Boolean,
    @SerializedName("monthly_token_limit") val monthlyTokenLimit: Int?,
    @SerializedName("photo_bytes_used") val photoBytesUsed: Long = 0
)

data class AdminDefaultQuota(val limit: Int)

data class AdminStatusRequest(val status: String)
data class AdminPasswordRequest(@SerializedName("new_password") val newPassword: String)
data class AdminQuotaRequest(val limit: Int?)
data class DeleteAccountRequest(val password: String, val confirm: Boolean = true)
data class PasswordChangeRequest(
    @SerializedName("current_password") val currentPassword: String,
    @SerializedName("new_password") val newPassword: String
)
data class TokenQuotaBalance(
    val period: String,
    val limit: Int,
    val used: Int,
    val reserved: Int,
    val remaining: Int
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
    @GET("api/v1/auth/me")
    suspend fun myAccount(@Header("Authorization") authorization: String): AccountInfo

    @HTTP(method = "DELETE", path = "api/v1/auth/me", hasBody = true)
    suspend fun deleteMyAccount(
        @Header("Authorization") authorization: String,
        @Body request: DeleteAccountRequest
    )

    @GET("api/v1/auth/me/quota")
    suspend fun myQuota(@Header("Authorization") authorization: String): TokenQuotaBalance

    @GET("api/v1/admin/users")
    suspend fun adminUsers(@Header("Authorization") authorization: String): List<AdminUser>

    @POST("api/v1/admin/users")
    suspend fun adminCreateUser(@Header("Authorization") authorization: String, @Body request: LoginRequest): AdminUser

    @PATCH("api/v1/admin/users/{userId}/status")
    suspend fun adminSetStatus(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Body request: AdminStatusRequest): AdminUser

    @POST("api/v1/admin/users/{userId}/password")
    suspend fun adminResetPassword(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Body request: AdminPasswordRequest)

    @PUT("api/v1/admin/users/{userId}/quota")
    suspend fun adminSetQuota(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Body request: AdminQuotaRequest): AdminUser

    @GET("api/v1/admin/users/{userId}/quota")
    suspend fun adminUserQuota(@Header("Authorization") authorization: String, @Path("userId") userId: Long): TokenQuotaBalance

    @GET("api/v1/admin/quota/default")
    suspend fun adminDefaultQuota(@Header("Authorization") authorization: String): AdminDefaultQuota

    @PUT("api/v1/admin/quota/default")
    suspend fun adminSetDefaultQuota(@Header("Authorization") authorization: String, @Body request: AdminDefaultQuota): AdminDefaultQuota

    @DELETE("api/v1/admin/users/{userId}")
    suspend fun adminDeleteUser(@Header("Authorization") authorization: String, @Path("userId") userId: Long)

    @GET("api/v1/admin/users/{userId}/trips")
    suspend fun adminTrips(@Header("Authorization") authorization: String, @Path("userId") userId: Long): List<RemoteTrip>

    @POST("api/v1/admin/users/{userId}/trips")
    suspend fun adminCreateTrip(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Body trip: TripRequest): RemoteTripSummary

    @PATCH("api/v1/admin/users/{userId}/trips/{tripId}")
    suspend fun adminUpdateTrip(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("tripId") tripId: Long, @Body trip: TripRequest): RemoteTrip

    @DELETE("api/v1/admin/users/{userId}/trips/{tripId}")
    suspend fun adminDeleteTrip(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("tripId") tripId: Long)

    @POST("api/v1/admin/users/{userId}/trips/{tripId}/records")
    suspend fun adminCreateRecord(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("tripId") tripId: Long, @Body record: RecordRequest): RemoteRecord

    @PATCH("api/v1/admin/users/{userId}/records/{recordId}")
    suspend fun adminUpdateRecord(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("recordId") recordId: Long, @Body record: RecordRequest): RemoteRecord

    @DELETE("api/v1/admin/users/{userId}/records/{recordId}")
    suspend fun adminDeleteRecord(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("recordId") recordId: Long)

    @DELETE("api/v1/admin/users/{userId}/images/{imageId}")
    suspend fun adminDeleteImage(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("imageId") imageId: Long)

    @Multipart
    @POST("api/v1/admin/users/{userId}/records/{recordId}/images")
    suspend fun adminUploadImage(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("recordId") recordId: Long, @Part file: MultipartBody.Part): RemoteImage

    @GET("api/v1/admin/users/{userId}/knowledge")
    suspend fun adminKnowledge(@Header("Authorization") authorization: String, @Path("userId") userId: Long): List<RemoteKnowledge>

    @POST("api/v1/admin/users/{userId}/knowledge")
    suspend fun adminCreateKnowledge(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Body request: KnowledgeRequest): RemoteKnowledge

    @PATCH("api/v1/admin/users/{userId}/knowledge/{entryId}")
    suspend fun adminUpdateKnowledge(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("entryId") entryId: Long, @Body request: KnowledgeRequest): RemoteKnowledge

    @DELETE("api/v1/admin/users/{userId}/knowledge/{entryId}")
    suspend fun adminDeleteKnowledge(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("entryId") entryId: Long)

    @GET("api/v1/admin/users/{userId}/conversations")
    suspend fun adminConversations(@Header("Authorization") authorization: String, @Path("userId") userId: Long): List<RemoteConversation>

    @DELETE("api/v1/admin/users/{userId}/conversations/{conversationId}")
    suspend fun adminDeleteConversation(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("conversationId") conversationId: String)

    @GET("api/v1/admin/users/{userId}/preferences")
    suspend fun adminPreferences(@Header("Authorization") authorization: String, @Path("userId") userId: Long): List<RemotePreference>

    @PUT("api/v1/admin/users/{userId}/preferences/{category}")
    suspend fun adminUpsertPreference(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("category") category: String, @Body request: PreferenceRequest): RemotePreference

    @DELETE("api/v1/admin/users/{userId}/preferences/{category}")
    suspend fun adminDeletePreference(@Header("Authorization") authorization: String, @Path("userId") userId: Long, @Path("category") category: String)

    @GET("api/v1/sync/trips")
    suspend fun syncTrips(
        @Header("Authorization") authorization: String,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int = 50
    ): TripSyncPage

    @GET("api/v1/records/{recordId}/images")
    suspend fun getRecordImages(@Header("Authorization") authorization: String, @Path("recordId") recordId: Long): List<RemoteImage>

    @POST("api/v1/auth/register")
    suspend fun register(@Body request: LoginRequest): Tokens

    @POST("api/v1/auth/logout")
    suspend fun logout(@Header("Authorization") authorization: String)

    @POST("api/v1/auth/password")
    suspend fun changePassword(@Header("Authorization") authorization: String, @Body request: PasswordChangeRequest)

    @GET("api/v1/agent/knowledge")
    suspend fun getKnowledge(
        @Header("Authorization") authorization: String,
        @Query("query") query: String? = null
    ): List<RemoteKnowledge>

    @GET("api/v1/agent/knowledge/{entryId}")
    suspend fun getKnowledgeEntry(
        @Header("Authorization") authorization: String,
        @Path("entryId") entryId: Long
    ): RemoteKnowledge

    @POST("api/v1/agent/knowledge")
    suspend fun createKnowledge(
        @Header("Authorization") authorization: String,
        @Body request: KnowledgeRequest
    ): RemoteKnowledge

    @PATCH("api/v1/agent/knowledge/{entryId}")
    suspend fun updateKnowledge(
        @Header("Authorization") authorization: String,
        @Path("entryId") entryId: Long,
        @Body request: KnowledgeRequest
    ): RemoteKnowledge

    @DELETE("api/v1/agent/knowledge/{entryId}")
    suspend fun deleteKnowledge(
        @Header("Authorization") authorization: String,
        @Path("entryId") entryId: Long
    )

    @POST("api/v1/auth/login")
    suspend fun login(@Body request: LoginRequest): Tokens

    @POST("api/v1/agent/chat")
    suspend fun chat(
        @Header("Authorization") authorization: String,
        @Body request: AgentChatRequest
    ): AgentChatResponse

    @Streaming
    @POST("api/v1/agent/chat/stream")
    suspend fun streamChat(
        @Header("Authorization") authorization: String,
        @Body request: AgentChatRequest
    ): Response<ResponseBody>

    @POST("api/v1/agent/conversations")
    suspend fun createConversation(
        @Header("Authorization") authorization: String
    ): RemoteConversation

    @GET("api/v1/agent/conversations")
    suspend fun getConversations(
        @Header("Authorization") authorization: String
    ): List<RemoteConversation>

    @GET("api/v1/agent/conversations/{conversationId}/messages")
    suspend fun getConversationMessages(
        @Header("Authorization") authorization: String,
        @Path("conversationId") conversationId: String,
        @Query("limit") limit: Int,
        @Query("before_id") beforeId: Long?
    ): List<RemoteConversationMessage>

    @DELETE("api/v1/agent/conversations/{conversationId}")
    suspend fun deleteConversation(
        @Header("Authorization") authorization: String,
        @Path("conversationId") conversationId: String
    )

    @GET("api/v1/agent/preferences")
    suspend fun getPreferences(
        @Header("Authorization") authorization: String
    ): List<RemotePreference>

    @PUT("api/v1/agent/preferences/{category}")
    suspend fun upsertPreference(
        @Header("Authorization") authorization: String,
        @Path("category") category: String,
        @Body request: PreferenceRequest
    ): RemotePreference

    @DELETE("api/v1/agent/preferences/{category}")
    suspend fun deletePreference(
        @Header("Authorization") authorization: String,
        @Path("category") category: String
    )

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
        internal fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(150, TimeUnit.SECONDS)
            .writeTimeout(20, TimeUnit.SECONDS)
            .callTimeout(150, TimeUnit.SECONDS)
            .build()

        fun create(baseUrl: String): FootmarksApi = Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(defaultClient())
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(FootmarksApi::class.java)
    }
}

data class RefreshRequest(@SerializedName("refresh_token") val refreshToken: String)
