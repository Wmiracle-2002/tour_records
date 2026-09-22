package com.miracle.footmarks.ui.screen.tripdetail

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.local.dao.TripWithCityAndRecords
import com.miracle.footmarks.data.repository.TripRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import javax.inject.Inject

data class TripDetailUiState(
    val trip: TripWithCityAndRecords? = null,
    val isLoading: Boolean = true,
    val error: String? = null
)

@HiltViewModel
class TripDetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    tripRepository: TripRepository
) : ViewModel() {

    private val tripId: Long = savedStateHandle.get<Long>("tripId") ?: 0L
    private val _uiState = MutableStateFlow(TripDetailUiState())
    val uiState: StateFlow<TripDetailUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            tripRepository.getTimeline()
                .map { trips -> trips.firstOrNull { it.trip.id == tripId } }
                .collect { trip ->
                    _uiState.value = TripDetailUiState(
                        trip = trip,
                        isLoading = false,
                        error = trip?.let { null } ?: "旅游记录不存在"
                    )
                }
        }
    }
}
