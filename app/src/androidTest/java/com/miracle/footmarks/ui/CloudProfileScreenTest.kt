package com.miracle.footmarks.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextClearance
import androidx.compose.runtime.mutableStateOf
import com.miracle.footmarks.data.local.dao.TravelStats
import com.miracle.footmarks.ui.screen.profile.CloudAccountState
import com.miracle.footmarks.ui.screen.profile.ProfileContent
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class CloudProfileScreenTest {
    @get:Rule val rule = createComposeRule()

    @Test
    fun loginFormSubmitsCredentialsAndCloudModeOffersRefresh() {
        var submitted = ""
        val account = mutableStateOf(CloudAccountState())
        rule.setContent {
            ProfileContent(
                stats = TravelStats(0, 0, 0f),
                versionName = "1.0.0",
                cloudState = account.value,
                onLogin = { username, password -> submitted = "$username:$password" }
            )
        }
        rule.onNodeWithText("共享账号").performScrollTo().assertIsDisplayed()
        rule.onNodeWithText("用户名").performTextClearance()
        rule.onNodeWithText("用户名").performTextInput("shared")
        rule.onNodeWithText("密码").performTextInput("password")
        rule.onNodeWithText("登录并同步").performClick()
        assertEquals("shared:password", submitted)

        rule.runOnIdle { account.value = CloudAccountState(isCloudMode = true) }
        rule.onNodeWithText("刷新共享记录").performScrollTo().assertIsDisplayed()
    }
}
