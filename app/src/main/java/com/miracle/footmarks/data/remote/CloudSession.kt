package com.miracle.footmarks.data.remote

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import retrofit2.HttpException
import javax.inject.Inject

interface TokenStore {
    var tokens: Tokens?
}

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

    suspend fun login(username: String, password: String) {
        store.tokens = api.login(LoginRequest(username, password))
    }

    suspend fun askAgent(message: String): AgentChatResponse =
        authorized { api.chat(it, AgentChatRequest(message)) }

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
