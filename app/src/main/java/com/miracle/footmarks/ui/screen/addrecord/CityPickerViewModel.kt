package com.miracle.footmarks.ui.screen.addrecord

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.repository.CityRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class CityPickerUiState(
    val cities: List<CityEntity> = emptyList(),
    val filteredCities: List<CityEntity> = emptyList(),
    val searchQuery: String = "",
    val isLoading: Boolean = false
)

@HiltViewModel
class CityPickerViewModel @Inject constructor(
    private val cityRepository: CityRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(CityPickerUiState())
    val uiState: StateFlow<CityPickerUiState> = _uiState.asStateFlow()

    init {
        loadCities()
    }

    private fun loadCities() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true)
            cityRepository.getAllCities().collect { cities ->
                _uiState.value = _uiState.value.copy(
                    cities = cities,
                    filteredCities = cities,
                    isLoading = false
                )
            }
        }
    }

    fun searchCities(query: String) {
        _uiState.value = _uiState.value.copy(
            searchQuery = query,
            filteredCities = if (query.isBlank()) {
                _uiState.value.cities
            } else {
                _uiState.value.cities.filter {
                    it.name.contains(query, ignoreCase = true)
                }
            }
        )
    }

    /**
     * 确保城市存在，如果用户输入的城市不存在则创建
     */
    suspend fun ensureCityExists(cityName: String): Long {
        return cityRepository.ensureCityExists(cityName)
    }
}
