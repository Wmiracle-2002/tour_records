package com.miracle.footmarks.ui.screen.recorddetail

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.repository.CityRepository
import com.miracle.footmarks.data.repository.RecordRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class RecordDetailUiState(
    val record: RecordEntity? = null,
    val city: CityEntity? = null,
    val isLoading: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class RecordDetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val recordRepository: RecordRepository,
    private val cityRepository: CityRepository
) : ViewModel() {

    private val recordId: Long = savedStateHandle.get<Long>("recordId") ?: 0L

    private val _uiState = MutableStateFlow(RecordDetailUiState())
    val uiState: StateFlow<RecordDetailUiState> = _uiState.asStateFlow()

    init {
        loadRecord()
    }

    private fun loadRecord() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true)
            try {
                val record = recordRepository.getRecordById(recordId)
                if (record != null) {
                    val city = cityRepository.getCityById(record.cityId)
                    _uiState.value = RecordDetailUiState(
                        record = record,
                        city = city,
                        isLoading = false
                    )
                } else {
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        error = "记录不存在"
                    )
                }
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    error = e.message
                )
            }
        }
    }

    fun deleteRecord(onSuccess: () -> Unit) {
        viewModelScope.launch {
            _uiState.value.record?.let { record ->
                try {
                    recordRepository.deleteRecord(record)
                    onSuccess()
                } catch (e: Exception) {
                    _uiState.value = _uiState.value.copy(error = "删除失败: ${e.message}")
                }
            }
        }
    }
}
