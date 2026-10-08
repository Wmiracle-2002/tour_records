package com.miracle.footmarks.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.miracle.footmarks.MainActivity
import org.junit.Rule
import org.junit.Test

class AccountNavigationTest {
    @get:Rule val rule = createAndroidComposeRule<MainActivity>()

    @Test
    fun loginPageHidesBottomNavigationAndBackReturnsToTabs() {
        rule.onNodeWithText("个人中心").performClick()
        rule.onNodeWithText("旅行者账号").performClick()
        rule.onNodeWithText("账号登录").assertIsDisplayed()
        rule.onNodeWithText("智能规划").assertDoesNotExist()
        rule.onNodeWithText("记录").assertDoesNotExist()

        rule.onNodeWithContentDescription("返回").performClick()
        rule.onNodeWithText("智能规划").performClick()
        rule.onNodeWithText("智能计划").assertIsDisplayed()
    }
}
