package com.miracle.footmarks.ui.screen.addrecord

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.repository.CityRepository
import com.miracle.footmarks.data.repository.RecordRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.LocalDate
import javax.inject.Inject

data class AddRecordUiState(
    val recordType: RecordType = RecordType.ATTRACTION,
    val cityId: Long? = null,
    val cityName: String = "",
    val name: String = "",
    val date: LocalDate = LocalDate.now(),
    val rating: Float? = null,
    val cost: Float? = null,
    val notes: String = "",
    val photoUris: List<Uri> = emptyList(),
    val isSaving: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class AddRecordViewModel @Inject constructor(
    private val recordRepository: RecordRepository,
    private val cityRepository: CityRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(AddRecordUiState())
    val uiState: StateFlow<AddRecordUiState> = _uiState.asStateFlow()

    fun updateRecordType(type: RecordType) {
        _uiState.value = _uiState.value.copy(recordType = type)
    }

    fun updateCity(cityId: Long, cityName: String) {
        _uiState.value = _uiState.value.copy(cityId = cityId, cityName = cityName)
    }

    fun updateName(name: String) {
        _uiState.value = _uiState.value.copy(name = name)
    }

    fun updateDate(date: LocalDate) {
        _uiState.value = _uiState.value.copy(date = date)
    }

    fun updateRating(rating: Float?) {
        _uiState.value = _uiState.value.copy(rating = rating)
    }

    fun updateCost(cost: Float?) {
        _uiState.value = _uiState.value.copy(cost = cost)
    }

    fun updateNotes(notes: String) {
        _uiState.value = _uiState.value.copy(notes = notes)
    }

    fun addPhoto(uri: Uri) {
        _uiState.value = _uiState.value.copy(
            photoUris = _uiState.value.photoUris + uri
        )
    }

    fun removePhoto(uri: Uri) {
        _uiState.value = _uiState.value.copy(
            photoUris = _uiState.value.photoUris - uri
        )
    }

    fun saveRecord(onSuccess: () -> Unit) {
        val state = _uiState.value

        if (state.cityId == null || state.name.isBlank()) {
            _uiState.value = state.copy(error = "请填写必填项")
            return
        }

        viewModelScope.launch {
            _uiState.value = state.copy(isSaving = true, error = null)
            try {
                recordRepository.createRecord(
                    cityId = state.cityId,
                    type = state.recordType,
                    name = state.name,
                    date = state.date,
                    rating = state.rating,
                    cost = state.cost,
                    notes = state.notes.ifBlank { null },
                    photoUris = state.photoUris
                )
                onSuccess()
            } catch (e: Exception) {
                _uiState.value = state.copy(
                    isSaving = false,
                    error = "保存失败: ${e.message}"
                )
            }
        }
    }

    fun clearError() {
        _uiState.value = _uiState.value.copy(error = null)
    }
}
