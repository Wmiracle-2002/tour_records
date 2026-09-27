package com.miracle.footmarks.ui

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import com.miracle.footmarks.data.local.dao.TravelStats
import com.miracle.footmarks.ui.screen.profile.CloudAccountState
import com.miracle.footmarks.ui.screen.profile.ProfileContent
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class CloudProfileScreenTest {
    @get:Rule val rule = createComposeRule()

    @Test
    fun profileShowsLoginButtonAndCloudModeOffersRefresh() {
        var opened = false
        val account = mutableStateOf(CloudAccountState())
        rule.setContent {
            ProfileContent(
                stats = TravelStats(0, 0, 0f),
                versionName = "1.0.0",
                cloudState = account.value,
                onOpenLogin = { opened = true }
            )
        }
        rule.onNodeWithText("共享账号").performScrollTo().assertIsDisplayed()
        rule.onNodeWithText("登录共享账号").performClick()
        assertTrue(opened)

        rule.runOnIdle { account.value = CloudAccountState(isCloudMode = true) }
        rule.onNodeWithText("刷新共享记录").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun addsAnExplicitTravelPreferenceFromProfile() {
        var saved: Pair<String, String>? = null
        rule.setContent {
            ProfileContent(
                stats = TravelStats(0, 0, 0f),
                versionName = "1.0.0",
                cloudState = CloudAccountState(isCloudMode = true),
                onSavePreference = { category, content -> saved = category to content }
            )
        }

        rule.onNodeWithText("添加偏好").performScrollTo().performClick()
        rule.onNodeWithText("景点兴趣").performClick()
        rule.onNodeWithText("偏好内容").performTextInput("喜欢博物馆")
        rule.onNodeWithText("保存").performClick()

        assertTrue(saved == ("attraction_interest" to "喜欢博物馆"))
    }
}
