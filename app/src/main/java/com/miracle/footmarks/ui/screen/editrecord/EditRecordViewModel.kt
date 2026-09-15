package com.miracle.footmarks.ui.screen.editrecord

import android.net.Uri
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.repository.CityRepository
import com.miracle.footmarks.data.repository.RecordRepository
import com.miracle.footmarks.data.repository.TripRepository
import com.miracle.footmarks.ui.validation.RecordInputValidator
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.LocalDate
import javax.inject.Inject

data class EditRecordUiState(
    val recordId: Long = 0,
    val recordType: RecordType = RecordType.ATTRACTION,
    val cityId: Long? = null,
    val cityName: String = "",
    val tripStartDate: LocalDate = LocalDate.now(),
    val tripEndDate: LocalDate = LocalDate.now(),
    val name: String = "",
    val date: LocalDate = LocalDate.now(),
    val rating: Float? = null,
    val cost: Float? = null,
    val notes: String = "",
    val photoUris: List<Uri> = emptyList(),
    val isLoading: Boolean = false,
    val isSaving: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class EditRecordViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val recordRepository: RecordRepository,
    private val tripRepository: TripRepository,
    private val cityRepository: CityRepository
) : ViewModel() {

    private val recordId: Long = savedStateHandle.get<Long>("recordId") ?: 0L

    private val _uiState = MutableStateFlow(EditRecordUiState(recordId = recordId))
    val uiState: StateFlow<EditRecordUiState> = _uiState.asStateFlow()

    init {
        loadRecord()
    }

    private fun loadRecord() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true)
            try {
                val record = recordRepository.getRecordById(recordId)
                if (record != null) {
                    val trip = tripRepository.getTripById(record.tripId)
                    val city = trip?.let { cityRepository.getCityById(it.cityId) }
                    val photoUris = record.photoUris?.split(",")
                        ?.filter { it.isNotBlank() }
                        ?.map { Uri.parse(it) }
                        ?: emptyList()

                    _uiState.value = EditRecordUiState(
                        recordId = record.id,
                        recordType = record.type,
                        cityId = trip?.cityId,
                        cityName = city?.name ?: "",
                        tripStartDate = trip?.let {
                            LocalDate.ofEpochDay(it.startDate / 86400000L)
                        } ?: LocalDate.now(),
                        tripEndDate = trip?.let {
                            LocalDate.ofEpochDay(it.endDate / 86400000L)
                        } ?: LocalDate.now(),
                        name = record.name,
                        date = LocalDate.ofEpochDay(record.date / 86400000L),
                        rating = record.rating,
                        cost = record.cost,
                        notes = record.notes ?: "",
                        photoUris = photoUris,
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
        val state = _uiState.value
        _uiState.value = if (state.photoUris.size >= RecordInputValidator.MAX_PHOTO_COUNT) {
            state.copy(error = "每条记录最多选择9张照片")
        } else {
            state.copy(photoUris = state.photoUris + uri, error = null)
        }
    }

    fun removePhoto(uri: Uri) {
        _uiState.value = _uiState.value.copy(
            photoUris = _uiState.value.photoUris - uri
        )
    }

    fun clearError() {
        _uiState.value = _uiState.value.copy(error = null)
    }

    fun saveRecord(onSuccess: () -> Unit) {
        val currentState = _uiState.value

        val validationError = RecordInputValidator.validate(
            cityId = currentState.cityId,
            name = currentState.name,
            cost = currentState.cost,
            notes = currentState.notes,
            photoCount = currentState.photoUris.size
        )
        if (validationError != null) {
            _uiState.value = currentState.copy(error = validationError)
            return
        }

        viewModelScope.launch {
            _uiState.value = currentState.copy(isSaving = true, error = null)

            try {
                val photoUrisStr = if (currentState.photoUris.isNotEmpty()) {
                    currentState.photoUris.joinToString(",") { it.toString() }
                } else null

                val existingRecord = requireNotNull(
                    recordRepository.getRecordById(currentState.recordId)
                ) { "记录不存在" }
                val record = existingRecord.copy(
                    type = currentState.recordType,
                    name = currentState.name,
                    date = currentState.date.toEpochDay() * 86400000L,
                    rating = currentState.rating,
                    cost = currentState.cost,
                    notes = currentState.notes.ifBlank { null },
                    photoUris = photoUrisStr
                )

                recordRepository.updateRecordWithTrip(
                    record = record,
                    cityId = requireNotNull(currentState.cityId),
                    date = currentState.date,
                    photoUris = currentState.photoUris
                )
                onSuccess()
            } catch (e: Exception) {
                _uiState.value = currentState.copy(
                    isSaving = false,
                    error = "保存失败: ${e.message}"
                )
            }
        }
    }
}
