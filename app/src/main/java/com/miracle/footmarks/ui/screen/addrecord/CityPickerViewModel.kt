package com.miracle.footmarks.ui.screen.addrecord

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.repository.AdministrativeDivisionRepository
import com.miracle.footmarks.data.repository.AdministrativeLocation
import com.miracle.footmarks.data.repository.AdministrativeProvince
import com.miracle.footmarks.data.repository.CityRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class CityPickerUiState(
    val provinces: List<AdministrativeProvince> = emptyList(),
    val selectedProvinceCode: String? = null,
    val locations: List<AdministrativeLocation> = emptyList(),
    val searchQuery: String = "",
    val isLoading: Boolean = true,
    val error: String? = null
)

@HiltViewModel
class CityPickerViewModel @Inject constructor(
    private val cityRepository: CityRepository,
    private val divisionRepository: AdministrativeDivisionRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(CityPickerUiState())
    val uiState: StateFlow<CityPickerUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { divisionRepository.getProvinces() }
                .onSuccess { provinces ->
                    val firstProvince = provinces.firstOrNull()
                    _uiState.value = CityPickerUiState(
                        provinces = provinces,
                        selectedProvinceCode = firstProvince?.code,
                        locations = firstProvince?.let { divisionRepository.getLocations(it.code) }.orEmpty(),
                        isLoading = false
                    )
                }
                .onFailure { error ->
                    _uiState.value = CityPickerUiState(
                        isLoading = false,
                        error = "行政区划数据加载失败：${error.message}"
                    )
                }
        }
    }

    fun selectProvince(provinceCode: String) {
        _uiState.value = _uiState.value.copy(
            selectedProvinceCode = provinceCode,
            locations = divisionRepository.getLocations(provinceCode),
            searchQuery = ""
        )
    }

    fun searchCities(query: String) {
        val state = _uiState.value
        _uiState.value = state.copy(
            searchQuery = query,
            locations = if (query.isBlank()) {
                state.selectedProvinceCode?.let(divisionRepository::getLocations).orEmpty()
            } else {
                divisionRepository.search(query)
            }
        )
    }

    suspend fun ensureLocationExists(location: AdministrativeLocation): Long =
        cityRepository.ensureDivisionExists(
            name = location.name,
            provinceCode = location.provinceCode,
            cityCode = location.code
        )
}
