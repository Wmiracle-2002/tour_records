package com.miracle.footmarks.ui.screen.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.local.dao.TravelStats
import com.miracle.footmarks.data.repository.TripRepository
import com.miracle.footmarks.data.repository.CloudCoordinator
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.remote.RemotePreference
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

    private val _cloudState = MutableStateFlow(CloudAccountState(isCloudMode = cloud.isCloudMode))
    val cloudState = _cloudState.asStateFlow()

    private val _preferencesState = MutableStateFlow(
        TravelPreferencesState(isLoading = cloud.isCloudMode)
    )
    val preferencesState = _preferencesState.asStateFlow()

    init {
        if (cloud.isCloudMode) loadPreferences()
    }

    fun login(username: String, password: String) {
        viewModelScope.launch {
            _cloudState.value = _cloudState.value.copy(isWorking = true, error = null)
            try {
                cloud.login(username, password)
                _cloudState.value = CloudAccountState(isCloudMode = true, message = "共享记录已更新")
                loadPreferences()
            } catch (error: Exception) {
                _cloudState.value = CloudAccountState(
                    isCloudMode = cloud.isCloudMode, error = error.message ?: "登录或同步失败"
                )
            }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            _cloudState.value = _cloudState.value.copy(isWorking = true, error = null)
            try {
                cloud.refresh()
                _cloudState.value = CloudAccountState(isCloudMode = true, message = "共享记录已更新")
                loadPreferences()
            } catch (error: Exception) {
                _cloudState.value = CloudAccountState(
                    isCloudMode = true, error = error.message ?: "刷新失败"
                )
            }
        }
    }

    fun loadPreferences() {
        if (!cloud.isCloudMode) return
        viewModelScope.launch {
            _preferencesState.value = _preferencesState.value.copy(
                isLoading = true, error = null, message = null
            )
            try {
                _preferencesState.value = TravelPreferencesState(
                    items = session.getPreferences()
                )
            } catch (error: Exception) {
                _preferencesState.value = _preferencesState.value.copy(
                    isLoading = false, error = error.message ?: "读取旅行偏好失败"
                )
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
