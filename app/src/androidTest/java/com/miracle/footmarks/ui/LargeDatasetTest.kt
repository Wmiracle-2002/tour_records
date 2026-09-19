package com.miracle.footmarks.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.performScrollToIndex
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.miracle.footmarks.data.local.FootmarksDatabase
import com.miracle.footmarks.data.local.entity.CityEntity
import com.miracle.footmarks.data.local.entity.RecordEntity
import com.miracle.footmarks.data.local.entity.RecordType
import com.miracle.footmarks.data.local.entity.TripEntity
import com.miracle.footmarks.data.repository.TripRepository
import com.miracle.footmarks.ui.screen.records.RecordsScreen
import com.miracle.footmarks.ui.screen.records.RecordsViewModel
import com.miracle.footmarks.ui.theme.FootmarksTheme
import java.time.LocalDate
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LargeDatasetTest {
    @get:Rule
    val composeRule = createComposeRule()

    private lateinit var database: FootmarksDatabase
    private lateinit var viewModel: RecordsViewModel
    private var cityId = 0L
    private val tripIds = mutableListOf<Long>()
    private val recordIds = mutableListOf<Long>()

    @Before
    fun seedLargeDataset() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        database = Room.inMemoryDatabaseBuilder(
            context,
            FootmarksDatabase::class.java
        ).allowMainThreadQueries().build()

        cityId = database.cityDao().insert(
            CityEntity(
                name = "压力测试城市",
                provinceCode = "stress-province",
                cityCode = "stress-city"
            )
        )
        repeat(DATASET_SIZE) { index ->
            val date = LocalDate.of(2026, 1, 1).plusDays(index.toLong())
            val dateMillis = date.toEpochDay() * DAY_MILLIS
            val tripId = database.tripDao().insert(
                TripEntity(cityId = cityId, startDate = dateMillis, endDate = dateMillis)
            )
            tripIds += tripId
            recordIds += database.recordDao().insert(
                RecordEntity(
                    tripId = tripId,
                    type = RecordType.ATTRACTION,
                    name = "stress-record-$index",
                    date = dateMillis
                )
            )
        }
        viewModel = RecordsViewModel(TripRepository(database.tripDao()))
    }

    @After
    fun removeLargeDataset() = runBlocking {
        recordIds.forEach { id ->
            database.recordDao().getById(id)?.let { database.recordDao().delete(it) }
        }
        tripIds.forEach { id ->
            database.tripDao().getById(id)?.let { database.tripDao().delete(it) }
        }
        database.cityDao().getById(cityId)?.let { database.cityDao().delete(it) }
        database.close()
    }

    @Test
    fun recordsScreenLoadsAndScrollsThroughMoreThanFiftyTrips() {
        composeRule.setContent {
            FootmarksTheme {
                RecordsScreen(
                    onRecordClick = {},
                    onAddClick = {},
                    onAddToTrip = {},
                    viewModel = viewModel
                )
            }
        }
        composeRule.waitUntil(timeoutMillis = 10_000) {
            composeRule.onAllNodesWithText("stress-record-${DATASET_SIZE - 1}")
                .fetchSemanticsNodes()
                .isNotEmpty()
        }

        composeRule.onNodeWithText("stress-record-${DATASET_SIZE - 1}").assertIsDisplayed()
        composeRule.onNode(hasScrollToIndexAction())
            .performScrollToIndex(DATASET_SIZE)
        composeRule.onNodeWithText("stress-record-0")
            .assertIsDisplayed()
    }

    private companion object {
        const val DATASET_SIZE = 60
        const val DAY_MILLIS = 86_400_000L
    }
}
