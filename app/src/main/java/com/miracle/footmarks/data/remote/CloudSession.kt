package com.miracle.footmarks.data.remote

import android.content.Context
import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.withContext
import dagger.hilt.android.qualifiers.ApplicationContext
import okhttp3.MultipartBody
import retrofit2.HttpException
import java.io.IOException
import javax.inject.Inject

interface TokenStore {
    var tokens: Tokens?
}

data class AgentStreamEvent(
    val name: String,
    @SerializedName("request_id") val requestId: String,
    val message: String? = null,
    val text: String? = null,
    val answer: String? = null,
    @SerializedName("conversation_id") val conversationId: String? = null
)

private data class StreamPayload(
    @SerializedName("request_id") val requestId: String = "",
    val message: String? = null,
    val text: String? = null,
    val answer: String? = null,
    @SerializedName("conversation_id") val conversationId: String? = null
)

class PreferencesTokenStore @Inject constructor(
    @ApplicationContext context: Context
) : TokenStore {
    private val preferences = context.getSharedPreferences("cloud_session", Context.MODE_PRIVATE)

    override var tokens: Tokens?
        get() {
            val access = preferences.getString("access", null) ?: return null
            val refresh = preferences.getString("refresh", null) ?: return null
            return Tokens(access, refresh)
        }
        set(value) {
            preferences.edit().apply {
                if (value == null) clear()
                else putString("access", value.accessToken).putString("refresh", value.refreshToken)
            }.apply()
        }
}

class CloudSession @Inject constructor(
    private val api: FootmarksApi,
    private val store: TokenStore
) {
    val isCloudMode: Boolean get() = store.tokens != null
    internal var streamDispatcher: CoroutineDispatcher = Dispatchers.IO

    suspend fun login(username: String, password: String) {
        store.tokens = api.login(LoginRequest(username, password))
    }

    suspend fun askAgent(
        message: String,
        conversationId: String? = null,
        clientMessageId: String? = null
    ): AgentChatResponse = authorized {
        api.chat(it, AgentChatRequest(message, conversationId, clientMessageId))
    }

    suspend fun streamAgent(
        message: String,
        conversationId: String,
        clientMessageId: String,
        onEvent: (AgentStreamEvent) -> Unit
    ): AgentChatResponse = authorized { authorization ->
        val response = api.streamChat(
            authorization, AgentChatRequest(message, conversationId, clientMessageId)
        )
        if (!response.isSuccessful) throw HttpException(response)
        val body = response.body() ?: throw IOException("流式响应为空")
        var completed: AgentChatResponse? = null
        val callerContext = currentCoroutineContext()
        val gson = Gson()
        withContext(streamDispatcher) {
            body.use { content ->
                content.charStream().buffered().use { reader ->
                    var name: String? = null
                    var data: String? = null
                    while (true) {
                        val line = reader.readLine() ?: break
                        if (line.isEmpty()) {
                            if (name != null && data != null) {
                                val payload = gson.fromJson(data, StreamPayload::class.java)
                                val event = AgentStreamEvent(
                                    name, payload.requestId, payload.message, payload.text,
                                    payload.answer, payload.conversationId
                                )
                                withContext(callerContext) { onEvent(event) }
                                when (name) {
                                    "completed" -> {
                                        completed = AgentChatResponse(
                                            payload.requestId,
                                            payload.answer ?: throw IOException("缺少最终回答"),
                                            payload.conversationId
                                        )
                                        break
                                    }
                                    "error" -> throw IOException(payload.message ?: "智能规划请求失败")
                                }
                            }
                            name = null
                            data = null
                        } else if (line.startsWith("event: ")) {
                            name = line.removePrefix("event: ")
                        } else if (line.startsWith("data: ")) {
                            data = line.removePrefix("data: ")
                        }
                    }
                }
            }
        }
        completed ?: throw IOException("流式响应中断，请稍后重试")
    }

    suspend fun createConversation(): RemoteConversation =
        authorized { api.createConversation(it) }

    suspend fun getConversations(): List<RemoteConversation> =
        authorized { api.getConversations(it) }

    suspend fun getConversationMessages(
        conversationId: String,
        limit: Int = 200,
        beforeId: Long? = null
    ): List<RemoteConversationMessage> = authorized {
        api.getConversationMessages(it, conversationId, limit, beforeId)
    }

    suspend fun deleteConversation(conversationId: String) =
        authorized { api.deleteConversation(it, conversationId) }

    suspend fun getPreferences(): List<RemotePreference> =
        authorized { api.getPreferences(it) }

    suspend fun upsertPreference(category: String, content: String): RemotePreference =
        authorized { api.upsertPreference(it, category, PreferenceRequest(content)) }

    suspend fun deletePreference(category: String) =
        authorized { api.deletePreference(it, category) }

    suspend fun getTrips(): List<RemoteTrip> = authorized { api.getTrips(it) }

    suspend fun createTrip(trip: TripRequest): RemoteTripSummary =
        authorized { api.createTrip(it, trip) }

    suspend fun createRecord(tripId: Long, record: RecordRequest): RemoteRecord =
        authorized { api.createRecord(it, tripId, record) }

    suspend fun updateTrip(tripId: Long, trip: TripRequest): RemoteTrip =
        authorized { api.updateTrip(it, tripId, trip) }

    suspend fun updateRecord(recordId: Long, record: RecordRequest): RemoteRecord =
        authorized { api.updateRecord(it, recordId, record) }

    suspend fun deleteRecord(recordId: Long) = authorized { api.deleteRecord(it, recordId) }

    suspend fun deleteTrip(tripId: Long) = authorized { api.deleteTrip(it, tripId) }

    suspend fun uploadImage(recordId: Long, file: MultipartBody.Part): RemoteImage =
        authorized { api.uploadImage(it, recordId, file) }

    suspend fun getImages(recordId: Long): List<RemoteImage> =
        authorized { api.getImages(it, recordId) }

    suspend fun deleteImage(imageId: Long) = authorized { api.deleteImage(it, imageId) }

    private suspend fun <T> authorized(block: suspend (String) -> T): T {
        val tokens = requireNotNull(store.tokens) { "请先在个人中心登录" }
        try {
            return block("Bearer ${tokens.accessToken}")
        } catch (error: HttpException) {
            if (error.code() != 401) throw error
        }
        val updated = api.refresh(RefreshRequest(tokens.refreshToken))
        store.tokens = updated
        return block("Bearer ${updated.accessToken}")
    }
}
