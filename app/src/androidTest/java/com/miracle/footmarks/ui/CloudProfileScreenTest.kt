package com.miracle.footmarks.ui

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import com.miracle.footmarks.data.local.dao.TravelStats
import com.miracle.footmarks.ui.screen.profile.CloudAccountState
import com.miracle.footmarks.ui.screen.profile.AccountManagementContent
import com.miracle.footmarks.ui.screen.profile.ProfileContent
import com.miracle.footmarks.data.remote.TokenQuotaBalance
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class CloudProfileScreenTest {
    @get:Rule val rule = createComposeRule()

    @Test
    fun profileHeaderOpensLoginOrAccountManagement() {
        var loginOpened = false
        var accountOpened = false
        val account = mutableStateOf(CloudAccountState())
        rule.setContent {
            ProfileContent(
                stats = TravelStats(0, 0, 0f),
                versionName = "1.0.0",
                cloudState = account.value,
                onOpenLogin = { loginOpened = true },
                onOpenAccount = { accountOpened = true }
            )
        }
        rule.onNodeWithText("登录或注册，保存你的旅行记录 ›").assertIsDisplayed()
        rule.onNodeWithText("旅行者账号").performClick()
        assertTrue(loginOpened)

        rule.runOnIdle { account.value = CloudAccountState(isCloudMode = true, username = "ccqq") }
        rule.onNodeWithText("ccqq").assertIsDisplayed()
        rule.onNodeWithText("已登录 · 查看账号与用量 ›").assertIsDisplayed()
        rule.onNodeWithText("ccqq").performClick()
        assertTrue(accountOpened)
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

    @Test
    fun opensPersonalKnowledgeFromProfile() {
        var opened = false
        rule.setContent {
            ProfileContent(
                stats = TravelStats(0, 0, 0f),
                versionName = "1.0.0",
                onOpenKnowledge = { opened = true }
            )
        }

        rule.onNodeWithText("我的旅行收藏").performScrollTo().assertIsDisplayed()
        rule.onNodeWithText("查看").performClick()
        assertTrue(opened)
    }

    @Test
    fun signedOutProfileKeepsTravelSectionsWithoutBottomAccountCard() {
        rule.setContent {
            ProfileContent(
                stats = TravelStats(2, 3, 0f),
                versionName = "1.0.0"
            )
        }

        val sectionTops = listOf("旅行者账号", "¥ 0.00", "旅行偏好", "我的旅行收藏", "关于足迹")
            .map { rule.onNodeWithText(it).fetchSemanticsNode().boundsInRoot.top }
        assertTrue(sectionTops.zipWithNext().all { (above, below) -> above < below })
        rule.onNodeWithText("关于足迹").performScrollTo().assertIsDisplayed()
        rule.onAllNodesWithText("开启云端旅程").assertCountEquals(0)
    }

    @Test
    fun signedInProfileShowsAccountActionsOnlyOnAccountPage() {
        var refreshed = false
        val showAccount = mutableStateOf(false)
        rule.setContent {
            if (showAccount.value) {
                AccountManagementContent(
                    state = CloudAccountState(isCloudMode = true,
                        quota = TokenQuotaBalance("2026-10", 50_000, 12_500, 0, 37_500)),
                    onRefresh = { refreshed = true }
                )
            } else {
                ProfileContent(stats = TravelStats(2, 3, 120f), versionName = "1.0.0",
                    cloudState = CloudAccountState(isCloudMode = true))
            }
        }
        rule.onAllNodesWithText("刷新云端记录").assertCountEquals(0)
        rule.runOnIdle { showAccount.value = true }
        rule.onNodeWithText("账号与同步").assertIsDisplayed()
        rule.onNodeWithText("已用 12,500 / 50,000 token").performScrollTo().assertIsDisplayed()
        rule.onNodeWithText("剩余 37,500 token").performScrollTo().assertIsDisplayed()
        rule.onNodeWithText("刷新云端记录").performScrollTo().performClick()
        assertTrue(refreshed)
        rule.onNodeWithText("修改密码").performScrollTo().assertIsDisplayed()
        rule.onNodeWithText("切换账号").performScrollTo().assertIsDisplayed()
        rule.onNodeWithText("退出登录").performScrollTo().assertIsDisplayed()
        rule.onNodeWithText("注销账号").performScrollTo().assertIsDisplayed()
    }
}
