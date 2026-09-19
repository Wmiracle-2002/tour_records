package com.miracle.footmarks.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import com.miracle.footmarks.data.local.dao.TravelStats
import com.miracle.footmarks.ui.screen.profile.ProfileContent
import org.junit.Rule
import org.junit.Test

class ProfileScreenTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun displaysLocalUserStatsAndVersion() {
        composeRule.setContent {
            ProfileContent(
                stats = TravelStats(cityCount = 3, tripCount = 5, totalCost = 1234.5f),
                versionName = "1.0.0"
            )
        }

        composeRule.onNodeWithText("本地旅行者").assertIsDisplayed()
        composeRule.onNodeWithText("3").assertIsDisplayed()
        composeRule.onNodeWithText("5").assertIsDisplayed()
        composeRule.onNodeWithText("¥ 1234.50").assertIsDisplayed()
        composeRule.onNodeWithText("版本 1.0.0")
            .performScrollTo()
            .assertIsDisplayed()
    }
}
