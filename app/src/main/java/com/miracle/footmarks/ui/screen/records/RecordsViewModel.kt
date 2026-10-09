package com.miracle.footmarks.ui.screen.records

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import android.content.Context
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.repository.CityRepository
import com.miracle.footmarks.data.repository.AdministrativeDivisionRepository
import com.miracle.footmarks.data.repository.AdministrativeLocation
import com.miracle.footmarks.data.local.dao.TravelStats
import com.miracle.footmarks.data.local.dao.TripWithCityAndRecords
import com.miracle.footmarks.data.repository.TripRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import javax.inject.Inject

data class RecordsUiState(
    val trips: List<TripWithCityAndRecords> = emptyList(),
    val cities: List<CityEntity> = emptyList(),
    val stats: TravelStats = TravelStats(cityCount = 0, tripCount = 0, totalCost = 0f),
    val isLoading: Boolean = true
)

data class FootprintMapState(
    val provinceCode: String? = null,
    val provinceName: String? = null,
    val cityCode: String? = null,
    val regions: List<MapRegion> = emptyList(),
    val locations: List<AdministrativeLocation> = emptyList(),
    val validCityCodes: Set<String> = emptySet(),
    val isLoading: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class RecordsViewModel @Inject constructor(
    private val repository: TripRepository,
    private val cityRepository: CityRepository,
    private val divisions: AdministrativeDivisionRepository,
    @ApplicationContext private val context: Context
) : ViewModel() {

    private val _uiState = MutableStateFlow(RecordsUiState())
    val uiState: StateFlow<RecordsUiState> = _uiState.asStateFlow()
    private val _mapState = MutableStateFlow(FootprintMapState())
    val mapState: StateFlow<FootprintMapState> = _mapState.asStateFlow()
    private var mapJob: Job? = null

    init {
        loadTimeline()
    }

    private fun loadTimeline() {
        viewModelScope.launch {
            combine(repository.getTimeline(), repository.getTravelStats(), cityRepository.getAllCities()) { trips, stats, cities ->
                RecordsUiState(
                    trips = trips,
                    cities = cities,
                    stats = stats,
                    isLoading = false
                )
            }.collect { _uiState.value = it }
        }
    }

    fun loadMap(provinceCode: String? = null) {
        mapJob?.cancel()
        _mapState.value = _mapState.value.copy(
            provinceCode = provinceCode, cityCode = null, isLoading = true, error = null
        )
        mapJob = viewModelScope.launch {
            try {
                val loaded = withContext(Dispatchers.IO) {
                    val provinces = divisions.getProvinces()
                    val locations = provinceCode?.let(divisions::getLocations).orEmpty()
                    val country = context.assets.open("maps/100000.json").bufferedReader().use { parseMapRegions(it.readText()) }
                    val province = country.firstOrNull { it.code == provinceCode }
                    val regions = when {
                        provinceCode == null -> country
                        provinceCode in setOf("110000", "120000", "310000", "500000") || locations.isEmpty() -> listOfNotNull(province)
                        else -> context.assets.open("maps/$provinceCode.json").bufferedReader().use { parseMapRegions(it.readText()) }
                    }
                    FootprintMapState(
                        provinceCode = provinceCode, provinceName = province?.name,
                        cityCode = provinceCode?.takeIf { code -> locations.any { it.code == code } },
                        regions = regions, locations = locations,
                        validCityCodes = provinces.flatMap { divisions.getLocations(it.code) }.map { it.code }.toSet()
                    )
                }
                _mapState.value = loaded
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                _mapState.value = _mapState.value.copy(isLoading = false, error = "地图边界加载失败，请重试")
            }
        }
    }

    fun selectMapCity(code: String) {
        if (_mapState.value.locations.any { it.code == code }) {
            _mapState.value = _mapState.value.copy(cityCode = code)
        }
    }
}
