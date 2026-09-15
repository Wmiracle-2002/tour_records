package com.miracle.footmarks.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.junit4.StateRestorationTester
import com.miracle.footmarks.ui.screen.smartplanning.SmartPlanningScreen
import org.junit.Rule
import org.junit.Test

class SmartPlanningScreenTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun draftRemainsVisibleWhenUnavailableSendIsTapped() {
        composeRule.setContent {
            SmartPlanningScreen()
        }

        composeRule.onNodeWithText("你好，我是足迹智能规划助手").assertIsDisplayed()
        composeRule.onNodeWithText("输入你的旅行想法").performTextInput("北京三日游")
        composeRule.onNodeWithText("发送").performClick()

        composeRule.onNodeWithText("暂未开放，待完善").assertIsDisplayed()
        composeRule.onNodeWithText("输入你的旅行想法")
            .assertTextContains("北京三日游")
    }

    @Test
    fun draftSurvivesSavedStateRestoration() {
        val restorationTester = StateRestorationTester(composeRule)
        restorationTester.setContent {
            SmartPlanningScreen()
        }

        composeRule.onNodeWithText("输入你的旅行想法").performTextInput("周末去苏州")
        restorationTester.emulateSavedInstanceStateRestore()

        composeRule.onNodeWithText("输入你的旅行想法")
            .assertTextContains("周末去苏州")
    }
}
