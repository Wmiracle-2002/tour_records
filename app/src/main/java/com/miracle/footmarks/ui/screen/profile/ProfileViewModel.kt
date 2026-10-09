package com.miracle.footmarks.ui.screen.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.local.dao.TravelStats
import com.miracle.footmarks.data.repository.TripRepository
import com.miracle.footmarks.data.repository.CloudCoordinator
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.remote.RemotePreference
import com.miracle.footmarks.data.remote.TokenQuotaBalance
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ProfileUiState(
    val stats: TravelStats = TravelStats(cityCount = 0, tripCount = 0, totalCost = 0f),
    val isLoading: Boolean = true
)

data class CloudAccountState(
    val isCloudMode: Boolean = false,
    val role: String? = null,
    val username: String? = null,
    val requiresPasswordChange: Boolean = false,
    val quota: TokenQuotaBalance? = null,
    val isWorking: Boolean = false,
    val message: String? = null,
    val error: String? = null
)

data class TravelPreferencesState(
    val items: List<RemotePreference> = emptyList(),
    val isLoading: Boolean = false,
    val isWorking: Boolean = false,
    val message: String? = null,
    val error: String? = null
)

@HiltViewModel
class ProfileViewModel @Inject constructor(
    repository: TripRepository,
    private val cloud: CloudCoordinator,
    private val session: CloudSession
) : ViewModel() {

    private val _cloudState = MutableStateFlow(CloudAccountState(
        isCloudMode = cloud.isCloudMode, role = session.accountRole,
        username = session.accountUsername,
        requiresPasswordChange = session.requiresPasswordChange,
    ))
    val cloudState = _cloudState.asStateFlow()
    val rememberedUsername: String? get() = session.rememberedUsername
    private var keepSignedIn = true
    private var rememberUsername = false

    fun setLoginOptions(keep: Boolean, remember: Boolean) {
        keepSignedIn = keep
        rememberUsername = remember
    }

    fun prepareLogin() {
        _cloudState.value = _cloudState.value.copy(message = null, error = null)
    }

    private val _preferencesState = MutableStateFlow(
        TravelPreferencesState(isLoading = cloud.isCloudMode)
    )
    val preferencesState = _preferencesState.asStateFlow()

    init {
        if (cloud.isCloudMode && session.accountRole != "admin") {
            loadAccountName()
            loadPreferences()
            loadQuota()
        }
    }

    fun login(username: String, password: String) {
        viewModelScope.launch {
            _cloudState.value = _cloudState.value.copy(isWorking = true, error = null)
            _preferencesState.value = TravelPreferencesState()
            try {
                cloud.login(username, password, keepSignedIn, rememberUsername)
                _cloudState.value = CloudAccountState(
                    isCloudMode = true, role = session.accountRole,
                    username = session.accountUsername,
                    requiresPasswordChange = session.requiresPasswordChange,
                    message = if (session.requiresPasswordChange) "请先修改临时密码" else "旅行记录已更新",
                )
                loadPreferences()
                loadQuota()
                loadAccountName()
            } catch (error: Exception) {
                _cloudState.value = CloudAccountState(
                    isCloudMode = cloud.isCloudMode, role = session.accountRole,
                    username = session.accountUsername, error = error.message ?: "登录或同步失败"
                )
            }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            _cloudState.value = _cloudState.value.copy(isWorking = true, error = null)
            try {
                cloud.refresh()
                _cloudState.value = CloudAccountState(isCloudMode = true, role = session.accountRole,
                    username = session.accountUsername, message = "旅行记录已更新")
                loadPreferences()
                loadQuota()
                loadAccountName()
            } catch (error: Exception) {
                _cloudState.value = CloudAccountState(
                    isCloudMode = true, role = session.accountRole,
                    username = session.accountUsername, error = error.message ?: "刷新失败"
                )
            }
        }
    }

    fun register(username: String, password: String) {
        viewModelScope.launch {
            _cloudState.value = _cloudState.value.copy(isWorking = true, error = null)
            try {
                cloud.register(username, password, keepSignedIn, rememberUsername)
                _cloudState.value = CloudAccountState(isCloudMode = true, role = session.accountRole,
                    username = session.accountUsername, message = "注册成功")
                loadQuota()
                loadAccountName()
            } catch (error: Exception) {
                _cloudState.value = CloudAccountState(
                    isCloudMode = cloud.isCloudMode, role = session.accountRole,
                    username = session.accountUsername,
                    error = error.message ?: "注册失败"
                )
            }
        }
    }

    fun logout() {
        viewModelScope.launch {
            _cloudState.value = _cloudState.value.copy(isWorking = true, error = null)
            try {
                cloud.logout()
                _preferencesState.value = TravelPreferencesState()
                _cloudState.value = CloudAccountState(message = "已退出登录")
            } catch (error: Exception) {
                _cloudState.value = CloudAccountState(error = error.message ?: "退出登录失败")
            }
        }
    }

    fun changePassword(currentPassword: String, newPassword: String) {
        viewModelScope.launch {
            _cloudState.value = _cloudState.value.copy(isWorking = true, error = null)
            try {
                cloud.changePassword(currentPassword, newPassword)
                _preferencesState.value = TravelPreferencesState()
                _cloudState.value = CloudAccountState(message = "密码已修改，请重新登录")
            } catch (error: Exception) {
                _cloudState.value = _cloudState.value.copy(
                    isWorking = false, error = error.message ?: "修改密码失败"
                )
            }
        }
    }

    fun deleteMyAccount(password: String) {
        viewModelScope.launch {
            _cloudState.value = _cloudState.value.copy(isWorking = true, error = null)
            try {
                cloud.deleteMyAccount(password)
                _preferencesState.value = TravelPreferencesState()
                _cloudState.value = CloudAccountState(message = "账号已注销")
            } catch (error: Exception) {
                _cloudState.value = _cloudState.value.copy(
                    isWorking = false, error = error.message ?: "注销失败"
                )
            }
        }
    }

    fun loadQuota() {
        if (!cloud.isCloudMode || session.accountRole == "admin") return
        val accountId = session.accountId
        viewModelScope.launch {
            runCatching { session.myQuota() }.onSuccess { balance ->
                if (session.accountId == accountId) {
                    _cloudState.value = _cloudState.value.copy(quota = balance)
                }
            }
        }
    }

    private fun loadAccountName() {
        if (!cloud.isCloudMode || session.accountRole == "admin") return
        val accountId = session.accountId
        viewModelScope.launch {
            runCatching { session.resolveAccountUsername() }.onSuccess { username ->
                if (session.accountId == accountId && _cloudState.value.isCloudMode) {
                    _cloudState.value = _cloudState.value.copy(username = username)
                }
            }
        }
    }

    fun loadPreferences() {
        if (!cloud.isCloudMode) return
        val accountId = session.accountId
        viewModelScope.launch {
            _preferencesState.value = _preferencesState.value.copy(
                isLoading = true, error = null, message = null
            )
            try {
                val items = session.getPreferences()
                if (session.accountId == accountId) {
                    _preferencesState.value = TravelPreferencesState(items = items)
                }
            } catch (error: Exception) {
                if (session.accountId == accountId) {
                    _preferencesState.value = _preferencesState.value.copy(
                        isLoading = false, error = error.message ?: "读取旅行偏好失败"
                    )
                }
            }
        }
    }

    fun savePreference(category: String, content: String) {
        viewModelScope.launch {
            _preferencesState.value = _preferencesState.value.copy(
                isWorking = true, error = null, message = null
            )
            try {
                session.upsertPreference(category, content.trim())
                _preferencesState.value = TravelPreferencesState(
                    items = session.getPreferences(), message = "旅行偏好已保存"
                )
            } catch (error: Exception) {
                _preferencesState.value = _preferencesState.value.copy(
                    isWorking = false, error = error.message ?: "保存旅行偏好失败"
                )
            }
        }
    }

    fun deletePreference(category: String) {
        viewModelScope.launch {
            _preferencesState.value = _preferencesState.value.copy(
                isWorking = true, error = null, message = null
            )
            try {
                session.deletePreference(category)
                _preferencesState.value = TravelPreferencesState(
                    items = session.getPreferences(), message = "旅行偏好已删除"
                )
            } catch (error: Exception) {
                _preferencesState.value = _preferencesState.value.copy(
                    isWorking = false, error = error.message ?: "删除旅行偏好失败"
                )
            }
        }
    }

    val uiState = repository.getTravelStats()
        .map { ProfileUiState(stats = it, isLoading = false) }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = ProfileUiState()
        )
}
