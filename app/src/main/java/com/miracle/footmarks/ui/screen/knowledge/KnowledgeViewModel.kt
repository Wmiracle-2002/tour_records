package com.miracle.footmarks.ui.screen.knowledge

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.remote.KnowledgeRequest
import com.miracle.footmarks.data.remote.RemoteKnowledge
import com.miracle.footmarks.data.repository.AdministrativeDivisionRepository
import com.miracle.footmarks.data.repository.AdministrativeLocation
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class KnowledgeUiState(
    val entries: List<RemoteKnowledge> = emptyList(),
    val selected: RemoteKnowledge? = null,
    val isLoading: Boolean = false,
    val isSaving: Boolean = false,
    val savedCount: Int = 0,
    val error: String? = null
)

@HiltViewModel
class KnowledgeViewModel @Inject constructor(
    private val session: CloudSession,
    private val divisions: AdministrativeDivisionRepository
) : ViewModel() {
    private val _uiState = MutableStateFlow(KnowledgeUiState())
    val uiState = _uiState.asStateFlow()
    val isCloudMode: Boolean get() = session.isCloudMode

    init {
        if (session.isCloudMode) refresh()
    }

    fun searchCities(query: String): List<AdministrativeLocation> =
        if (query.isBlank()) emptyList() else divisions.search(query).take(8)

    fun refresh(query: String? = null) {
        if (!session.isCloudMode) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, error = null)
            try {
                _uiState.value = _uiState.value.copy(
                    entries = session.getKnowledge(query?.takeIf { it.isNotBlank() }),
                    isLoading = false
                )
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(
                    isLoading = false, error = error.message ?: "读取收藏失败"
                )
            }
        }
    }

    fun open(entryId: Long) {
        viewModelScope.launch {
            try {
                _uiState.value = _uiState.value.copy(selected = session.getKnowledgeEntry(entryId))
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(error = error.message ?: "收藏已不存在")
            }
        }
    }

    fun close() {
        _uiState.value = _uiState.value.copy(selected = null)
    }

    fun save(entryId: Long?, request: KnowledgeRequest) {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isSaving = true, error = null)
            try {
                if (entryId == null) session.createKnowledge(request)
                else session.updateKnowledge(entryId, request)
                _uiState.value = _uiState.value.copy(
                    selected = null, isSaving = false,
                    savedCount = _uiState.value.savedCount + 1
                )
                refresh()
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(
                    isSaving = false, error = error.message ?: "保存收藏失败"
                )
            }
        }
    }

    fun delete(entryId: Long) {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isSaving = true, error = null)
            try {
                session.deleteKnowledge(entryId)
                _uiState.value = _uiState.value.copy(selected = null, isSaving = false)
                refresh()
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(
                    isSaving = false, error = error.message ?: "删除收藏失败"
                )
            }
        }
    }
}
