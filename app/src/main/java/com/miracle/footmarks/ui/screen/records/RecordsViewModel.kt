package com.miracle.footmarks.ui.screen.records

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.local.dao.TravelStats
import com.miracle.footmarks.data.local.dao.TripWithCityAndRecords
import com.miracle.footmarks.data.repository.TripRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import javax.inject.Inject

data class RecordsUiState(
    val trips: List<TripWithCityAndRecords> = emptyList(),
    val stats: TravelStats = TravelStats(cityCount = 0, tripCount = 0, totalCost = 0f),
    val isLoading: Boolean = true
)

@HiltViewModel
class RecordsViewModel @Inject constructor(
    private val repository: TripRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(RecordsUiState())
    val uiState: StateFlow<RecordsUiState> = _uiState.asStateFlow()

    init {
        loadTimeline()
    }

    private fun loadTimeline() {
        viewModelScope.launch {
            combine(repository.getTimeline(), repository.getTravelStats()) { trips, stats ->
                RecordsUiState(
                    trips = trips,
                    stats = stats,
                    isLoading = false
                )
            }.collect { _uiState.value = it }
        }
    }
}
