package com.miracle.footmarks.ui.screen.profile

import androidx.lifecycle.ViewModel
import android.net.Uri
import com.miracle.footmarks.data.local.util.PhotoManager
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.remote.AdminUser
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.remote.RemoteTrip
import com.miracle.footmarks.data.remote.TripRequest
import com.miracle.footmarks.data.remote.RecordRequest
import com.miracle.footmarks.data.remote.RemoteKnowledge
import com.miracle.footmarks.data.remote.RemoteConversation
import com.miracle.footmarks.data.remote.RemotePreference
import com.miracle.footmarks.data.remote.KnowledgeRequest
import com.miracle.footmarks.data.remote.TokenQuotaBalance
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class AdminState(
    val users: List<AdminUser> = emptyList(),
    val selectedUserId: Long? = null,
    val trips: List<RemoteTrip> = emptyList(),
    val knowledge: List<RemoteKnowledge> = emptyList(),
    val conversations: List<RemoteConversation> = emptyList(),
    val preferences: List<RemotePreference> = emptyList(),
    val defaultQuota: Int? = null,
    val selectedQuota: TokenQuotaBalance? = null,
    val working: Boolean = false,
    val error: String? = null,
    val message: String? = null
)

@HiltViewModel
class AdminViewModel @Inject constructor(
    private val session: CloudSession,
    private val photoManager: PhotoManager,
) : ViewModel() {
    private val _state = MutableStateFlow(AdminState())
    val state = _state.asStateFlow()

    init { load() }

    fun load() = perform("账号列表已更新") {
        _state.value = _state.value.copy(users = session.adminUsers())
        _state.value = _state.value.copy(defaultQuota = session.adminDefaultQuota())
        _state.value.selectedUserId?.let { loadContent(it) }
    }

    fun select(userId: Long) = perform("数据已加载") {
        _state.value = _state.value.copy(selectedUserId = userId)
        loadContent(userId)
    }

    fun createUser(username: String, password: String) = perform("账号已创建") {
        session.adminCreateUser(username, password)
        _state.value = _state.value.copy(users = session.adminUsers())
    }

    fun setStatus(userId: Long, status: String) = perform("账号状态已更新") {
        session.adminSetStatus(userId, status)
        _state.value = _state.value.copy(users = session.adminUsers())
    }

    fun resetPassword(userId: Long, password: String) = perform("临时密码已设置") {
        session.adminResetPassword(userId, password)
    }

    fun setQuota(userId: Long, limit: Int?) = perform("月度额度已更新") {
        session.adminSetQuota(userId, limit)
        _state.value = _state.value.copy(users = session.adminUsers())
    }

    fun setDefaultQuota(limit: Int) = perform("新账号默认额度已更新") {
        _state.value = _state.value.copy(defaultQuota = session.adminSetDefaultQuota(limit))
    }

    fun deleteUser(userId: Long) = perform("账号已删除") {
        session.adminDeleteUser(userId)
        _state.value = _state.value.copy(
            users = session.adminUsers(), selectedUserId = null, trips = emptyList()
        )
    }

    fun createTrip(userId: Long, trip: TripRequest) = perform("旅行已添加") {
        session.adminCreateTrip(userId, trip)
        _state.value = _state.value.copy(trips = session.adminTrips(userId))
    }

    fun updateTrip(userId: Long, tripId: Long, trip: TripRequest) = perform("旅行已更新") {
        session.adminUpdateTrip(userId, tripId, trip)
        _state.value = _state.value.copy(trips = session.adminTrips(userId))
    }

    fun deleteTrip(userId: Long, tripId: Long) = perform("旅行已删除") {
        session.adminDeleteTrip(userId, tripId)
        _state.value = _state.value.copy(trips = session.adminTrips(userId))
    }

    fun createRecord(userId: Long, tripId: Long, record: RecordRequest) = perform("记录已添加") {
        session.adminCreateRecord(userId, tripId, record)
        _state.value = _state.value.copy(trips = session.adminTrips(userId))
    }

    fun updateRecord(userId: Long, recordId: Long, record: RecordRequest) = perform("记录已更新") {
        session.adminUpdateRecord(userId, recordId, record)
        _state.value = _state.value.copy(trips = session.adminTrips(userId))
    }

    fun deleteRecord(userId: Long, recordId: Long) = perform("记录已删除") {
        session.adminDeleteRecord(userId, recordId)
        _state.value = _state.value.copy(trips = session.adminTrips(userId))
    }

    fun deleteImage(userId: Long, imageId: Long) = perform("照片已删除") {
        session.adminDeleteImage(userId, imageId)
        _state.value = _state.value.copy(trips = session.adminTrips(userId))
    }

    fun uploadImage(userId: Long, recordId: Long, uri: Uri) = perform("照片已上传") {
        val part = requireNotNull(photoManager.createOriginalUploadPart(uri)) { "请选择图片" }
        session.adminUploadImage(userId, recordId, part)
        _state.value = _state.value.copy(trips = session.adminTrips(userId))
    }

    fun saveKnowledge(userId: Long, entryId: Long?, request: KnowledgeRequest) = perform("收藏已保存") {
        if (entryId == null) session.adminCreateKnowledge(userId, request)
        else session.adminUpdateKnowledge(userId, entryId, request)
        _state.value = _state.value.copy(knowledge = session.adminKnowledge(userId))
    }

    fun deleteKnowledge(userId: Long, entryId: Long) = perform("收藏已删除") {
        session.adminDeleteKnowledge(userId, entryId)
        _state.value = _state.value.copy(knowledge = session.adminKnowledge(userId))
    }

    fun deleteConversation(userId: Long, conversationId: String) = perform("会话已删除") {
        session.adminDeleteConversation(userId, conversationId)
        _state.value = _state.value.copy(conversations = session.adminConversations(userId))
    }

    fun savePreference(userId: Long, category: String, content: String) = perform("偏好已保存") {
        session.adminUpsertPreference(userId, category, content)
        _state.value = _state.value.copy(preferences = session.adminPreferences(userId))
    }

    fun deletePreference(userId: Long, category: String) = perform("偏好已删除") {
        session.adminDeletePreference(userId, category)
        _state.value = _state.value.copy(preferences = session.adminPreferences(userId))
    }

    private suspend fun loadContent(userId: Long) {
        val trips = session.adminTrips(userId)
        val knowledge = session.adminKnowledge(userId)
        val conversations = session.adminConversations(userId)
        val preferences = session.adminPreferences(userId)
        val quota = session.adminUserQuota(userId)
        if (_state.value.selectedUserId == userId) {
            _state.value = _state.value.copy(
                trips = trips, knowledge = knowledge,
                conversations = conversations, preferences = preferences,
                selectedQuota = quota,
            )
        }
    }

    private fun perform(success: String, block: suspend () -> Unit) {
        viewModelScope.launch {
            _state.value = _state.value.copy(working = true, error = null, message = null)
            try {
                block()
                _state.value = _state.value.copy(working = false, message = success)
            } catch (error: Exception) {
                _state.value = _state.value.copy(working = false, error = error.message ?: "操作失败")
            }
        }
    }
}
