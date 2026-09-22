package com.miracle.footmarks.ui.screen.addrecord

import android.net.Uri
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.repository.CityRepository
import com.miracle.footmarks.data.repository.CloudCoordinator
import com.miracle.footmarks.data.repository.RecordRepository
import com.miracle.footmarks.data.repository.TripRepository
import com.miracle.footmarks.ui.validation.RecordInputValidator
import com.miracle.footmarks.ui.validation.TripDateValidator
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
    val tripId: Long? = null,
    val tripStartDate: LocalDate = LocalDate.now(),
    val tripEndDate: LocalDate = LocalDate.now(),
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
class AddRecordViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val recordRepository: RecordRepository,
    private val cityRepository: CityRepository,
    private val tripRepository: TripRepository,
    private val cloud: CloudCoordinator
) : ViewModel() {

    private val requestedTripId = savedStateHandle.get<Long>("tripId")?.takeIf { it > 0 }

    private val _uiState = MutableStateFlow(AddRecordUiState())
    val uiState: StateFlow<AddRecordUiState> = _uiState.asStateFlow()

    init {
        requestedTripId?.let(::loadTrip)
    }

    private fun loadTrip(tripId: Long) {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true)
            try {
                val trip = requireNotNull(tripRepository.getTripById(tripId)) { "旅行不存在" }
                val city = requireNotNull(cityRepository.getCityById(trip.cityId)) { "城市不存在" }
                val startDate = LocalDate.ofEpochDay(trip.startDate / DAY_MILLIS)
                val endDate = LocalDate.ofEpochDay(trip.endDate / DAY_MILLIS)
                _uiState.value = _uiState.value.copy(
                    tripId = trip.id,
                    cityId = trip.cityId,
                    cityName = city.name,
                    tripStartDate = startDate,
                    tripEndDate = endDate,
                    date = startDate,
                    isLoading = false
                )
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(isLoading = false, error = error.message)
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

    fun updateTripStartDate(date: LocalDate) {
        _uiState.value = _uiState.value.copy(tripStartDate = date)
    }

    fun updateTripEndDate(date: LocalDate) {
        _uiState.value = _uiState.value.copy(tripEndDate = date)
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
        _uiState.value = _uiState.value.copy(photoUris = _uiState.value.photoUris - uri)
    }

    fun saveTrip(onSuccess: (Long) -> Unit) {
        val state = _uiState.value
        val cityId = state.cityId
        if (cityId == null) {
            _uiState.value = state.copy(error = "请选择旅游城市")
            return
        }
        val dateError = TripDateValidator.validateRange(state.tripStartDate, state.tripEndDate)
        if (dateError != null) {
            _uiState.value = state.copy(error = dateError)
            return
        }

        viewModelScope.launch {
            _uiState.value = state.copy(isSaving = true, error = null)
            try {
                val tripId = if (cloud.isCloudMode) {
                    val city = requireNotNull(cityRepository.getCityById(cityId)) { "城市不存在" }
                    cloud.createTrip(city, state.tripStartDate, state.tripEndDate)
                } else {
                    tripRepository.createTrip(
                        cityId = cityId,
                        startDate = state.tripStartDate.toEpochDay() * DAY_MILLIS,
                        endDate = state.tripEndDate.toEpochDay() * DAY_MILLIS
                    )
                }
                _uiState.value = _uiState.value.copy(isSaving = false)
                onSuccess(tripId)
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    error = "保存失败: ${error.message}"
                )
            }
        }
    }

    fun saveRecord(onSuccess: () -> Unit) {
        val state = _uiState.value
        val tripId = state.tripId
        val validationError = RecordInputValidator.validate(
            cityId = state.cityId,
            name = state.name,
            cost = state.cost,
            notes = state.notes,
            photoCount = state.photoUris.size
        )
        if (validationError != null) {
            _uiState.value = state.copy(error = validationError)
            return
        }
        if (tripId == null) {
            _uiState.value = state.copy(error = "请先创建旅游记录")
            return
        }
        val dateError = TripDateValidator.validate(
            startDate = state.tripStartDate,
            endDate = state.tripEndDate,
            recordDate = state.date
        )
        if (dateError != null) {
            _uiState.value = state.copy(error = dateError)
            return
        }

        viewModelScope.launch {
            _uiState.value = state.copy(isSaving = true, error = null)
            try {
                if (cloud.isCloudMode) {
                    cloud.createRecordForTrip(
                        tripId, state.recordType, state.name, state.date,
                        state.rating, state.cost, state.notes.ifBlank { null }, state.photoUris
                    )
                } else {
                    recordRepository.createRecordForTrip(
                        tripId, state.recordType, state.name, state.date,
                        state.rating, state.cost, state.notes.ifBlank { null }, state.photoUris
                    )
                }
                onSuccess()
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    error = "保存失败: ${error.message}"
                )
            }
        }
    }

    fun clearError() {
        _uiState.value = _uiState.value.copy(error = null)
    }

    private companion object {
        const val DAY_MILLIS = 86_400_000L
    }
}
