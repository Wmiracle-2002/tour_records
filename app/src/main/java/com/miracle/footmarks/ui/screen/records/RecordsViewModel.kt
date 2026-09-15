package com.miracle.footmarks.ui.screen.records

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.repository.RecordRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class RecordsUiState(
    val records: List<RecordEntity> = emptyList(),
    val isLoading: Boolean = false
)

@HiltViewModel
class RecordsViewModel @Inject constructor(
    private val repository: RecordRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(RecordsUiState())
    val uiState: StateFlow<RecordsUiState> = _uiState.asStateFlow()

    init {
        loadRecords()
    }

    private fun loadRecords() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true)
            repository.getAllRecords().collect { records ->
                _uiState.value = RecordsUiState(
                    records = records.sortedByDescending { it.date },
                    isLoading = false
                )
            }
        }
    }
}
