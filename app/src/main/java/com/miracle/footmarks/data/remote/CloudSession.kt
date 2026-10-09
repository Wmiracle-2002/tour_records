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
    var keepSignedIn: Boolean
        get() = true
        set(_) {}
    var rememberedUsername: String?
        get() = null
        set(_) {}
}

data class AgentStreamEvent(
    val name: String,
    @SerializedName("request_id") val requestId: String,
    val message: String? = null,
    val text: String? = null,
    val answer: String? = null,
    @SerializedName("conversation_id") val conversationId: String? = null,
    val stage: String? = null,
    val status: String? = null
)

private data class StreamPayload(
    @SerializedName("request_id") val requestId: String = "",
    val message: String? = null,
    val text: String? = null,
    val answer: String? = null,
    @SerializedName("conversation_id") val conversationId: String? = null,
    val stage: String? = null,
    val status: String? = null
)

class PreferencesTokenStore @Inject constructor(
    @ApplicationContext context: Context
) : TokenStore {
    private val preferences = context.getSharedPreferences("cloud_session", Context.MODE_PRIVATE)
    private val cipher = TokenCipher()
    private var temporaryTokens: Tokens? = null

    override var keepSignedIn: Boolean = true
        set(value) {
            field = value
            if (!value) preferences.edit().remove("session_blob").remove("access").remove("refresh")
                .remove("user_id").remove("role").apply()
        }

    override var rememberedUsername: String?
        get() = preferences.getString("remembered_username", null)
        set(value) {
            preferences.edit().apply {
                if (value == null) remove("remembered_username")
                else putString("remembered_username", value)
            }.apply()
        }

    override var tokens: Tokens?
        get() {
            if (temporaryTokens != null) return temporaryTokens
            val encrypted = preferences.getString("session_blob", null) ?: return null
            return try {
                Gson().fromJson(cipher.decrypt(encrypted), Tokens::class.java)
            } catch (_: Exception) {
                preferences.edit().remove("session_blob").apply()
                null
            }
        }
        set(value) {
            temporaryTokens = if (keepSignedIn) null else value
            preferences.edit().apply {
                if (value == null) {
                    remove("session_blob").remove("access").remove("refresh").remove("user_id").remove("role")
                }
                else if (!keepSignedIn) {
                    remove("session_blob").remove("access").remove("refresh").remove("user_id").remove("role")
                }
                else {
                    putString("session_blob", cipher.encrypt(Gson().toJson(value)))
                    remove("access").remove("refresh").remove("user_id").remove("role")
                }
            }.apply()
        }
}

class CloudSession @Inject constructor(
    private val api: FootmarksApi,
    private val store: TokenStore
) {
    val isCloudMode: Boolean get() = store.tokens != null
    val accountId: Long? get() = store.tokens?.userId
    val accountRole: String? get() = store.tokens?.role
    val accountUsername: String? get() = store.tokens?.username

    suspend fun resolveAccountUsername(): String? {
        accountUsername?.takeIf { it.isNotBlank() }?.let { return it }
        val account = authorized { api.myAccount(it) }
        val current = store.tokens ?: return null
        if (current.userId != null && current.userId != account.id) return null
        store.tokens = current.copy(username = account.username)
        return account.username
    }
    val requiresPasswordChange: Boolean get() = store.tokens?.requiresPasswordChange == true
    internal var streamDispatcher: CoroutineDispatcher = Dispatchers.IO

    val rememberedUsername: String? get() = store.rememberedUsername

    suspend fun login(username: String, password: String, keepSignedIn: Boolean = true, rememberUsername: Boolean = false) {
        store.keepSignedIn = keepSignedIn
        store.rememberedUsername = username.takeIf { rememberUsername }
        store.tokens = api.login(LoginRequest(username, password)).copy(username = username)
    }

    suspend fun register(username: String, password: String, keepSignedIn: Boolean = true, rememberUsername: Boolean = false) {
        store.keepSignedIn = keepSignedIn
        store.rememberedUsername = username.takeIf { rememberUsername }
        store.tokens = api.register(LoginRequest(username, password)).copy(username = username)
    }

    suspend fun logout() {
        try {
            authorized { api.logout(it) }
        } finally {
            store.tokens = null
        }
    }

    suspend fun changePassword(currentPassword: String, newPassword: String) {
        authorized { api.changePassword(it, PasswordChangeRequest(currentPassword, newPassword)) }
        store.tokens = null
    }

    suspend fun syncTrips(cursor: String?): TripSyncPage = authorized {
        api.syncTrips(it, cursor)
    }

    suspend fun recordImages(recordId: Long): List<RemoteImage> = authorized { api.getRecordImages(it, recordId) }

    suspend fun myQuota(): TokenQuotaBalance = authorized { api.myQuota(it) }

    suspend fun deleteMyAccount(password: String) {
        authorized { api.deleteMyAccount(it, DeleteAccountRequest(password)) }
        store.tokens = null
    }

    suspend fun adminUsers(): List<AdminUser> = authorized { api.adminUsers(it) }
    suspend fun adminCreateUser(username: String, password: String): AdminUser =
        authorized { api.adminCreateUser(it, LoginRequest(username, password)) }
    suspend fun adminSetStatus(userId: Long, status: String): AdminUser =
        authorized { api.adminSetStatus(it, userId, AdminStatusRequest(status)) }
    suspend fun adminResetPassword(userId: Long, password: String) =
        authorized { api.adminResetPassword(it, userId, AdminPasswordRequest(password)) }
    suspend fun adminSetQuota(userId: Long, limit: Int?): AdminUser =
        authorized { api.adminSetQuota(it, userId, AdminQuotaRequest(limit)) }
    suspend fun adminUserQuota(userId: Long) = authorized { api.adminUserQuota(it, userId) }
    suspend fun adminDefaultQuota(): Int = authorized { api.adminDefaultQuota(it).limit }
    suspend fun adminSetDefaultQuota(limit: Int): Int =
        authorized { api.adminSetDefaultQuota(it, AdminDefaultQuota(limit)).limit }
    suspend fun adminDeleteUser(userId: Long) = authorized { api.adminDeleteUser(it, userId) }
    suspend fun adminTrips(userId: Long): List<RemoteTrip> = authorized { api.adminTrips(it, userId) }
    suspend fun adminCreateTrip(userId: Long, trip: TripRequest): RemoteTripSummary =
        authorized { api.adminCreateTrip(it, userId, trip) }
    suspend fun adminUpdateTrip(userId: Long, tripId: Long, trip: TripRequest): RemoteTrip =
        authorized { api.adminUpdateTrip(it, userId, tripId, trip) }
    suspend fun adminDeleteTrip(userId: Long, tripId: Long) =
        authorized { api.adminDeleteTrip(it, userId, tripId) }
    suspend fun adminCreateRecord(userId: Long, tripId: Long, record: RecordRequest) =
        authorized { api.adminCreateRecord(it, userId, tripId, record) }
    suspend fun adminUpdateRecord(userId: Long, recordId: Long, record: RecordRequest) =
        authorized { api.adminUpdateRecord(it, userId, recordId, record) }
    suspend fun adminDeleteRecord(userId: Long, recordId: Long) =
        authorized { api.adminDeleteRecord(it, userId, recordId) }
    suspend fun adminDeleteImage(userId: Long, imageId: Long) =
        authorized { api.adminDeleteImage(it, userId, imageId) }
    suspend fun adminUploadImage(userId: Long, recordId: Long, file: MultipartBody.Part) =
        authorized { api.adminUploadImage(it, userId, recordId, file) }
    suspend fun adminKnowledge(userId: Long) = authorized { api.adminKnowledge(it, userId) }
    suspend fun adminCreateKnowledge(userId: Long, request: KnowledgeRequest) =
        authorized { api.adminCreateKnowledge(it, userId, request) }
    suspend fun adminUpdateKnowledge(userId: Long, entryId: Long, request: KnowledgeRequest) =
        authorized { api.adminUpdateKnowledge(it, userId, entryId, request) }
    suspend fun adminDeleteKnowledge(userId: Long, entryId: Long) =
        authorized { api.adminDeleteKnowledge(it, userId, entryId) }
    suspend fun adminConversations(userId: Long) = authorized { api.adminConversations(it, userId) }
    suspend fun adminDeleteConversation(userId: Long, conversationId: String) =
        authorized { api.adminDeleteConversation(it, userId, conversationId) }
    suspend fun adminPreferences(userId: Long) = authorized { api.adminPreferences(it, userId) }
    suspend fun adminUpsertPreference(userId: Long, category: String, content: String) =
        authorized { api.adminUpsertPreference(it, userId, category, PreferenceRequest(content)) }
    suspend fun adminDeletePreference(userId: Long, category: String) =
        authorized { api.adminDeletePreference(it, userId, category) }

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
                                    payload.answer, payload.conversationId, payload.stage, payload.status
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

    suspend fun getKnowledge(query: String? = null): List<RemoteKnowledge> =
        authorized { api.getKnowledge(it, query) }

    suspend fun getKnowledgeEntry(entryId: Long): RemoteKnowledge =
        authorized { api.getKnowledgeEntry(it, entryId) }

    suspend fun getKnowledgeDistricts(cityCode: String): List<KnowledgeDistrict> =
        authorized { api.getKnowledgeDistricts(it, cityCode) }

    suspend fun createKnowledge(request: KnowledgeRequest): RemoteKnowledge =
        authorized { api.createKnowledge(it, request) }

    suspend fun updateKnowledge(entryId: Long, request: KnowledgeRequest): RemoteKnowledge =
        authorized { api.updateKnowledge(it, entryId, request) }

    suspend fun deleteKnowledge(entryId: Long) =
        authorized { api.deleteKnowledge(it, entryId) }

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
            val result = block("Bearer ${tokens.accessToken}")
            check(sameAccount(tokens)) { "账号已切换，请重试" }
            return result
        } catch (error: HttpException) {
            if (error.code() != 401) throw error
        }
        val updated = api.refresh(RefreshRequest(tokens.refreshToken)).copy(username = tokens.username)
        check(store.tokens == tokens) { "账号已切换，请重试" }
        store.tokens = updated
        val result = block("Bearer ${updated.accessToken}")
        check(sameAccount(updated)) { "账号已切换，请重试" }
        return result
    }

    private fun sameAccount(expected: Tokens): Boolean {
        val current = store.tokens ?: return false
        return if (expected.userId != null) current.userId == expected.userId else current == expected
    }
}
